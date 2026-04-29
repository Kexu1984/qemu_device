#!/usr/bin/env python3
"""
visualize_trace.py — Generate a self-contained HTML trace visualizer.

Usage
-----
    python3 scripts/visualize_trace.py [INPUT] [-o OUTPUT]

    INPUT   JSONL trace file  (default: build/device_trace.jsonl)
    OUTPUT  HTML output path  (default: build/trace_viz.html)

The generated HTML file is fully self-contained (no CDN, no external files).
Open it in any modern browser.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Colour palette (device rows use these in order)
# ---------------------------------------------------------------------------
_PALETTE = [
    '#4FC3F7',  # light-blue     → ConsoleUart
    '#EF9A9A',  # light-red      → DmaController
    '#A5D6A7',  # light-green    → timer
    '#CE93D8',  # light-purple   → DmaClientDemo
    '#80DEEA',  # light-cyan     → CRC
    '#FFCC80',  # light-orange   → WDT
    '#BCAAA4',  # light-brown
    '#B0BEC5',  # blue-grey
]


# ---------------------------------------------------------------------------
# Data loading / preprocessing
# ---------------------------------------------------------------------------

def load_trace(path: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    events: List[Dict[str, Any]] = []
    header: Optional[Dict[str, Any]] = None
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get('event') in ('HEADER', '_header'):
                header = rec
            else:
                events.append(rec)
    return events, header


def pair_dma_transfers(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Match CH_START → CH_DONE pairs to compute actual transfer latencies."""
    transfers: List[Dict[str, Any]] = []
    pending: Dict[int, Dict[str, Any]] = {}
    for e in events:
        ev = e.get('event', '')
        ch = e.get('ch')
        if ev == 'CH_START' and ch is not None:
            pending[ch] = e
        elif ev in ('CH_DONE',) and ch is not None and ch in pending:
            start = pending.pop(ch)
            t0 = start.get('t_virt_ns') or 0
            t1 = e.get('t_virt_ns') or 0
            length = start.get('length', 0)
            expected_ns = start.get('latency_ns')
            actual_ns = t1 - t0
            transfers.append({
                'ch':          ch,
                'src':         hex(start['src']) if isinstance(start.get('src'), int) else start.get('src'),
                'dst':         hex(start['dst']) if isinstance(start.get('dst'), int) else start.get('dst'),
                'length':      length,
                'mode':        start.get('mode', '?'),
                'expected_ns': expected_ns,
                'actual_ns':   actual_ns,
                'ok':          e.get('ok', True),
                't_start_ns':  t0,
                't_end_ns':    t1,
                'dev':         start.get('dev', ''),
            })
    return transfers


def build_dev_stats(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for e in events:
        d = e.get('dev', 'unknown')
        ev = e.get('event', '?')
        if d not in stats:
            stats[d] = {'total': 0, 'by_event': {}}
        stats[d]['total'] += 1
        stats[d]['by_event'][ev] = stats[d]['by_event'].get(ev, 0) + 1
    return stats


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(
    events: List[Dict[str, Any]],
    transfers: List[Dict[str, Any]],
    dev_stats: Dict[str, Any],
    header: Optional[Dict[str, Any]],
    title: str,
) -> str:
    devices = list(dict.fromkeys(e['dev'] for e in events if 'dev' in e))
    colour_map = {d: _PALETTE[i % len(_PALETTE)] for i, d in enumerate(devices)}

    vtimes = [e['t_virt_ns'] for e in events if e.get('t_virt_ns') is not None]
    t_min = min(vtimes) if vtimes else 0
    t_max = max(vtimes) if vtimes else 1_000_000

    meta = {
        'total':      len(events),
        't_min_ns':   t_min,
        't_max_ns':   t_max,
        'title':      title,
        'trace_file': (header or {}).get('path', (header or {}).get('file', 'unknown')),
    }

    html = _HTML_TEMPLATE
    html = html.replace('/*__EVENTS__*/',    f'const EVENTS={json.dumps(events, separators=(",",":"))};')
    html = html.replace('/*__DEVICES__*/',   f'const DEVICES={json.dumps(devices)};')
    html = html.replace('/*__COLOURS__*/',   f'const COLOURS={json.dumps(colour_map)};')
    html = html.replace('/*__TRANSFERS__*/', f'const TRANSFERS={json.dumps(transfers, separators=(",",":"))};')
    html = html.replace('/*__META__*/',      f'const META={json.dumps(meta)};')
    html = html.replace('/*__DEVSTATS__*/',  f'const DEVSTATS={json.dumps(dev_stats)};')
    html = html.replace('__PAGE_TITLE__',    title)
    return html


# ---------------------------------------------------------------------------
# HTML / CSS / JS template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__PAGE_TITLE__</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #0f1117;
  --surface:  #1a1f2e;
  --surface2: #242938;
  --border:   #2d3451;
  --text:     #e2e8f0;
  --muted:    #8892a4;
  --accent:   #4f9eff;
}

