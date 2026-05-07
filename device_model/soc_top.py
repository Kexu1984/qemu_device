"""
soc_top — Python Device Domain topology and wiring.

Encapsulates the Python Device Domain from the architecture diagram: transport
servers, a peripheral transaction bus, a bus-master address space, abstract
device-model instances, and reset/tick wiring. Native QEMU blocks such as
SYSCTRL and CRU are intentionally outside this domain.

Each peripheral is described by a typed config dataclass; ``PythonDeviceDomain``
wires them together and exposes a single ``start()``/``stop()`` interface.
``SoCTop`` remains as a backward-compatible alias.

Architecture
------------
::

    PythonDeviceDomain
    ├── PeripheralBus                  — peripheral transaction bus
    │   └── MMIODevice instances       — UART / DMA / timer / WDT / ...
    ├── BusMasterAddressSpace          — DMA/HSM/flash memory transaction path
    ├── Transport servers              — RW / IRQ / tick / mem / reset TCP
    └── Reset/tick managers            — SystemResetManager / tick broadcast

Defining a custom SoC topology::

    from device_model.soc_top import PythonDeviceDomain, UartCfg, TimerCfg, DmaCfg
    from device_model.soc_top import DmaClientDemoCfg, CrcCfg, WdtCfg

    domain = PythonDeviceDomain(
        uarts=[
            UartCfg('uart0', base_addr=0x40004000, rw_port=7890, irq_port=7891,
                    nvic_irq=0, term_port=7904),
            UartCfg('uart1', base_addr=0x4000A000, rw_port=7910, irq_port=7911,
                    nvic_irq=5, term_port=7912),
        ],
        timers=[
            TimerCfg('timer0', base_addr=0x40006000, rw_port=7894, irq_port=7895, nvic_irq=2),
            TimerCfg('timer1', base_addr=0x4000B000, rw_port=7914, irq_port=7915, nvic_irq=6),
            TimerCfg('timer2', base_addr=0x4000C000, rw_port=7918, irq_port=7919, nvic_irq=7),
        ],
        dma=DmaCfg(base_addr=0x40005000, rw_port=7892, irq_port=7893,
                   nvic_irq=1, mem_port=7897, tick_port=7905),
        dma_client_demo=DmaClientDemoCfg(base_addr=0x40007000, rw_port=7898,
                                         irq_port=7899, nvic_irq=3),
        crc=CrcCfg(base_addr=0x40008000, rw_port=7900),
        wdt=WdtCfg(base_addr=0x40009000, rw_port=7901, irq_port=7902,
                   nvic_irq=4, rst_port=7903)
        tick_port=7896,
    )
    domain.start()

NOTE — circular-import avoidance
---------------------------------
This module imports the transport-layer classes (``PeripheralBus``, ``RWServer``, …)
from ``mmio_device_server``.  To avoid a circular import, ``mmio_device_server``
must import ``kx6625_default`` inside ``main()`` (function-level), not at the top of the
file.  By the time ``main()`` runs the module is already in ``sys.modules``.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Ensure the project root is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Transport layer + bus — imported from mmio_device_server.
# See NOTE in module docstring about circular-import safety.
from device_model.mmio_device_server import (   # noqa: E402
    IRQServer,
    MemServer,
    PeripheralBus,
    RstServer,
    RWServer,
    TickServer,
)

from device_model.mmio_base import (            # noqa: E402
    BusMasterAddressSpace,
    IRQController,
    MemChannel,
)

from device_model.cru_device import (           # noqa: E402
    CruNotifyServer,
    RstController,
    SystemResetManager,
)

from device_model.uart_model import (           # noqa: E402
    ConsoleUartDevice,
    UartChannel,
)
from device_model.timer_model       import TimerDevice          # noqa: E402
from device_model.dma_controller    import DmaController        # noqa: E402
from device_model.dma_client_demo   import DmaClientDemoDevice  # noqa: E402
from device_model.crc_device        import CrcDevice            # noqa: E402
from device_model.wdt_model         import WdtDevice            # noqa: E402
from device_model.hsm_model         import HsmDevice            # noqa: E402
from device_model.otp_model         import OtpControllerDevice   # noqa: E402
from device_model.flash_controller  import FlashControllerDevice # noqa: E402
from device_model.tracer            import Tracer               # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Per-device config dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UartCfg:
    """Configuration for one ``ConsoleUartDevice`` instance.

    Attributes
    ----------
    name       : Instance identifier used in log messages and traces.
    base_addr  : Physical MMIO base address (must match QEMU addr= property).
    rw_port    : TCP port for the MMIO R/W chardev channel (QEMU → Python).
    irq_port   : TCP port for the IRQ injection channel   (Python → QEMU).
    irq_idx    : NVIC external IRQ line number (maps to QEMU ``irq-num=N``).
                 Metadata only — used for documentation and QEMU cmdline
                 generation.  The Python IRQ output index within each
                 mmio-sockdev is always 0 (each device has one IRQ line).
    term_port  : TCP port for the external terminal server (nc/uart_console.py).
    irq_delay  : Seconds after the IRQ channel connects before the TX-ready IRQ fires.
    size       : MMIO region size in bytes.
    """
    name:      str
    base_addr: int
    rw_port:   int
    irq_port:  int
    nvic_irq:  int
    term_port: int
    irq_delay: float = 2.0
    size:      int   = 0x1000


@dataclass
class TimerCfg:
    """Configuration for one ``TimerDevice`` instance.

    All timer instances share the PythonDeviceDomain-level periodic tick broadcast
    (``tick_port`` on ``PythonDeviceDomain.__init__``); no per-timer tick port is needed.

    Attributes
    ----------
    name       : Instance identifier used in log messages and traces.
    base_addr  : Physical MMIO base address.
    rw_port    : TCP port for the MMIO R/W chardev channel.
    irq_port   : TCP port for the IRQ injection channel.
    irq_idx    : NVIC external IRQ line number (maps to QEMU ``irq-num=N``).
                 The Python IRQ output index is always 0.
    size       : MMIO region size in bytes.
    """
    name:      str
    base_addr: int
    rw_port:   int
    irq_port:  int
    nvic_irq:  int
    size:      int = 0x1000


@dataclass
class DmaCfg:
    """Configuration for the ``DmaController`` (single instance per SoC).

    Attributes
    ----------
    base_addr    : Physical MMIO base address.
    rw_port      : TCP port for the MMIO R/W chardev channel.
    irq_port     : TCP port for the IRQ injection channel.
    irq_idx      : NVIC external IRQ line number (maps to QEMU ``irq-num=N``).
                   The Python IRQ output index is always 0.
    mem_port     : TCP port for the bus-master memory channel (Python → QEMU RAM).
    tick_port    : TCP port for the DES one-shot tick channel (QEMU → Python).
    num_channels : Number of DMA channels to instantiate.
    size         : MMIO region size in bytes.
    """
    base_addr:    int
    rw_port:      int
    irq_port:     int
    nvic_irq:     int
    mem_port:     int
    tick_port:    int
    num_channels: int = 2
    size:         int = 0x1000


@dataclass
class DmaClientDemoCfg:
    """Configuration for the ``DmaClientDemoDevice`` (single instance per SoC).

    Requires a ``DmaCfg`` to be present in the same ``PythonDeviceDomain``.

    Attributes
    ----------
    base_addr   : Physical MMIO base address.
    rw_port     : TCP port for the MMIO R/W chardev channel.
    irq_port    : TCP port for the IRQ injection channel.
    irq_idx     : NVIC external IRQ line number (maps to QEMU ``irq-num=N``).
                  The Python IRQ output index is always 0.
    dma_channel : Which ``DmaController`` channel to use (0-based).
    size        : MMIO region size in bytes.
    """
    base_addr:   int
    rw_port:     int
    irq_port:    int
    nvic_irq:    int
    dma_channel: int = 1
    size:        int = 0x1000


@dataclass
class CrcCfg:
    """Configuration for the ``CrcDevice`` (no IRQ, no tick).

    Attributes
    ----------
    base_addr : Physical MMIO base address.
    rw_port   : TCP port for the MMIO R/W chardev channel.
    size      : MMIO region size in bytes.
    """
    base_addr: int
    rw_port:   int
    size:      int = 0x1000


@dataclass
class WdtCfg:
    """Configuration for the ``WdtDevice`` (IRQ + system-reset channel).

    Attributes
    ----------
    base_addr : Physical MMIO base address.
    rw_port   : TCP port for the MMIO R/W chardev channel.
    irq_port  : TCP port for the IRQ injection channel.
    irq_idx   : NVIC external IRQ line number (maps to QEMU ``irq-num=N``).
                The Python IRQ output index is always 0.
    rst_port  : TCP port for the system-reset channel (Python → QEMU rst-chardev).
    size      : MMIO region size in bytes.
    """
    base_addr: int
    rw_port:   int
    irq_port:  int
    nvic_irq:  int
    rst_port:  int
    size:      int = 0x1000


@dataclass
class HsmCfg:
    """Configuration for the ``HsmDevice`` (IRQ, DMA-style memory access).

    Requires a ``DmaCfg`` to be present so it can reuse the SoC physical
    address-space/MemChannel path for bus-master reads and writes.
    """
    base_addr: int
    rw_port:   int
    irq_port:  int
    nvic_irq:  int
    otp_file:  str = 'build/hsm_otp.json'
    size:      int = 0x1000


@dataclass
class OtpCfg:
    """Configuration for the ``OtpControllerDevice``.

    OTP persists its rows in a host-side HEX file and exposes HSM key slots
    through a direct provider API used by ``HsmDevice``.
    """
    base_addr:    int
    rw_port:      int
    irq_port:     int
    nvic_irq:     int
    storage_file: str = 'build/otp.hex'
    size:         int = 0x1000


@dataclass
class FlashCtrlCfg:
    """Configuration for the FLASH controller and DFLASH memory window."""
    base_addr:     int
    rw_port:       int
    irq_port:      int
    nvic_irq:      int
    mem_port:      int
    ahb_base_addr: int
    ahb_size:      int
    ahb_rw_port:   int
    storage_file:  str = 'build/dflash.hex'
    size:          int = 0x1000


# ─────────────────────────────────────────────────────────────────────────────
# PythonDeviceDomain
# ─────────────────────────────────────────────────────────────────────────────

class PythonDeviceDomain:
    """Python Device Domain: device models plus transport wiring.

    This class is the code-level counterpart of the "Python Device Domain" in
    the architecture diagram. Individual devices are intentionally treated as
    instances of the ``MMIODevice`` abstraction; the important architectural
    boundaries here are the peripheral bus, bus-master address space, transport
    servers, tick delivery, and reset path.

    Parameters
    ----------
    uarts            : List of UART instance configs (0 or more).
    timers           : List of Timer instance configs (0 or more).
    dma              : DMA controller config (``None`` = omit DMA subsystem).
    dma_client_demo  : DMA client demo config (``None`` = omit; requires ``dma``).
    crc              : CRC device config (``None`` = omit).
    wdt              : Watchdog config (``None`` = omit).
    tick_port        : TCP port for the shared periodic tick server that
                       broadcasts ``bus.tick_all()`` to every registered device.
                       All ``TimerDevice`` instances are driven by this broadcast.
    tracer           : Optional ``Tracer`` instance for event recording.
                       ``PythonDeviceDomain.stop()`` will call ``tracer.close()``.

    Typical usage::

        domain = PythonDeviceDomain(uarts=[...], timers=[...], dma=..., crc=..., wdt=...)
        domain.start()          # blocks until KeyboardInterrupt

    Scripted / test usage::

        domain = PythonDeviceDomain(...)
        domain.start_background()
        # ... interact with devices via TCP / direct Python calls ...
        domain.stop()
    """

    def __init__(
        self,
        uarts:           List[UartCfg]              = (),
        timers:          List[TimerCfg]             = (),
        dma:             Optional[DmaCfg]           = None,
        dma_client_demo: Optional[DmaClientDemoCfg] = None,
        crc:             Optional[CrcCfg]           = None,
        wdt:             Optional[WdtCfg]           = None,
        otp:             Optional[OtpCfg]           = None,
        hsm:             Optional[HsmCfg]           = None,
        flash_ctrl:      Optional[FlashCtrlCfg]     = None,
        tick_port:       int                        = 7896,
        cru_notify_port: Optional[int]              = None,
        tracer:          Optional[Tracer]           = None,
    ) -> None:
        if dma_client_demo is not None and dma is None:
            raise ValueError('DmaClientDemoCfg requires a DmaCfg')
        if hsm is not None and dma is None:
            raise ValueError('HsmCfg requires a DmaCfg')

        self._tracer   = tracer
        self._servers: list = []    # transport server objects (have .stop())
        self._channels: list = []   # UartChannel objects (have .stop())
        self._stop_evt = threading.Event()

        bus = PeripheralBus()
        self._bus = bus

        # ── 1. Collect MMIO regions for BusMasterAddressSpace ─────────────
        #    BusMasterAddressSpace is only needed when bus-mastering is active.
        mmio_regions = (
            [(u.base_addr, u.size) for u in uarts]
            + ([(dma.base_addr, dma.size)] if dma else [])
            + [(t.base_addr, t.size) for t in timers]
            + ([(dma_client_demo.base_addr, dma_client_demo.size)] if dma_client_demo else [])
            + ([(crc.base_addr, crc.size)] if crc else [])
            + ([(wdt.base_addr, wdt.size)] if wdt else [])
            + ([(otp.base_addr, otp.size)] if otp else [])
            + ([(hsm.base_addr, hsm.size)] if hsm else [])
            + ([(flash_ctrl.base_addr, flash_ctrl.size),
                (flash_ctrl.ahb_base_addr, flash_ctrl.ahb_size)] if flash_ctrl else [])
        )

        # ── 2. DMA subsystem ──────────────────────────────────────────────
        dma_ctrl: Optional[DmaController] = None
        if dma is not None:
            mem_channel   = MemChannel()
            addr_space    = BusMasterAddressSpace(
                mem_channel  = mem_channel,
                mmio_bus     = bus,
                mmio_regions = mmio_regions,
            )
            dma_irq_ctrl  = IRQController()
            dma_ctrl      = DmaController(
                num_channels   = dma.num_channels,
                address_space  = addr_space,
                irq_controller = dma_irq_ctrl,
                irq_idx        = 0,   # device IRQ output index (always 0)
                tracer         = tracer,
            )
            bus.register(dma.base_addr, dma.size, dma_ctrl)
            self._add_server(IRQServer(port=dma.irq_port, irq_controller=dma_irq_ctrl))
            self._add_server(MemServer(port=dma.mem_port, mem_channel=mem_channel))
            self._add_server(RWServer(port=dma.rw_port, bus=bus, base_addr=dma.base_addr))
            # DES one-shot tick fires at exactly arm_vtime + transfer_ns.
            self._add_server(TickServer(port=dma.tick_port, tick_fn=dma_ctrl.on_tick))

        # ── 3. UARTs ──────────────────────────────────────────────────────
        for u in uarts:
            uart_ch = UartChannel(port=u.term_port)
            uart_ch.start()
            self._channels.append(uart_ch)

            uart_irq_ctrl = IRQController()
            dev = ConsoleUartDevice(
                name           = u.name,
                irq_controller = uart_irq_ctrl,
                irq_idx        = 0,   # device IRQ output index (always 0)
                irq_delay      = u.irq_delay,
                uart_channel   = uart_ch,
                tracer         = tracer,
            )
            bus.register(u.base_addr, u.size, dev)
            self._add_server(IRQServer(port=u.irq_port, irq_controller=uart_irq_ctrl))
            self._add_server(RWServer(port=u.rw_port, bus=bus, base_addr=u.base_addr))

        # ── 4. Timers ─────────────────────────────────────────────────────
        #    All timer instances receive on_tick() via the shared tick broadcast
        #    (TickServer → bus.tick_all()) registered at the end of this section.
        for t in timers:
            timer_irq_ctrl = IRQController()
            dev = TimerDevice(
                name           = t.name,
                irq_controller = timer_irq_ctrl,
                irq_idx        = 0,   # device IRQ output index (always 0)
                tracer         = tracer,
            )
            bus.register(t.base_addr, t.size, dev)
            self._add_server(IRQServer(port=t.irq_port, irq_controller=timer_irq_ctrl))
            self._add_server(RWServer(port=t.rw_port, bus=bus, base_addr=t.base_addr))

        # Shared periodic tick — drives all registered devices (timers + DMA).
        self._add_server(TickServer(port=tick_port, tick_fn=bus.tick_all))

        # ── 5. DMA client demo ────────────────────────────────────────────
        if dma_client_demo is not None and dma_ctrl is not None:
            demo_irq_ctrl = IRQController()
            dev = DmaClientDemoDevice(
                dma_handle     = dma_ctrl.get_handle(dma_client_demo.dma_channel),
                irq_controller = demo_irq_ctrl,
                irq_idx        = 0,   # device IRQ output index (always 0)
                tracer         = tracer,
            )
            bus.register(dma_client_demo.base_addr, dma_client_demo.size, dev)
            self._add_server(IRQServer(port=dma_client_demo.irq_port,
                                       irq_controller=demo_irq_ctrl))
            self._add_server(RWServer(port=dma_client_demo.rw_port, bus=bus,
                                      base_addr=dma_client_demo.base_addr))

        # ── 6. CRC ────────────────────────────────────────────────────────
        if crc is not None:
            bus.register(crc.base_addr, crc.size, CrcDevice(tracer=tracer))
            self._add_server(RWServer(port=crc.rw_port, bus=bus, base_addr=crc.base_addr))

        # ── 7. WDT ────────────────────────────────────────────────────────
        if wdt is not None:
            wdt_irq_ctrl  = IRQController()
            wdt_rst_ctrl  = RstController()
            sys_reset_mgr = SystemResetManager(bus=bus, rst_ctrl=wdt_rst_ctrl)
            wdt_dev = WdtDevice(
                irq_controller = wdt_irq_ctrl,
                irq_idx        = 0,   # device IRQ output index (always 0)
                reset_callback = sys_reset_mgr.wdt_reset,
                tracer         = tracer,
            )
            bus.register(wdt.base_addr, wdt.size, wdt_dev)
            self._add_server(IRQServer(port=wdt.irq_port, irq_controller=wdt_irq_ctrl))
            self._add_server(RstServer(port=wdt.rst_port, rst_controller=wdt_rst_ctrl))
            self._add_server(RWServer(port=wdt.rw_port, bus=bus, base_addr=wdt.base_addr))

        # ── 8. OTP ────────────────────────────────────────────────────────
        otp_dev: Optional[OtpControllerDevice] = None
        if otp is not None:
            otp_irq_ctrl = IRQController()
            otp_dev = OtpControllerDevice(
                storage_file   = otp.storage_file,
                irq_controller = otp_irq_ctrl,
                irq_idx        = 0,
                tracer         = tracer,
            )
            bus.register(otp.base_addr, otp.size, otp_dev)
            self._add_server(IRQServer(port=otp.irq_port, irq_controller=otp_irq_ctrl))
            self._add_server(RWServer(port=otp.rw_port, bus=bus, base_addr=otp.base_addr))

        # ── 9. HSM ────────────────────────────────────────────────────────
        if hsm is not None and dma_ctrl is not None:
            hsm_irq_ctrl = IRQController()
            hsm_dev = HsmDevice(
                address_space  = addr_space,
                irq_controller = hsm_irq_ctrl,
                irq_idx        = 0,   # device IRQ output index (always 0)
                otp_file       = hsm.otp_file,
                otp_provider   = otp_dev.read_key if otp_dev is not None else None,
                tracer         = tracer,
            )
            bus.register(hsm.base_addr, hsm.size, hsm_dev)
            self._add_server(IRQServer(port=hsm.irq_port, irq_controller=hsm_irq_ctrl))
            self._add_server(RWServer(port=hsm.rw_port, bus=bus, base_addr=hsm.base_addr))

        # ── 10. FLASH controller + DFLASH memory window ──────────────────
        if flash_ctrl is not None:
            flash_irq_ctrl = IRQController()
            flash_mem_channel = MemChannel()
            flash_addr_space = BusMasterAddressSpace(
                mem_channel  = flash_mem_channel,
                mmio_bus     = bus,
                mmio_regions = mmio_regions,
            )
            flash_dev = FlashControllerDevice(
                address_space  = flash_addr_space,
                storage_file   = flash_ctrl.storage_file,
                data_base      = flash_ctrl.ahb_base_addr,
                data_size      = flash_ctrl.ahb_size,
                irq_controller = flash_irq_ctrl,
                irq_idx        = 0,
                tracer         = tracer,
            )
            bus.register(flash_ctrl.base_addr, flash_ctrl.size, flash_dev)
            bus.register(flash_ctrl.ahb_base_addr, flash_ctrl.ahb_size, flash_dev.window)
            self._add_server(IRQServer(port=flash_ctrl.irq_port, irq_controller=flash_irq_ctrl))
            self._add_server(MemServer(port=flash_ctrl.mem_port, mem_channel=flash_mem_channel))
            self._add_server(RWServer(port=flash_ctrl.rw_port, bus=bus, base_addr=flash_ctrl.base_addr))
            self._add_server(RWServer(port=flash_ctrl.ahb_rw_port, bus=bus,
                                      base_addr=flash_ctrl.ahb_base_addr))

        # ── CRU notify server (optional) ──────────────────────────────────
        # Maps CRU device indices (matching kx6625_cru_devices[] in kx6625.c)
        # to Python device instances so on_device_reset() can be dispatched.
        if cru_notify_port is not None:
            cru_dev_map: dict = {}
            _cru_base_to_idx = {
                0x40004000: 0,   # console_uart
                0x40005000: 1,   # dma
                0x40006000: 2,   # timer0
                0x40007000: 3,   # dma_demo
                0x40008000: 4,   # crc
                0x40009000: 5,   # wdt
                0x4000B000: 6,   # sv_timer (no Python model; idx still reserved)
                0x4000C000: 7,   # hsm
                0x4000D000: 8,   # otp
            }
            for base, _size, device in bus._entries:
                idx = _cru_base_to_idx.get(base)
                if idx is not None:
                    cru_dev_map[idx] = device
            self._add_server(CruNotifyServer(port=cru_notify_port, device_map=cru_dev_map))

    # ── Internal helpers ──────────────────────────────────────────────────

    def _add_server(self, srv) -> None:
        self._servers.append(srv)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def bus(self) -> PeripheralBus:
        """The shared ``PeripheralBus`` (read-only; useful for testing)."""
        return self._bus

    def start_background(self) -> None:
        """Start all transport servers as daemon threads (non-blocking).

        Useful for test harnesses that want to drive the model programmatically.
        Call :meth:`stop` when done.
        """
        for srv in self._servers:
            threading.Thread(target=srv.start, daemon=True).start()

    def start(self) -> None:
        """Start all transport servers and block until ``KeyboardInterrupt``.

        All servers run as daemon threads; the main thread blocks on a
        ``threading.Event`` so it remains alive until the user interrupts.
        ``stop()`` is called automatically in the ``finally`` clause.
        """
        self.start_background()
        try:
            self._stop_evt.wait()   # block until stop() or KeyboardInterrupt
        except KeyboardInterrupt:
            print('\n[SoC] Shutting down...')
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop all transport servers, UART channels, and close the tracer."""
        self._stop_evt.set()
        for srv in reversed(self._servers):
            try:
                srv.stop()
            except Exception:
                pass
        for ch in self._channels:
            try:
                ch.stop()
            except Exception:
                pass
        if self._tracer is not None:
            try:
                self._tracer.close()
            except Exception:
                pass
            self._tracer = None


