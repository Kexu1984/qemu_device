#!/usr/bin/env python3
"""
Device Code Generator
=====================

Reads ``spec/devices.yaml`` and writes two generated files:

  build/generated/mmio_devices.h            — C header for firmware drivers
  device_model/generated/device_consts.py  — Python constants for tools/tests

Run via ``make gen`` or directly::

    python3 scripts/gen_device_code.py [--config path/to/devices.yaml]
             [--c-out path/to/mmio_devices.h]
             [--py-out path/to/device_consts.py]

Neither generated file should be committed to version control; they are
created at build time from the authoritative ``spec/devices.yaml``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit(
        "ERROR: PyYAML is not installed.  Run:  pip install pyyaml\n"
        "       or:                             pip3 install pyyaml"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex(value: int, width: int = 8) -> str:
    """Return a zero-padded uppercase hex string, e.g. '0x10020000'."""
    return f"0x{value:0{width}X}"


def _upper(name: str) -> str:
    """Convert snake_case device/register name to UPPER_CASE macro prefix."""
    return name.strip().upper()


def _load_config(path: Path) -> dict[str, Any]:
    spec_dir = path.parent
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    # Merge per-device register specs referenced via the 'spec:' field.
    # If a device has both inline 'registers:' and 'spec:', the inline
    # registers take precedence (allows selective overrides).
    for dev in cfg.get("devices", []):
        if "spec" in dev and "registers" not in dev:
            dev_yaml = spec_dir / dev["spec"]
            if not dev_yaml.exists():
                sys.exit(
                    f"ERROR: device '{dev.get('name', '?')}' references "
                    f"spec: '{dev['spec']}' but file not found: {dev_yaml}"
                )
            with open(dev_yaml, encoding="utf-8") as fh:
                dev_spec = yaml.safe_load(fh)
            dev["registers"] = dev_spec.get("registers", [])

    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    """Minimal schema check — fail early with a clear message."""
    required_top = {"platform", "devices"}
    for key in required_top:
        if key not in cfg:
            sys.exit(f"ERROR: config is missing top-level key '{key}'")

    plat = cfg["platform"]
    for key in ("nvic_base",):
        if key not in plat:
            sys.exit(f"ERROR: platform section is missing '{key}'")

    seen_names: set[str] = set()
    seen_bases: dict[int, str] = {}
    seen_rw_ports: dict[int, str] = {}
    seen_irq_ports: dict[int, str] = {}

    for dev in cfg["devices"]:
        for key in ("name", "base_addr", "size", "irq_num",
                    "irq_delay", "rw_port", "irq_port", "registers"):
            if key not in dev:
                sys.exit(
                    f"ERROR: device '{dev.get('name', '?')}' is missing field '{key}'"
                )

        name = dev["name"]
        if name in seen_names:
            sys.exit(f"ERROR: duplicate device name '{name}'")
        seen_names.add(name)

        base = int(dev["base_addr"])
        if base in seen_bases:
            sys.exit(
                f"ERROR: device '{name}' has the same base_addr as '{seen_bases[base]}'"
            )
        seen_bases[base] = name

        for port_dict, port_key, label in (
            (seen_rw_ports,  "rw_port",  "rw_port"),
            (seen_irq_ports, "irq_port", "irq_port"),
        ):
            port = int(dev[port_key])
            if port in port_dict:
                sys.exit(
                    f"ERROR: device '{name}' shares {label} {port} "
                    f"with '{port_dict[port]}'"
                )
            port_dict[port] = name

        for reg in dev["registers"]:
            for key in ("offset", "name", "access", "description"):
                if key not in reg:
                    sys.exit(
                        f"ERROR: register in device '{name}' is missing '{key}'"
                    )
            if reg["access"] not in ("R", "W", "RW"):
                sys.exit(
                    f"ERROR: device '{name}' register '{reg['name']}' "
                    f"has unknown access '{reg['access']}' (must be R, W, or RW)"
                )


# ---------------------------------------------------------------------------
# C header generator
# ---------------------------------------------------------------------------

_C_HEADER_BANNER = """\
/* ==========================================================================
 * AUTO-GENERATED — do not edit by hand.
 * Source: {config_path}
 * Regenerate: make gen   (or: python3 scripts/gen_device_code.py)
 * ========================================================================== */