body {
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
}

header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 24px;
  display: flex;
  align-items: center;
  gap: 20px;
  position: sticky;
  top: 0;
  z-index: 100;
}

header h1 { font-size: 17px; font-weight: 600; white-space: nowrap; }
header h1 span { color: var(--accent); }

.meta-chips { display: flex; gap: 10px; flex-wrap: wrap; }
.chip {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 2px 10px;
  font-size: 11px;
  color: var(--muted);
}
.chip strong { color: var(--text); }

main { padding: 20px 24px; display: flex; flex-direction: column; gap: 24px; }

section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.sec-header {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface2);
}
.sec-header h2 { font-size: 13px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); }

/* Summary cards */
#summary-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1px;
  background: var(--border);
}
.dev-card {
  background: var(--surface);
  padding: 14px 16px;
}
.dev-card .dev-name {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dev-card .dev-total {
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 6px;
}
.dev-card .event-pills { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--muted);
}

/* Timeline */
#timeline-controls {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
#timeline-controls label { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 8px; }
#zoom-slider {
  -webkit-appearance: none;
  width: 160px; height: 4px;
  background: var(--border); border-radius: 2px; outline: none; cursor: pointer;
}
#zoom-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 14px; height: 14px;
  background: var(--accent); border-radius: 50%;
}
#zoom-label { font-size: 12px; color: var(--accent); min-width: 36px; }
.btn {
  padding: 4px 12px; border-radius: 4px; font-size: 11px; cursor: pointer;
  background: var(--surface2); border: 1px solid var(--border); color: var(--text);
}
.btn:hover { border-color: var(--accent); color: var(--accent); }

.legend { display: flex; flex-wrap: wrap; gap: 10px; }
.legend-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; }
.legend-rect { width: 14px; height: 8px; border-radius: 2px; opacity: 0.7; }

#canvas-wrap {
  overflow-x: auto;
  overflow-y: hidden;
  cursor: crosshair;
  position: relative;
  background: var(--bg);
}
#tl-canvas { display: block; }

/* Tooltip */
#tooltip {
  position: fixed;
  display: none;
  background: var(--surface2);
  border: 1px solid var(--accent);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 11px;
  line-height: 1.7;
  pointer-events: none;
  z-index: 1000;
  max-width: 320px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
#tooltip .tt-event { font-size: 13px; font-weight: 700; margin-bottom: 4px; }
#tooltip .tt-row { display: flex; gap: 8px; }
#tooltip .tt-key { color: var(--muted); min-width: 70px; }
#tooltip .tt-val { color: var(--text); word-break: break-all; }