# ─────────────────────────────────────────────────────────────────────────────
# KX6625 default configuration
# ─────────────────────────────────────────────────────────────────────────────

def kx6625_default(
    uart_rw_port:   int   = 7890,
    uart_irq_port:  int   = 7891,
    uart_irq_delay: float = 2.0,
    uart_term_port: int   = 7904,
    tracer: Optional[Tracer] = None,
) -> PythonDeviceDomain:
    """Return a ``PythonDeviceDomain`` configured with the canonical KX6625 device map.

    Port and delay overrides are accepted for the console UART to keep
    backward compatibility with the ``--uart-*`` CLI flags.

    The topology matches ``spec/devices.yaml`` exactly::

        uart0   @ 0x40004000  rw=7890 irq=7891 nvic_irq=0 term=7904
        dma     @ 0x40005000  rw=7892 irq=7893 nvic_irq=1 mem=7897 tick=7905
        timer0  @ 0x40006000  rw=7894 irq=7895 nvic_irq=2  (shared tick=7896)
        demo    @ 0x40007000  rw=7898 irq=7899 nvic_irq=3
        crc     @ 0x40008000  rw=7900
        wdt     @ 0x40009000  rw=7901 irq=7902 nvic_irq=4 rst=7903
        hsm     @ 0x4000C000  rw=7908 irq=7909 nvic_irq=6 otp-provider=otp
        otp     @ 0x4000D000  rw=7910 irq=7911 nvic_irq=7 file=build/otp.hex
        flash   @ 0x4000E000  rw=7913 irq=7914 mem=7915 nvic_irq=8
        dflash  @ 0x10000000  rw=7916 size=512KB file=build/dflash.hex
    """
    return PythonDeviceDomain(
        uarts=[
            UartCfg(
                name      = 'uart0',
                base_addr = 0x40004000,
                rw_port   = uart_rw_port,
                irq_port  = uart_irq_port,
                nvic_irq  = 0,
                term_port = uart_term_port,
                irq_delay = uart_irq_delay,
            ),
        ],
        timers=[
            TimerCfg(
                name      = 'timer0',
                base_addr = 0x40006000,
                rw_port   = 7894,
                irq_port  = 7895,
                nvic_irq  = 2,
            ),
        ],
        dma=DmaCfg(
            base_addr    = 0x40005000,
            rw_port      = 7892,
            irq_port     = 7893,
            nvic_irq     = 1,
            mem_port     = 7897,
            tick_port    = 7905,
        ),
        dma_client_demo=DmaClientDemoCfg(
            base_addr   = 0x40007000,
            rw_port     = 7898,
            irq_port    = 7899,
            nvic_irq    = 3,
            dma_channel = 1,
        ),
        crc=CrcCfg(
            base_addr = 0x40008000,
            rw_port   = 7900,
        ),
        wdt=WdtCfg(
            base_addr = 0x40009000,
            rw_port   = 7901,
            irq_port  = 7902,
            nvic_irq  = 4,
            rst_port  = 7903,
        ),
        otp=OtpCfg(
            base_addr    = 0x4000D000,
            rw_port      = 7910,
            irq_port     = 7911,
            nvic_irq     = 7,
            storage_file = 'build/otp.hex',
        ),
        hsm=HsmCfg(
            base_addr = 0x4000C000,
            rw_port   = 7908,
            irq_port  = 7909,
            nvic_irq  = 6,
            otp_file  = 'build/hsm_otp.json',
        ),
        flash_ctrl=FlashCtrlCfg(
            base_addr     = 0x4000E000,
            rw_port       = 7913,
            irq_port      = 7914,
            nvic_irq      = 8,
            mem_port      = 7915,
            ahb_base_addr = 0x10000000,
            ahb_size      = 0x00080000,
            ahb_rw_port   = 7916,
            storage_file  = 'build/dflash.hex',
        ),
        tick_port = 7896,
        tracer    = tracer,
    )


# Backward-compatible public name used by older code and docs.
SoCTop = PythonDeviceDomain
