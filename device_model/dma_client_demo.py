"""
dma_client_demo — Example peripheral that uses DMA via DmaClientHandle.

This device model demonstrates the DMA client interface architecture:
instead of managing bus-master I/O directly, it calls
``self._dma.transfer()`` and receives a callback when the data movement
is complete — just like a real peripheral asserting a hardware DREQ line.

Register map (offsets from device base address, see spec/dma_client_demo.yaml)
-------------------------------------------------------------------------------
  0x00  SRC_ADDR  RW  DMA source address
  0x04  DST_ADDR  RW  DMA destination address
  0x08  LENGTH    RW  Transfer length in bytes
  0x0C  CTRL      RW  bit0=START — write 1 to kick off a transfer
  0x10  STATUS    R   bit0=BUSY, bit1=DONE

Hardware analogy
----------------
When firmware writes CTRL.START this peripheral asserts its DMA request
line (DREQ).  The DmaController accepts the request (DACK), performs the
memory copy over the required number of virtual ticks, then signals
completion by invoking ``_on_transfer_done()`` — analogous to the DMA
asserting a transfer-complete (TC) signal back to the peripheral.  The
peripheral then fires its own IRQ to notify the CPU.

This decouples the peripheral logic from DMA channel management: the device
only needs a DmaClientHandle, not direct access to MemChannel or tick logic.
"""

from __future__ import annotations

from typing import Optional

from device_model.mmio_base import DmaRequestInterface, IRQController, IrqLine, MMIODevice, RegisterBank


class DmaClientDemoDevice(MMIODevice):
    """
    Peripheral that initiates memory copies through the DMA engine.

    The constructor accepts a :class:`DmaClientHandle` (obtained from
    :meth:`DmaController.get_handle`) and an optional
    :class:`IRQController` + IRQ index.  At most one transfer can be
    in-flight at a time (STATUS.BUSY is set while the channel is active).

    Firmware interaction
    --------------------
    1. Write SRC_ADDR, DST_ADDR, LENGTH.
    2. Write CTRL = 0x1  (START bit).
    3. Device calls ``dma_handle.transfer()`` (DREQ asserted).
    4. DmaController performs the copy after ``transfer_ticks`` ticks.
    5. ``_on_transfer_done`` callback fires:
       - STATUS.DONE set, STATUS.BUSY cleared.
       - IRQ pulsed (assert then immediate deassert, NVIC-style).
    6. Firmware reads STATUS.DONE to confirm, or waits for the IRQ.
    """

    # Register offsets
    _SRC_ADDR = 0x00
    _DST_ADDR = 0x04
    _LENGTH   = 0x08
    _CTRL     = 0x0C
    _STATUS   = 0x10
    _REGSIZE  = 0x14

    # CTRL bits
    _CTRL_START  = 0x01

    # STATUS bits
    _STATUS_BUSY = 0x01
    _STATUS_DONE = 0x02

    def __init__(
        self,
        dma_handle: DmaRequestInterface,
        irq_controller: Optional[IRQController] = None,
        irq_idx: int = 0,
    ) -> None:
        self._regs = RegisterBank(self._REGSIZE)
        self._dma  = dma_handle
        self._irq  = IrqLine(irq_controller, irq_idx)

    @property
    def name(self) -> str:
        return f'DmaClientDemo(ch{self._dma.channel_id})'

    # -- MMIODevice interface ---------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        return self._regs.read(offset, size)

    def write(self, offset: int, size: int, data: bytes) -> None:
        self._regs.write(offset, size, data)
        if offset <= self._CTRL < offset + size:
            if self._regs.get32(self._CTRL) & self._CTRL_START:
                self._regs.clear_bits(self._CTRL, self._CTRL_START)
                self._kick_dma()

    def on_reset(self) -> None:
        self._regs.reset()

    def on_tick(self, vtime_ns: int) -> None:
        # DMA timing is driven by DmaController; this device has no own tick.
        pass

    # -- DMA handshake ----------------------------------------------------

    def _kick_dma(self) -> None:
        """Assert DREQ — request a DMA transfer from the controller."""
        with self._regs:
            src    = self._regs.get32_nolock(self._SRC_ADDR)
            dst    = self._regs.get32_nolock(self._DST_ADDR)
            length = self._regs.get32_nolock(self._LENGTH)
            self._regs[self._STATUS] = self._STATUS_BUSY

        print(
            f'[DMA_CLIENT] CH{self._dma.channel_id}: DREQ — '
            f'src=0x{src:08x} dst=0x{dst:08x} len={length}',
            flush=True,
        )

        ok = self._dma.transfer(src, dst, length, self._on_transfer_done)
        if not ok:
            print(
                f'[DMA_CLIENT] CH{self._dma.channel_id}: NACK — channel busy',
                flush=True,
            )
            with self._regs:
                self._regs[self._STATUS] = 0   # clear BUSY, request dropped

    def _on_transfer_done(self, success: bool) -> None:
        """DMA transfer-complete callback (TC) — called from DmaController thread."""
        with self._regs:
            if success:
                self._regs[self._STATUS] = (
                    (self._regs[self._STATUS] & ~self._STATUS_BUSY) | self._STATUS_DONE
                )
            else:
                self._regs[self._STATUS] = 0

        print(
            f'[DMA_CLIENT] CH{self._dma.channel_id}: TC — '
            f'transfer {"DONE" if success else "FAILED"}',
            flush=True,
        )

        # Pulse IRQ: edge-trigger so NVIC does not re-fire on exception return.
        self._irq.pulse()