/* DMA table + event log */
.table-wrap { overflow-x: auto; padding: 0; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
thead th {
  background: var(--surface2);
  color: var(--muted);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.06em;
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
tbody td {
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: var(--surface2); }

.badge {
  display: inline-block;
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 10px;
  font-weight: 600;
  font-family: monospace;
}
.badge-ok   { background: #1b5e2044; color: #69f0ae; border: 1px solid #2e7d3266; }
.badge-fail { background: #b71c1c44; color: #ff5252; border: 1px solid #c62828aa; }
.badge-mode { background: #1a237e44; color: #82b1ff; border: 1px solid #283593aa; }

/* Search bar */
.search-row { padding: 10px 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--border); }
#search-box {
  flex: 1; max-width: 360px;
  background: var(--bg); border: 1px solid var(--border);
  color: var(--text); padding: 5px 10px; border-radius: 4px; font-size: 12px;
  outline: none;
}
#search-box:focus { border-color: var(--accent); }
#log-count { color: var(--muted); font-size: 11px; }

/* DMA latency bar chart */
#dma-latency-chart {
  padding: 16px;
  border-top: 1px solid var(--border);
}
.latency-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; font-size: 11px; }
.latency-label { width: 80px; text-align: right; color: var(--muted); font-family: monospace; }
.latency-bar-wrap { flex: 1; background: var(--surface2); border-radius: 3px; height: 16px; }
.latency-bar { height: 100%; border-radius: 3px; min-width: 2px; display: flex; align-items: center; padding-left: 6px; font-size: 10px; }
.latency-val { min-width: 70px; font-family: monospace; color: var(--muted); }

.empty-state { padding: 32px; text-align: center; color: var(--muted); }
</style>
</head>
<body>

<header>
  <h1>&#x1F4E1; <span>Device Trace</span> Viewer</h1>
  <div id="header-meta" class="meta-chips"></div>
</header>

<main>

<!-- ═══ 1. SUMMARY ═══════════════════════════════════════════════════════ -->
<section id="sec-summary">
  <div class="sec-header">
    <h2>&#x2699; Device Summary</h2>
  </div>
  <div id="summary-cards"></div>
</section>

<!-- ═══ 2. TIMELINE ══════════════════════════════════════════════════════ -->
<section id="sec-timeline">
  <div class="sec-header">
    <h2>&#x23F1; Event Timeline</h2>
    <div class="legend" id="event-legend"></div>
  </div>
  <div id="timeline-controls">
    <label>Zoom <input type="range" id="zoom-slider" min="1" max="200" step="1" value="1">
      <span id="zoom-label">1&#xd7;</span>
    </label>
    <button class="btn" onclick="resetZoom()">Reset</button>
    <span style="color:var(--muted);font-size:11px">Scroll to pan &nbsp;&#x2022;&nbsp; Hover for details</span>
  </div>
  <div id="canvas-wrap">
    <canvas id="tl-canvas"></canvas>
  </div>
</section>

<!-- ═══ 3. DMA ANALYSIS ══════════════════════════════════════════════════ -->
<section id="sec-dma">
  <div class="sec-header">
    <h2>&#x26A1; DMA Transfer Analysis</h2>
  </div>
  <div id="dma-empty" class="empty-state" style="display:none">No DMA transfers found in trace.</div>
  <div id="dma-content">
    <div class="table-wrap">
      <table id="dma-table">
        <thead>
          <tr>
            <th>#</th>
            <th>CH</th>
            <th>Mode</th>
            <th>Length</th>
            <th>Source</th>
            <th>Destination</th>
            <th>Expected Latency</th>
            <th>Actual Latency</th>
            <th>Delta</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody id="dma-tbody"></tbody>
      </table>
    </div>
    <div id="dma-latency-chart"></div>
  </div>
</section>

<!-- ═══ 4. EVENT LOG ══════════════════════════════════════════════════════ -->
<section id="sec-log">
  <div class="sec-header">
    <h2>&#x1F4CB; Event Log</h2>
  </div>
  <div class="search-row">
    <input id="search-box" type="text" placeholder="Filter events by device, event name, or any field…" oninput="filterLog()">
    <span id="log-count"></span>
  </div>
  <div class="table-wrap">
    <table id="log-table">
      <thead>
        <tr>
          <th>Seq</th>
          <th>Virtual Time</th>
          <th>Device</th>
          <th>Event</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody id="log-tbody"></tbody>
    </table>
  </div>
</section>

</main>

<div id="tooltip"></div>

<script>
/*__EVENTS__*/
/*__DEVICES__*/
/*__COLOURS__*/
/*__TRANSFERS__*/
/*__META__*/
/*__DEVSTATS__*/

// ── Constants ──────────────────────────────────────────────────────────────
const LABEL_W  = 185;   // px — left column for device names
const LANE_H   = 46;    // px — height of each device lane
const AXIS_H   = 28;    // px — bottom axis area
const PADDING  = 8;     // px — top/bottom lane padding

// Event type → colour mapping
const EV_COLOUR = {
  // DMA
  'CH_START':   '#FF5252', 'CH_DREQ':   '#FF8A65',
  'CH_DONE':    '#FF1744', 'IRQ_PULSE': '#FF6D00',
  // UART
  'TX':         '#42A5F5', 'IRQ_FIRE':  '#1E88E5', 'IRQ_ASSERT': '#1565C0',
  // Timer
  'ARM':        '#66BB6A', 'DISARM':    '#43A047',
  'EXPIRE':     '#1B5E20', 'INTCLR':    '#A5D6A7',
  // WDT
  'LOAD':       '#FFA726', 'KICK':      '#FF9800',
  'TIMEOUT':    '#E65100', 'IRQ_PULSE_WDT': '#CE93D8',
  // CRC
  'DATA_WRITE': '#26C6DA', 'RESULT':    '#00E5FF',
  // General
  'RESET':      '#9E9E9E',
};

// ── Utility functions ──────────────────────────────────────────────────────
function fmtNs(ns) {
  if (ns == null) return '—';
  if (ns < 1000)         return ns.toFixed(0) + ' ns';
  if (ns < 1_000_000)    return (ns / 1000).toFixed(1) + ' µs';
  if (ns < 1_000_000_000) return (ns / 1_000_000).toFixed(2) + ' ms';
  return (ns / 1_000_000_000).toFixed(3) + ' s';
}

function shortName(dev) {
  // "DmaController(2ch)" → "DmaCtrl(2ch)"
  return dev
    .replace('DmaController', 'DmaCtrl')
    .replace('ConsoleUart',   'UART')
    .replace('DmaClientDemo', 'DmaClient')
    .replace('CRC-32',        'CRC-32')
    .replace('timer0',        'Timer0');
}

function evColour(evName, dev) {
  return EV_COLOUR[evName] || COLOURS[dev] || '#aaa';
}

function fmtFields(e) {
  const skip = new Set(['seq','t_wall_ns','t_virt_ns','dev','event']);
  return Object.entries(e)
    .filter(([k]) => !skip.has(k))
    .map(([k, v]) => {
      const disp = (typeof v === 'number' && v > 0xFFFF && k !== 'length' && k !== 'latency_ns' && k !== 'seq')
        ? '0x' + v.toString(16).padStart(8,'0')
        : String(v);
      return `<span style="color:var(--muted)">${k}</span>=<span>${disp}</span>`;
    })
    .join('  ');
}

// ── 1. Header meta ─────────────────────────────────────────────────────────
function renderHeader() {
  const el = document.getElementById('header-meta');
  const range = META.t_max_ns - META.t_min_ns;
  el.innerHTML = [
    `<span class="chip">&#x1F4C4; <strong>${META.trace_file.split('/').pop()}</strong></span>`,
    `<span class="chip">Events: <strong>${META.total.toLocaleString()}</strong></span>`,
    `<span class="chip">Duration: <strong>${fmtNs(range)}</strong></span>`,
    `<span class="chip">Devices: <strong>${DEVICES.length}</strong></span>`,
  ].join('');
}

// ── 2. Summary cards ───────────────────────────────────────────────────────
function renderSummary() {
  const container = document.getElementById('summary-cards');
  container.innerHTML = DEVICES.map(dev => {
    const stats = DEVSTATS[dev] || {total: 0, by_event: {}};
    const colour = COLOURS[dev] || '#aaa';
    const pills = Object.entries(stats.by_event)
      .sort((a,b) => b[1]-a[1])
      .slice(0, 8)
      .map(([ev, n]) =>
        `<span class="pill" style="border-color:${evColour(ev,dev)}44">${ev} <strong>${n}</strong></span>`
      ).join('');
    return `
      <div class="dev-card">
        <div class="dev-name" style="color:${colour}">${shortName(dev)}</div>
        <div class="dev-total" style="color:${colour}">${stats.total.toLocaleString()}</div>
        <div style="font-size:10px;color:var(--muted)">events</div>
        <div class="event-pills">${pills}</div>
      </div>`;
  }).join('');
}

// ── 3. Timeline ────────────────────────────────────────────────────────────
let viewMin = META.t_min_ns;
let viewMax = META.t_max_ns;

function nsToX(ns, canvasW) {
  const tw = canvasW - LABEL_W;
  return LABEL_W + (ns - viewMin) / (viewMax - viewMin) * tw;
}

function xToNs(x, canvasW) {
  const tw = canvasW - LABEL_W;
  return viewMin + (x - LABEL_W) / tw * (viewMax - viewMin);
}

function canvasHeight() {
  return DEVICES.length * LANE_H + AXIS_H;
}

function drawTimeline() {
  const wrap  = document.getElementById('canvas-wrap');
  const canvas = document.getElementById('tl-canvas');
  const W = Math.max(wrap.clientWidth, 800);
  const H = canvasHeight();
  if (canvas.width !== W || canvas.height !== H) {
    canvas.width  = W;
    canvas.height = H;
  }
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,W,H);

  // Background
  ctx.fillStyle = '#0f1117';
  ctx.fillRect(0,0,W,H);

  // Device lane backgrounds
  DEVICES.forEach((dev, i) => {
    const y = i * LANE_H;
    ctx.fillStyle = i % 2 === 0 ? '#141822' : '#0f1117';
    ctx.fillRect(LABEL_W, y, W - LABEL_W, LANE_H);

    // Label area
    ctx.fillStyle = '#1a1f2e';
    ctx.fillRect(0, y, LABEL_W, LANE_H);

    // Colour indicator bar on left edge
    ctx.fillStyle = COLOURS[dev] || '#aaa';
    ctx.fillRect(0, y + 6, 3, LANE_H - 12);

    // Device name
    ctx.font = 'bold 11px "Segoe UI", system-ui, sans-serif';
    ctx.fillStyle = COLOURS[dev] || '#aaa';
    ctx.fillText(shortName(dev), 10, y + LANE_H/2 + 4);

    // Lane separator
    ctx.strokeStyle = '#1e2538';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y + LANE_H - 0.5);
    ctx.lineTo(W, y + LANE_H - 0.5);
    ctx.stroke();
  });

  // Vertical label separator
  ctx.strokeStyle = '#2d3451';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(LABEL_W - 0.5, 0);
  ctx.lineTo(LABEL_W - 0.5, H - AXIS_H);
  ctx.stroke();

  // Time axis grid lines
  const tRange = viewMax - viewMin;
  const rawStep = tRange / 10;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const niceStep = Math.ceil(rawStep / mag) * mag;
  const tStart = Math.ceil(viewMin / niceStep) * niceStep;

  ctx.strokeStyle = '#1e2538';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#4a5568';
  ctx.font = '10px monospace';
  ctx.textAlign = 'center';

  for (let t = tStart; t <= viewMax; t += niceStep) {
    const x = nsToX(t, W);
    if (x < LABEL_W || x > W) continue;
    // Grid line
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H - AXIS_H);
    ctx.stroke();
    // Tick + label
    ctx.fillStyle = '#4a5568';
    ctx.fillText(fmtNs(t - META.t_min_ns), x, H - AXIS_H + 14);
  }

  // Axis baseline
  ctx.strokeStyle = '#2d3451';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(LABEL_W, H - AXIS_H);
  ctx.lineTo(W, H - AXIS_H);
  ctx.stroke();

  // DMA transfer rectangles (rendered behind events)
  TRANSFERS.forEach(tx => {
    const devIdx = DEVICES.findIndex(d => d.includes('DmaController') || d === tx.dev);
    if (devIdx < 0) return;
    const x1 = nsToX(tx.t_start_ns, W);
    const x2 = nsToX(tx.t_end_ns, W);
    if (x2 < LABEL_W || x1 > W) return;
    const y = devIdx * LANE_H;
    ctx.fillStyle = tx.ok ? 'rgba(76,175,80,0.18)' : 'rgba(244,67,54,0.22)';
    ctx.fillRect(Math.max(x1, LABEL_W), y + 4, Math.max(x2 - Math.max(x1, LABEL_W), 2), LANE_H - 8);
    ctx.strokeStyle = tx.ok ? 'rgba(76,175,80,0.5)' : 'rgba(244,67,54,0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(Math.max(x1, LABEL_W), y + 4, Math.max(x2 - Math.max(x1, LABEL_W), 2), LANE_H - 8);
  });

  // Events as circles
  const R = 4;
  EVENTS.forEach(e => {
    if (e.t_virt_ns == null) return;
    const devIdx = DEVICES.indexOf(e.dev);
    if (devIdx < 0) return;
    const x = nsToX(e.t_virt_ns, W);
    if (x < LABEL_W - R || x > W + R) return;
    const cy = devIdx * LANE_H + LANE_H / 2;
    ctx.fillStyle = evColour(e.event, e.dev);
    ctx.beginPath();
    ctx.arc(x, cy, R, 0, Math.PI * 2);
    ctx.fill();
  });
}

