"""
display_model - RGB565 framebuffer display controller.

The first display model is intentionally functional: firmware programs a
framebuffer in QEMU physical memory, the display reads active pixel bytes as a
bus master, computes a CRC, optionally renders to a host window, and raises a
FRAME_DONE interrupt once per completed frame while enabled.
"""

from __future__ import annotations

import os
import queue
import threading
import zlib
from dataclasses import dataclass
from typing import Optional

from device_model.mmio_base import BusMasterAddressSpace, IRQController, IrqLine, MMIODevice
from device_model.tracer import NULL_DEVICE_TRACER, DeviceTracer, Tracer


@dataclass(frozen=True)
class _LayerConfig:
    fb_base: int
    stride: int
    width: int
    height: int
    fmt: int
    x: int = 0
    y: int = 0

    @property
    def bytes_per_pixel(self) -> int:
        return 2

    @property
    def active_line_bytes(self) -> int:
        return self.width * self.bytes_per_pixel


@dataclass(frozen=True)
class _DisplayConfig:
    layer0: _LayerConfig
    layer1: Optional[_LayerConfig]
    layer1_colorkey_enabled: bool
    layer1_colorkey: int
    h_front: int
    h_sync: int
    h_back: int
    v_front: int
    v_sync: int
    v_back: int
    pixel_clock_hz: int

    @property
    def width(self) -> int:
        return self.layer0.width

    @property
    def height(self) -> int:
        return self.layer0.height

    @property
    def frame_ns(self) -> int:
        htotal = self.width + self.h_front + self.h_sync + self.h_back
        vtotal = self.height + self.v_front + self.v_sync + self.v_back
        if self.pixel_clock_hz == 0 or htotal == 0 or vtotal == 0:
            return 0
        return max(1, (htotal * vtotal * 1_000_000_000) // self.pixel_clock_hz)


class _DisplayWindow:
    """Small optional Tk window for interactive display debugging."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=2)
        self._thread = threading.Thread(target=self._run, daemon=True, name='display-window')
        self._thread.start()

    def submit(self, width: int, height: int, pixels: list[str]) -> None:
        try:
            if self._queue.full():
                self._queue.get_nowait()
            self._queue.put_nowait((width, height, pixels))
        except queue.Full:
            pass

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            print(f'[DISP] Tk window unavailable: {exc}', flush=True)
            return

        try:
            root = tk.Tk()
            root.title('KX6625 Display')
            root.minsize(320, 320)
            label = tk.Label(root, bg='black')
            label.pack()
            state = {'image': None, 'scaled': None, 'size': (0, 0), 'scale': 1}
            print('[DISP] Tk display window opened', flush=True)

            def poll() -> None:
                try:
                    while True:
                        width, height, pixels = self._queue.get_nowait()
                        scale = max(1, min(32, 512 // max(width, height, 1)))
                        if state['size'] != (width, height) or state['scale'] != scale:
                            state['image'] = tk.PhotoImage(width=width, height=height)
                            state['scale'] = scale
                            state['size'] = (width, height)
                        image = state['image']
                        if image is not None:
                            image.put(' '.join(pixels), to=(0, 0, width, height))
                            state['scaled'] = image.zoom(scale, scale)
                            label.configure(image=state['scaled'])
                            root.geometry(f'{width * scale}x{height * scale}')
                except queue.Empty:
                    pass
                root.after(33, poll)

            root.after(0, poll)
            root.mainloop()
        except Exception as exc:
            print(f'[DISP] window disabled: {exc}', flush=True)


class DisplayController(MMIODevice):
    _ID = 0x00
    _VERSION = 0x04
    _CTRL = 0x08
    _STATUS = 0x0C
    _INT_STATUS = 0x10
    _INT_ENABLE = 0x14
    _INT_CLEAR = 0x18
    _ERROR = 0x1C
    _FB_BASE = 0x20
    _FB_STRIDE = 0x24
    _WIDTH = 0x28
    _HEIGHT = 0x2C
    _FORMAT = 0x30
    _BG_COLOR = 0x34
    _H_TIMING = 0x38
    _V_TIMING = 0x3C
    _PIXEL_CLOCK_HZ = 0x40
    _SHADOW_FB_BASE = 0x48
    _SHADOW_CTRL = 0x4C
    _CUR_LINE = 0x50
    _CUR_PIXEL = 0x54
    _FRAME_COUNT = 0x58
    _FRAME_CRC = 0x5C
    _LAST_FB_BASE = 0x60
    _OUTPUT_CTRL = 0x64
    _OUTPUT_INDEX = 0x68
    _LAYER_CTRL = 0x6C
    _L1_FB_BASE = 0x70
    _L1_FB_STRIDE = 0x74
    _L1_X = 0x78
    _L1_Y = 0x7C
    _L1_WIDTH = 0x80
    _L1_HEIGHT = 0x84
    _L1_FORMAT = 0x88
    _L1_COLORKEY = 0x8C
    _LAST_L1_FB_BASE = 0x90
    _REGSIZE = 0x94

    _CTRL_ENABLE = 0x01
    _CTRL_SOFT_RESET = 0x02
    _CTRL_OUTPUT_ENABLE = 0x04

    _STATUS_BUSY = 0x01
    _STATUS_FRAME_DONE = 0x02
    _STATUS_ERROR = 0x04
    _STATUS_ENABLED = 0x08
    _STATUS_ACTIVE_VIDEO = 0x10
    _STATUS_SHADOW_PENDING = 0x20

    _INT_FRAME_DONE = 0x01

    _SHADOW_APPLY = 0x01
    _SHADOW_PENDING = 0x02
    _SHADOW_CANCEL = 0x04

    _OUT_WINDOW_ENABLE = 0x01
    _OUT_TRACE_EVENTS = 0x02

    _LAYER0_ENABLE = 0x01
    _LAYER1_ENABLE = 0x02
    _LAYER1_COLORKEY_ENABLE = 0x100

    _ERR_NONE = 0
    _ERR_BAD_CONFIG = 1
    _ERR_BAD_FORMAT = 2
    _ERR_BAD_FB_ADDR = 3
    _ERR_FABRIC_READ = 4
    _ERR_BUSY_CFG = 5

    def __init__(
        self,
        address_space: BusMasterAddressSpace,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._addrspace = address_space
        self._irq = IrqLine(irq_controller, irq_idx)
        self._tr: DeviceTracer = tracer.context(self.name) if tracer else NULL_DEVICE_TRACER
        self._lock = threading.Lock()
        self._regs = bytearray(self._REGSIZE)
        self._initial = bytearray(self._REGSIZE)
        self._put32(self._initial, self._ID, 0x50534944)
        self._put32(self._initial, self._VERSION, 0x00010000)
        self._put32(self._initial, self._OUTPUT_CTRL, self._OUT_WINDOW_ENABLE | self._OUT_TRACE_EVENTS)
        self._regs[:] = self._initial
        self._enabled = False
        self._next_frame_vtime_ns: Optional[int] = None
        self._window: Optional[_DisplayWindow] = None

    @property
    def name(self) -> str:
        return 'display'

    def read(self, offset: int, size: int, master_id: int = 0) -> bytes:
        with self._lock:
            if offset < 0 or offset + size > self._REGSIZE:
                return b'\x00' * size
            if offset == self._INT_CLEAR:
                return b'\x00' * size
            if offset == self._SHADOW_CTRL:
                value = self._get32(self._SHADOW_CTRL) & self._SHADOW_PENDING
                return value.to_bytes(4, 'little')[:size]
            return bytes(self._regs[offset:offset + size])

    def write(self, offset: int, size: int, data: bytes, master_id: int = 0) -> int:
        value = int.from_bytes(data[:size].ljust(4, b'\x00'), 'little')
        with self._lock:
            if offset < 0 or offset + size > self._REGSIZE:
                return 0
            if offset in (self._ID, self._VERSION, self._STATUS, self._ERROR,
                          self._CUR_LINE, self._CUR_PIXEL, self._FRAME_COUNT,
                          self._FRAME_CRC, self._LAST_FB_BASE, self._OUTPUT_INDEX,
                          self._LAST_L1_FB_BASE):
                return 0

            if offset == self._CTRL:
                if value & self._CTRL_SOFT_RESET:
                    self._reset_locked()
                    return 0
                self._put32(self._regs, self._CTRL, value & (self._CTRL_ENABLE | self._CTRL_OUTPUT_ENABLE))
                if value & self._CTRL_ENABLE:
                    self._enable_locked()
                else:
                    self._disable_locked()
                return 0

            if offset == self._INT_STATUS:
                self._clear_int_locked(value)
                return 0

            if offset == self._INT_CLEAR:
                self._clear_int_locked(value)
                return 0

            if offset == self._SHADOW_CTRL:
                if value & self._SHADOW_CANCEL:
                    self._clear32_bits(self._SHADOW_CTRL, self._SHADOW_PENDING)
                    self._clear32_bits(self._STATUS, self._STATUS_SHADOW_PENDING)
                if value & self._SHADOW_APPLY:
                    self._set32_bits(self._SHADOW_CTRL, self._SHADOW_PENDING)
                    self._set32_bits(self._STATUS, self._STATUS_SHADOW_PENDING)
                return 0

            if self._enabled and offset in (
                self._FB_BASE, self._FB_STRIDE, self._WIDTH, self._HEIGHT,
                self._FORMAT, self._H_TIMING, self._V_TIMING, self._PIXEL_CLOCK_HZ,
                self._LAYER_CTRL, self._L1_FB_BASE, self._L1_FB_STRIDE,
                self._L1_X, self._L1_Y, self._L1_WIDTH, self._L1_HEIGHT,
                self._L1_FORMAT, self._L1_COLORKEY,
            ):
                self._set_error_locked(self._ERR_BUSY_CFG)
                return 0

            self._regs[offset:offset + size] = data[:size]
        return 0

    def on_reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def on_tick(self, vtime_ns: int) -> int:
        self._tr.tick(vtime_ns)
        should_scan = False
        with self._lock:
            if self._enabled and self._next_frame_vtime_ns is not None and vtime_ns >= self._next_frame_vtime_ns:
                should_scan = True
        if should_scan:
            self._complete_frame(vtime_ns)
        return 0

    def _complete_frame(self, vtime_ns: int) -> None:
        with self._lock:
            config = self._config_locked()
            if config is None:
                self._disable_locked()
                return
            output_ctrl = self._get32(self._OUTPUT_CTRL)
            ctrl = self._get32(self._CTRL)

        frame = self._scanout_frame(config)
        if frame is None:
            return

        frame_crc = zlib.crc32(frame) & 0xFFFFFFFF
        pixels = self._rgb565_to_tk_rows(bytes(frame), config.width, config.height)

        with self._lock:
            self._put32(self._regs, self._CUR_LINE, 0)
            self._put32(self._regs, self._CUR_PIXEL, 0)
            self._put32(self._regs, self._FRAME_CRC, frame_crc)
            self._put32(self._regs, self._LAST_FB_BASE, config.layer0.fb_base)
            self._put32(self._regs, self._LAST_L1_FB_BASE, config.layer1.fb_base if config.layer1 else 0)
            frame_count = (self._get32(self._FRAME_COUNT) + 1) & 0xFFFFFFFF
            self._put32(self._regs, self._FRAME_COUNT, frame_count)
            self._put32(self._regs, self._OUTPUT_INDEX, frame_count)
            self._set32_bits(self._STATUS, self._STATUS_FRAME_DONE)
            self._set32_bits(self._INT_STATUS, self._INT_FRAME_DONE)
            if self._get32(self._SHADOW_CTRL) & self._SHADOW_PENDING:
                shadow_base = self._get32(self._SHADOW_FB_BASE)
                if shadow_base != 0:
                    self._put32(self._regs, self._FB_BASE, shadow_base)
                self._clear32_bits(self._SHADOW_CTRL, self._SHADOW_PENDING)
                self._clear32_bits(self._STATUS, self._STATUS_SHADOW_PENDING)
            if self._enabled:
                self._next_frame_vtime_ns = vtime_ns + config.frame_ns
            if self._get32(self._INT_ENABLE) & self._INT_FRAME_DONE:
                self._irq.pulse()

        if (ctrl & self._CTRL_OUTPUT_ENABLE) and (output_ctrl & self._OUT_WINDOW_ENABLE):
            self._render(config.width, config.height, pixels)
        if output_ctrl & self._OUT_TRACE_EVENTS:
            self._tr.emit('FRAME_DONE', frame=frame_count, crc32=hex(frame_crc),
                          fb_base=hex(config.layer0.fb_base),
                          l1_fb_base=hex(config.layer1.fb_base) if config.layer1 else '0x0')
        layer_msg = f' l1=0x{config.layer1.fb_base:08x}' if config.layer1 else ''
        print(f'[DISP] frame {frame_count} done crc=0x{frame_crc:08x} fb=0x{config.layer0.fb_base:08x}{layer_msg}', flush=True)

    def _enable_locked(self) -> None:
        config = self._config_locked()
        if config is None:
            return
        self._enabled = True
        self._next_frame_vtime_ns = 0
        self._clear32_bits(self._STATUS, self._STATUS_FRAME_DONE | self._STATUS_ERROR)
        self._set32_bits(self._STATUS, self._STATUS_BUSY | self._STATUS_ENABLED)
        self._put32(self._regs, self._ERROR, self._ERR_NONE)
        self._tr.emit('ENABLE', width=config.width, height=config.height,
                  fb_base=hex(config.layer0.fb_base),
                  l1_fb_base=hex(config.layer1.fb_base) if config.layer1 else '0x0')

    def _disable_locked(self) -> None:
        self._enabled = False
        self._next_frame_vtime_ns = None
        self._clear32_bits(self._STATUS, self._STATUS_BUSY | self._STATUS_ENABLED | self._STATUS_ACTIVE_VIDEO)
        self._irq.deassert()
        self._tr.emit('DISABLE')

    def _config_locked(self) -> Optional[_DisplayConfig]:
        fmt = self._get32(self._FORMAT)
        fb_base = self._get32(self._FB_BASE)
        stride = self._get32(self._FB_STRIDE)
        width = self._get32(self._WIDTH)
        height = self._get32(self._HEIGHT)
        pixel_clock_hz = self._get32(self._PIXEL_CLOCK_HZ)
        h_timing = self._get32(self._H_TIMING)
        v_timing = self._get32(self._V_TIMING)
        layer_ctrl = self._get32(self._LAYER_CTRL)
        layer0_enabled = (layer_ctrl == 0) or bool(layer_ctrl & self._LAYER0_ENABLE)
        layer1_enabled = bool(layer_ctrl & self._LAYER1_ENABLE)
        layer0 = _LayerConfig(fb_base=fb_base, stride=stride, width=width, height=height, fmt=fmt)

        if not layer0_enabled:
            self._set_error_locked(self._ERR_BAD_CONFIG)
            return None
        if not self._validate_layer_locked(layer0, output_width=width, output_height=height, require_full_output=True):
            return None

        layer1: Optional[_LayerConfig] = None
        if layer1_enabled:
            layer1 = _LayerConfig(
                fb_base=self._get32(self._L1_FB_BASE),
                stride=self._get32(self._L1_FB_STRIDE),
                width=self._get32(self._L1_WIDTH),
                height=self._get32(self._L1_HEIGHT),
                fmt=self._get32(self._L1_FORMAT),
                x=self._get32(self._L1_X),
                y=self._get32(self._L1_Y),
            )
            if not self._validate_layer_locked(layer1, output_width=width, output_height=height, require_full_output=False):
                return None

        config = _DisplayConfig(
            layer0=layer0,
            layer1=layer1,
            layer1_colorkey_enabled=bool(layer_ctrl & self._LAYER1_COLORKEY_ENABLE),
            layer1_colorkey=self._get32(self._L1_COLORKEY) & 0xFFFF,
            h_front=h_timing & 0x3FF,
            h_sync=(h_timing >> 10) & 0x3FF,
            h_back=(h_timing >> 20) & 0x3FF,
            v_front=v_timing & 0x3FF,
            v_sync=(v_timing >> 10) & 0x3FF,
            v_back=(v_timing >> 20) & 0x3FF,
            pixel_clock_hz=pixel_clock_hz,
        )
        if config.frame_ns == 0:
            self._set_error_locked(self._ERR_BAD_CONFIG)
            return None
        return config

    def _validate_layer_locked(self, layer: _LayerConfig, output_width: int, output_height: int, require_full_output: bool) -> bool:
        if layer.fmt != 0:
            self._set_error_locked(self._ERR_BAD_FORMAT)
            return False
        if layer.fb_base == 0 or (layer.fb_base & 0x3):
            self._set_error_locked(self._ERR_BAD_FB_ADDR)
            return False
        if layer.width == 0 or layer.height == 0 or layer.stride < layer.active_line_bytes or (layer.stride & 0x3):
            self._set_error_locked(self._ERR_BAD_CONFIG)
            return False
        if require_full_output:
            if layer.x != 0 or layer.y != 0 or layer.width != output_width or layer.height != output_height:
                self._set_error_locked(self._ERR_BAD_CONFIG)
                return False
        elif layer.x >= output_width or layer.y >= output_height or layer.x + layer.width > output_width or layer.y + layer.height > output_height:
            self._set_error_locked(self._ERR_BAD_CONFIG)
            return False
        return True

    def _read_layer_line(self, layer: _LayerConfig, line: int, name: str) -> Optional[bytes]:
        addr = layer.fb_base + line * layer.stride
        data = self._addrspace.read(addr, layer.active_line_bytes)
        if data is None or len(data) != layer.active_line_bytes:
            with self._lock:
                self._set_error_locked(self._ERR_FABRIC_READ)
                self._disable_locked()
            self._tr.emit('FABRIC_READ_ERROR', layer=name, line=line, addr=hex(addr))
            return None
        return data

    def _scanout_frame(self, config: _DisplayConfig) -> Optional[bytearray]:
        frame = bytearray()
        for output_line in range(config.height):
            line = self._read_layer_line(config.layer0, output_line, 'layer0')
            if line is None:
                return None
            composed_line = bytearray(line)
            if config.layer1 is not None and config.layer1.y <= output_line < config.layer1.y + config.layer1.height:
                layer1_line_index = output_line - config.layer1.y
                layer1_line = self._read_layer_line(config.layer1, layer1_line_index, 'layer1')
                if layer1_line is None:
                    return None
                self._compose_layer1_line(composed_line, config, layer1_line)
            frame.extend(composed_line)
        return frame

    @staticmethod
    def _compose_layer1_line(output_line: bytearray, config: _DisplayConfig, layer1_line: bytes) -> None:
        layer1 = config.layer1
        if layer1 is None:
            return
        dst_base = layer1.x * 2
        for x in range(layer1.width):
            src = x * 2
            pixel = layer1_line[src] | (layer1_line[src + 1] << 8)
            if config.layer1_colorkey_enabled and pixel == config.layer1_colorkey:
                continue
            dst = dst_base + src
            output_line[dst] = layer1_line[src]
            output_line[dst + 1] = layer1_line[src + 1]

    def _render(self, width: int, height: int, pixels: list[str]) -> None:
        if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
            print('[DISP] no GUI display environment; window rendering skipped', flush=True)
            return
        if self._window is None:
            print(f'[DISP] opening display window for {width}x{height} frame', flush=True)
            self._window = _DisplayWindow()
        self._window.submit(width, height, pixels)

    @staticmethod
    def _rgb565_to_tk_rows(frame: bytes, width: int, height: int) -> list[str]:
        rows: list[str] = []
        index = 0
        for _y in range(height):
            colors: list[str] = []
            for _x in range(width):
                value = frame[index] | (frame[index + 1] << 8)
                index += 2
                red = ((value >> 11) & 0x1F) * 255 // 31
                green = ((value >> 5) & 0x3F) * 255 // 63
                blue = (value & 0x1F) * 255 // 31
                colors.append(f'#{red:02x}{green:02x}{blue:02x}')
            rows.append('{' + ' '.join(colors) + '}')
        return rows

    def _clear_int_locked(self, value: int) -> None:
        if value & self._INT_FRAME_DONE:
            self._clear32_bits(self._INT_STATUS, self._INT_FRAME_DONE)
            self._clear32_bits(self._STATUS, self._STATUS_FRAME_DONE)
            self._irq.deassert()

    def _set_error_locked(self, error: int) -> None:
        self._put32(self._regs, self._ERROR, error)
        if error != self._ERR_NONE:
            self._set32_bits(self._STATUS, self._STATUS_ERROR)
            self._tr.emit('ERROR', code=error)

    def _reset_locked(self) -> None:
        self._regs[:] = self._initial
        self._enabled = False
        self._next_frame_vtime_ns = None
        self._irq.deassert()
        self._tr.emit('RESET')

    def _get32(self, offset: int) -> int:
        return int.from_bytes(self._regs[offset:offset + 4], 'little')

    @staticmethod
    def _put32(buf: bytearray, offset: int, value: int) -> None:
        buf[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, 'little')

    def _set32_bits(self, offset: int, mask: int) -> None:
        self._put32(self._regs, offset, self._get32(offset) | mask)

    def _clear32_bits(self, offset: int, mask: int) -> None:
        self._put32(self._regs, offset, self._get32(offset) & ~mask)