#pragma once

#include <stdint.h>

"""

_C_PLATFORM_BLOCK = """\
/* ── Platform: {machine} ───────────────────────────────────────────────── */
#define NVIC_BASE   {nvic_base}UL   /* ARM Cortex-M NVIC base */

"""

_C_NVIC_REGS = """\
/* NVIC registers (derived from NVIC_BASE = 0xE000E000) */
#define NVIC_ISER0  (NVIC_BASE + 0x100U)   /* IRQ  0-31 enable set      */
#define NVIC_ICPR0  (NVIC_BASE + 0x280U)   /* IRQ  0-31 clear pending   */
#define NVIC_IPR0   (NVIC_BASE + 0x400U)   /* Priority: IRQ  0-3        */
#define NVIC_IPR1   (NVIC_BASE + 0x404U)   /* Priority: IRQ  4-7        */
#define NVIC_IPR2   (NVIC_BASE + 0x408U)   /* Priority: IRQ  8-11       */

"""


def generate_c_header(cfg: dict, config_path: str) -> str:
    lines: list[str] = []

    lines.append(_C_HEADER_BANNER.format(config_path=config_path))

    plat = cfg["platform"]
    lines.append(
        _C_PLATFORM_BLOCK.format(
            machine=plat.get("machine", "unknown"),
            nvic_base=_hex(int(plat["nvic_base"])),
        )
    )
    lines.append(_C_NVIC_REGS)

    for dev in cfg["devices"]:
        prefix     = _upper(dev["name"])
        base       = int(dev["base_addr"])
        size       = int(dev["size"])
        irq_num    = int(dev["irq_num"])
        irq_delay  = float(dev["irq_delay"])
        rw_port    = int(dev["rw_port"])
        irq_port   = int(dev["irq_port"])
        description = dev.get("description", "")

        sep = "─" * (60 - len(prefix))
        lines.append(
            f"/* ── {prefix} {sep}\n"
            f" * {description}\n"
            f" * base={_hex(base)}  size={_hex(size, 4)}"
            f"  irq_num={irq_num}"
            f"  rw_port={rw_port}  irq_port={irq_port}\n"
            f" * ─────────────────────────────────────────────────────────── */\n"
        )
        lines.append(f"#define {prefix}_BASE          {_hex(base)}UL\n")
        lines.append(f"#define {prefix}_SIZE          {_hex(size, 4)}UL\n")
        lines.append(f"#define {prefix}_IRQ_INTID     {irq_num}U\n")
        lines.append(f"#define {prefix}_IRQ_DELAY_S   {irq_delay}\n")
        lines.append(f"#define {prefix}_RW_PORT       {rw_port}\n")
        lines.append(f"#define {prefix}_IRQ_PORT      {irq_port}\n")
        lines.append("\n/* Registers */\n")

        for reg in dev["registers"]:
            reg_offset = int(reg["offset"])
            reg_name   = _upper(reg["name"])
            access     = reg["access"]
            desc       = reg.get("description", "")
            macro      = f"{prefix}_{reg_name}_REG"
            comment    = f"/* {access:<3} {desc} */"
            lines.append(
                f"#define {macro:<40} ({prefix}_BASE + {_hex(reg_offset, 4)}U)"
                f"  {comment}\n"
            )

        lines.append("\n")

    # ── Memory regions ────────────────────────────────────────────────────
    for mem in cfg.get("memory", []):
        prefix      = _upper(mem["name"])
        base        = int(mem["base_addr"])
        size        = int(mem["size"], 0) if isinstance(mem["size"], str) else int(mem["size"])
        description = mem.get("description", "")
        lines.append(f"/* ── {prefix} memory region: {description} */\n")
        lines.append(f"#define {prefix}_BASE   {_hex(base)}UL\n")
        lines.append(f"#define {prefix}_SIZE   {_hex(size)}UL\n")
        lines.append("\n")

    return "".join(lines)
# ---------------------------------------------------------------------------

_PY_CONSTS_BANNER = """\
# =============================================================================
# AUTO-GENERATED — do not edit by hand.
# Source: {config_path}
# Regenerate: make gen   (or: python3 scripts/gen_device_code.py)
# =============================================================================
# Python constants mirroring the C header mmio_devices.h.
# Import in scripts or tests that need symbolic device constants:
#
#     from device_model.generated.device_consts import CONSOLE_UART_BASE
"""


def generate_python_consts(cfg: dict, config_path: str) -> str:
    lines: list[str] = [_PY_CONSTS_BANNER.format(config_path=config_path)]

    for dev in cfg["devices"]:
        prefix      = _upper(dev["name"])
        base        = int(dev["base_addr"])
        size        = int(dev["size"])
        irq_num     = int(dev["irq_num"])
        irq_delay   = float(dev["irq_delay"])
        rw_port     = int(dev["rw_port"])
        irq_port    = int(dev["irq_port"])
        description = dev.get("description", "")

        sep = "─" * (60 - len(prefix))
        lines.append(f"# ── {prefix} {sep}\n")
        lines.append(f"# {description}\n")
        lines.append(f"{prefix}_BASE         = {_hex(base)}\n")
        lines.append(f"{prefix}_SIZE         = {_hex(size, 4)}\n")
        lines.append(f"{prefix}_IRQ_INTID    = {irq_num}\n")
        lines.append(f"{prefix}_IRQ_DELAY_S  = {irq_delay}\n")
        lines.append(f"{prefix}_RW_PORT      = {rw_port}\n")
        lines.append(f"{prefix}_IRQ_PORT     = {irq_port}\n")
        lines.append("\n# Registers\n")

        for reg in dev["registers"]:
            reg_name = _upper(reg["name"])
            offset   = int(reg["offset"])
            access   = reg["access"]
            desc     = reg.get("description", "")
            macro    = f"{prefix}_{reg_name}_REG"
            lines.append(
                f"{macro:<40} = {_hex(base + offset)}"
                f"  # offset {_hex(offset, 4)}  {access}  {desc}\n"
            )
        lines.append("\n")

    # ── Memory regions ────────────────────────────────────────────────────
    for mem in cfg.get("memory", []):
        prefix      = _upper(mem["name"])
        base        = int(mem["base_addr"])
        size        = int(mem["size"], 0) if isinstance(mem["size"], str) else int(mem["size"])
        description = mem.get("description", "")
        sep = "\u2500" * (60 - len(prefix))
        lines.append(f"# \u2500\u2500 {prefix} memory region {sep}\n")
        lines.append(f"# {description}\n")
        lines.append(f"{prefix}_BASE         = {_hex(base)}\n")
        lines.append(f"{prefix}_SIZE         = {_hex(size)}\n")
        lines.append("\n")

    return "".join(lines)
# ---------------------------------------------------------------------------

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Generate C and Python code from spec/devices.yaml",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=str(repo_root / "spec" / "devices.yaml"),
        help="Path to the YAML device configuration file",
    )
    parser.add_argument(
        "--c-out",
        default=str(repo_root / "build" / "generated" / "mmio_devices.h"),
        help="Output path for the generated C header",
    )
    parser.add_argument(
        "--py-out",
        default=str(repo_root / "device_model" / "generated" / "device_consts.py"),
        help="Output path for the generated Python constants file",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    c_out_path  = Path(args.c_out)
    py_out_path = Path(args.py_out)

    if not config_path.exists():
        sys.exit(f"ERROR: config file not found: {config_path}")

    cfg = _load_config(config_path)

    # Relative path for display inside generated files
    try:
        display_path = config_path.relative_to(repo_root)
    except ValueError:
        display_path = config_path

    # ── Generate C header ──────────────────────────────────────────────────
    c_out_path.parent.mkdir(parents=True, exist_ok=True)
    c_header = generate_c_header(cfg, str(display_path))
    c_out_path.write_text(c_header, encoding="utf-8")
    print(f"[gen] C header  → {c_out_path}")

    # ── Generate Python constants ──────────────────────────────────────────
    py_out_path.parent.mkdir(parents=True, exist_ok=True)
    py_consts = generate_python_consts(cfg, str(display_path))
    py_out_path.write_text(py_consts, encoding="utf-8")
    print(f"[gen] Python consts → {py_out_path}")

    print("[gen] Done.")


if __name__ == "__main__":
    main()