// Tooltip logic
let _cachedHitMap = null;

function buildHitMap(canvasW) {
  if (_cachedHitMap && _cachedHitMap.w === canvasW && _cachedHitMap.vMin === viewMin) return _cachedHitMap;
  const entries = EVENTS
    .filter(e => e.t_virt_ns != null && DEVICES.indexOf(e.dev) >= 0)
    .map(e => ({
      x:  nsToX(e.t_virt_ns, canvasW),
      cy: DEVICES.indexOf(e.dev) * LANE_H + LANE_H / 2,
      e,
    }));
  _cachedHitMap = { entries, w: canvasW, vMin: viewMin };
  return _cachedHitMap;
}

const tooltip = document.getElementById('tooltip');

function onCanvasMouseMove(ev) {
  const canvas = document.getElementById('tl-canvas');
  const rect   = canvas.getBoundingClientRect();
  const mx = ev.clientX - rect.left;
  const my = ev.clientY - rect.top;
  if (mx < LABEL_W) { hideTooltip(); return; }

  const hm = buildHitMap(canvas.width);
  let best = null, bestD = 12;
  for (const item of hm.entries) {
    const d = Math.hypot(item.x - mx, item.cy - my);
    if (d < bestD) { bestD = d; best = item; }
  }

  if (!best) { hideTooltip(); return; }
  showTooltip(best.e, ev.clientX, ev.clientY);
}

function showTooltip(e, cx, cy) {
  const skip = new Set(['seq','t_wall_ns','t_virt_ns','dev','event']);
  const fields = Object.entries(e).filter(([k]) => !skip.has(k));
  const color = evColour(e.event, e.dev);
  tooltip.style.display = 'block';
  tooltip.innerHTML = `
    <div class="tt-event" style="color:${color}">${e.event}</div>
    <div class="tt-row"><span class="tt-key">seq</span><span class="tt-val">${e.seq}</span></div>
    <div class="tt-row"><span class="tt-key">virt time</span><span class="tt-val">${fmtNs(e.t_virt_ns)}</span></div>
    <div class="tt-row"><span class="tt-key">device</span><span class="tt-val" style="color:${COLOURS[e.dev]||'#aaa'}">${shortName(e.dev)}</span></div>
    ${fields.map(([k,v]) => {
      const disp = (typeof v === 'number' && v > 0xFFFF && k !== 'length' && k !== 'latency_ns')
        ? '0x' + v.toString(16).padStart(8,'0') : String(v);
      return `<div class="tt-row"><span class="tt-key">${k}</span><span class="tt-val">${disp}</span></div>`;
    }).join('')}`;
  const W = window.innerWidth, H = window.innerHeight;
  const tw = 280, th = 200;
  const tx = cx + 14 + tw > W ? cx - tw - 8 : cx + 14;
  const ty = cy + th > H     ? cy - th      : cy + 10;
  tooltip.style.left = tx + 'px';
  tooltip.style.top  = ty + 'px';
}

function hideTooltip() {
  tooltip.style.display = 'none';
}

// Zoom via slider
function applyZoom() {
  const slider = document.getElementById('zoom-slider');
  const z = parseFloat(slider.value);
  document.getElementById('zoom-label').textContent = z.toFixed(0) + '×';
  const center = (viewMin + viewMax) / 2;
  const halfRange = (META.t_max_ns - META.t_min_ns) / (2 * z);
  viewMin = Math.max(META.t_min_ns, center - halfRange);
  viewMax = Math.min(META.t_max_ns, center + halfRange);
  _cachedHitMap = null;
  drawTimeline();
}

function resetZoom() {
  viewMin = META.t_min_ns;
  viewMax = META.t_max_ns;
  document.getElementById('zoom-slider').value = 1;
  document.getElementById('zoom-label').textContent = '1×';
  _cachedHitMap = null;
  drawTimeline();
}

// Wheel zoom (zoom towards mouse position)
function onCanvasWheel(ev) {
  ev.preventDefault();
  const canvas = document.getElementById('tl-canvas');
  const rect   = canvas.getBoundingClientRect();
  const mx = ev.clientX - rect.left;
  if (mx < LABEL_W) return;

  const factor = ev.deltaY < 0 ? 0.75 : 1.33;
  const pivotNs = xToNs(mx, canvas.width);
  const newRange = (viewMax - viewMin) * factor;
  const maxRange = META.t_max_ns - META.t_min_ns;
  const clampedRange = Math.min(maxRange, Math.max(1_000_000, newRange));
  const ratio = (pivotNs - viewMin) / (viewMax - viewMin);
  viewMin = Math.max(META.t_min_ns, pivotNs - ratio * clampedRange);
  viewMax = Math.min(META.t_max_ns, viewMin + clampedRange);
  // Sync slider
  const z = maxRange / (viewMax - viewMin);
  const slider = document.getElementById('zoom-slider');
  slider.value = Math.min(200, Math.max(1, z)).toFixed(0);
  document.getElementById('zoom-label').textContent = parseFloat(slider.value).toFixed(0) + '×';
  _cachedHitMap = null;
  drawTimeline();
}

function buildLegend() {
  const container = document.getElementById('event-legend');
  const shown = new Set();
  const items = [
    { label: 'DMA xfer', type: 'rect', color: 'rgba(76,175,80,0.4)', border: 'rgba(76,175,80,0.7)' },
    ...Object.entries(EV_COLOUR).map(([ev, c]) => ({ label: ev, type: 'dot', color: c })),
  ];
  container.innerHTML = items.slice(0,12).map(it => {
    const shape = it.type === 'rect'
      ? `<span class="legend-rect" style="background:${it.color};border:1px solid ${it.border||it.color}"></span>`
      : `<span class="legend-dot" style="background:${it.color}"></span>`;
    return `<span class="legend-item">${shape} ${it.label}</span>`;
  }).join('');
}

// ── 4. DMA Analysis ────────────────────────────────────────────────────────
function renderDmaTable() {
  if (!TRANSFERS.length) {
    document.getElementById('dma-empty').style.display = '';
    document.getElementById('dma-content').style.display = 'none';
    return;
  }

  const tbody = document.getElementById('dma-tbody');
  tbody.innerHTML = TRANSFERS.map((tx, i) => {
    const delta = tx.actual_ns != null && tx.expected_ns != null
      ? tx.actual_ns - tx.expected_ns : null;
    const deltaStr = delta == null ? '—' :
      (delta >= 0 ? `+${fmtNs(delta)}` : `−${fmtNs(-delta)}`);
    const deltaCol = delta == null ? '' :
      (Math.abs(delta) < 500_000 ? 'color:#69f0ae' : 'color:#ff5252');
    return `
      <tr>
        <td style="color:var(--muted)">${i+1}</td>
        <td>CH${tx.ch}</td>
        <td><span class="badge badge-mode">${tx.mode}</span></td>
        <td><strong>${tx.length}</strong> B</td>
        <td style="font-size:10px">${tx.src || '—'}</td>
        <td style="font-size:10px">${tx.dst || '—'}</td>
        <td>${tx.expected_ns != null ? fmtNs(tx.expected_ns) : '—'}</td>
        <td><strong>${fmtNs(tx.actual_ns)}</strong></td>
        <td style="${deltaCol}">${deltaStr}</td>
        <td><span class="badge ${tx.ok ? 'badge-ok' : 'badge-fail'}">${tx.ok ? 'OK' : 'FAIL'}</span></td>
      </tr>`;
  }).join('');

  // Latency bar chart (size vs expected latency)
  const chart = document.getElementById('dma-latency-chart');
  const unique = [...new Map(TRANSFERS.map(tx => [tx.length, tx])).values()]
    .sort((a,b) => a.length - b.length);
  const maxNs = Math.max(...unique.map(tx => tx.expected_ns || 0)) || 1;

  chart.innerHTML = `
    <div style="color:var(--muted);font-size:11px;margin-bottom:10px;font-weight:600;text-transform:uppercase;letter-spacing:.05em">
      Transfer Size → Expected Latency  (HCLK=48MHz · PCLK=12MHz)
    </div>
    ${unique.map(tx => {
      const pct = (tx.expected_ns || 0) / maxNs * 100;
      const color = tx.mode === 'M2M' ? '#4FC3F7' : tx.mode === 'M2P' ? '#EF9A9A' : '#A5D6A7';
      return `
        <div class="latency-row">
          <span class="latency-label">${tx.length} B (${tx.mode})</span>
          <div class="latency-bar-wrap">
            <div class="latency-bar" style="width:${pct}%;background:${color}44;border:1px solid ${color}88">
              <span style="color:${color};font-weight:600">${fmtNs(tx.expected_ns)}</span>
            </div>
          </div>
          <span class="latency-val">${tx.expected_ns} ns</span>
        </div>`;
    }).join('')}`;
}

// ── 5. Event log ───────────────────────────────────────────────────────────
let _filteredEvents = EVENTS;
const LOG_PAGE = 300;

function filterLog() {
  const q = document.getElementById('search-box').value.trim().toLowerCase();
  _filteredEvents = q
    ? EVENTS.filter(e => {
        return e.dev.toLowerCase().includes(q) ||
               e.event.toLowerCase().includes(q) ||
               JSON.stringify(e).toLowerCase().includes(q);
      })
    : EVENTS;
  renderLogPage();
}

function renderLogPage() {
  const rows = _filteredEvents.slice(0, LOG_PAGE);
  const tbody = document.getElementById('log-tbody');
  tbody.innerHTML = rows.map(e => {
    const col = COLOURS[e.dev] || '#aaa';
    const evcol = evColour(e.event, e.dev);
    return `
      <tr>
        <td style="color:var(--muted)">${e.seq}</td>
        <td>${fmtNs(e.t_virt_ns)}</td>
        <td style="color:${col}">${shortName(e.dev)}</td>
        <td style="color:${evcol};font-weight:600">${e.event}</td>
        <td style="font-size:11px;color:var(--muted)">${fmtFields(e)}</td>
      </tr>`;
  }).join('');
  const total = _filteredEvents.length;
  document.getElementById('log-count').textContent =
    total <= LOG_PAGE
      ? `${total.toLocaleString()} events`
      : `${LOG_PAGE} of ${total.toLocaleString()} events (refine filter to see more)`;
}

// ── Init ───────────────────────────────────────────────────────────────────
function init() {
  renderHeader();
  renderSummary();
  buildLegend();
  drawTimeline();
  renderDmaTable();
  renderLogPage();

  const canvas = document.getElementById('tl-canvas');
  canvas.addEventListener('mousemove', onCanvasMouseMove);
  canvas.addEventListener('mouseleave', hideTooltip);
  canvas.addEventListener('wheel', onCanvasWheel, { passive: false });

  document.getElementById('zoom-slider').addEventListener('input', applyZoom);
  window.addEventListener('resize', () => { _cachedHitMap = null; drawTimeline(); });
}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description='Generate a self-contained HTML trace visualizer from device_trace.jsonl',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument('input',  nargs='?', default='build/device_trace.jsonl',
                    help='JSONL trace file to read')
    ap.add_argument('-o', '--output', default='build/trace_viz.html',
                    help='HTML output path')
    ap.add_argument('--title', default='KX6625 Device Trace',
                    help='Page title shown in the browser')
    args = ap.parse_args()

    trace_path = args.input
    if not Path(trace_path).exists():
        print(f'ERROR: trace file not found: {trace_path}', file=sys.stderr)
        sys.exit(1)

    print(f'Loading trace: {trace_path}', flush=True)
    events, header = load_trace(trace_path)
    print(f'  {len(events)} events loaded', flush=True)

    transfers = pair_dma_transfers(events)
    print(f'  {len(transfers)} DMA transfers paired', flush=True)

    dev_stats = build_dev_stats(events)

    html = generate_html(events, transfers, dev_stats, header, args.title)

    out = args.output
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(html)

    size_kb = Path(out).stat().st_size // 1024
    print(f'Generated: {out}  ({size_kb} KB)', flush=True)
    print(f'Open in browser:  xdg-open {out}', flush=True)


if __name__ == '__main__':
    main()
