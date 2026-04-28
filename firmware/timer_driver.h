/**
 * timer_driver.h — bare-metal driver for timer0
 *
 * Self-contained header; include after mmio_devices.h (or let the firmware
 * Makefile pull it in via -I ../build/generated).
 *
 * Timer0 register map (all offsets from TIMER0_BASE):
 *   LOAD   0x00  RW  Countdown value in milliseconds
 *   VALUE  0x04  R   Remaining time in ms (approximate)
 *   CTRL   0x08  RW  bit0=ENABLE, bit1=PERIODIC, bit2=INT_ENABLE
 *   STATUS 0x0C  R   bit0=INT_PENDING
 *   INTCLR 0x10  W   Write any value to clear INT_PENDING + deassert IRQ
 *
 * GIC wiring (ARM virt machine, GICv2):
 *   Timer0 uses SPI 2  →  INTID 34  (bit 2 of GICD_ISENABLER1)
 *
 * Typical one-shot usage:
 *   timer0_gic_enable();          // once, during board init
 *   enable_irq();                 // CPSR.I = 0
 *   timer0_start(500, 0);         // fire once after 500 ms
 *   // … IRQ handler calls timer0_clear_irq() …
 *
 * Typical periodic usage:
 *   timer0_start(1000, 1);        // fire every 1 000 ms
 */

#pragma once
#include <stdint.h>
#include "mmio_devices.h"   /* generated — provides TIMER0_*_REG macros */

/* -------------------------------------------------------------------------
 * CTRL register bit masks
 * ---------------------------------------------------------------------- */
#define TIMER_CTRL_ENABLE      (1U << 0)  /**< Start the countdown          */
#define TIMER_CTRL_PERIODIC    (1U << 1)  /**< Auto-reload when expired      */
#define TIMER_CTRL_INT_ENABLE  (1U << 2)  /**< Assert IRQ on expiry          */

/* -------------------------------------------------------------------------
 * STATUS register bit masks
 * ---------------------------------------------------------------------- */
#define TIMER_STATUS_INT_PENDING  (1U << 0)  /**< Countdown reached zero     */

/* -------------------------------------------------------------------------
 * GIC register helpers (referenced from timer0_gic_enable)
 * These macros rely on GICD_ISENABLER1 / GICD_IPRIORITYR8 / GICD_ITARGETSR8
 * already defined in mmio_devices.h (generated from spec/devices.yaml).
 * ---------------------------------------------------------------------- */

/**
 * timer0_gic_enable - configure GICv2 to forward timer0 IRQ to CPU 0.
 *
 * Must be called once during board init, BEFORE enabling IRQs in CPSR.
 * Does NOT call enable_irq() itself — the caller controls that.
 *
 * GIC INTID 34 = SPI 2:
 *   GICD_ISENABLER1  bit 2  (INTID 34 − 32 = 2)
 *   GICD_IPRIORITYR8 byte 2 (INTID 32..35 share this 32-bit register)
 *   GICD_ITARGETSR8  byte 2 (route to CPU 0 = bit 0)
 *   GICD_IGROUPR1    bit 2  (Group 1 = non-secure, same as UART)
 *   GICD_ICPENDR1    bit 2  (clear stale pending state)
 */
static inline void timer0_gic_enable(void)
{
    /* Group 1 (non-secure) */
    *(volatile uint32_t *)GICD_IGROUPR1 |= (1U << (TIMER0_IRQ_INTID - 32));

    /* Clear stale pending state */
    *(volatile uint32_t *)GICD_ICPENDR1  = (1U << (TIMER0_IRQ_INTID - 32));

    /* Priority 0x80 (byte-access into the 32-bit register) */
    *(volatile uint8_t *)(GICD_IPRIORITYR8 + (TIMER0_IRQ_INTID - 32)) = 0x80;

    /* Route to CPU 0 (byte-access into GICD_ITARGETSR8) */
    *(volatile uint8_t *)(GICD_ITARGETSR8  + (TIMER0_IRQ_INTID - 32)) = 0x01;

    /* Enable INTID 34 at the Distributor */
    *(volatile uint32_t *)GICD_ISENABLER1  = (1U << (TIMER0_IRQ_INTID - 32));
}

/* -------------------------------------------------------------------------
 * Timer control API
 * ---------------------------------------------------------------------- */

/**
 * timer0_start - load and start the timer.
 *
 * @ms       countdown value in milliseconds (0 = no-op)
 * @periodic 1 = auto-reload (periodic mode), 0 = one-shot
 *
 * Disables the timer first so that re-arming mid-count is safe.
 */
static inline void timer0_start(uint32_t ms, int periodic)
{
    /* Disable to abort any running count */
    *(volatile uint32_t *)TIMER0_CTRL_REG = 0;

    *(volatile uint32_t *)TIMER0_LOAD_REG = ms;

    uint32_t ctrl = TIMER_CTRL_ENABLE | TIMER_CTRL_INT_ENABLE;
    if (periodic)
        ctrl |= TIMER_CTRL_PERIODIC;

    *(volatile uint32_t *)TIMER0_CTRL_REG = ctrl;
}

/**
 * timer0_stop - disable the timer immediately.
 *
 * STATUS.INT_PENDING is NOT cleared; call timer0_clear_irq() if needed.
 */
static inline void timer0_stop(void)
{
    *(volatile uint32_t *)TIMER0_CTRL_REG = 0;
}

/**
 * timer0_read_value - return approximate remaining time in milliseconds.
 */
static inline uint32_t timer0_read_value(void)
{
    return *(volatile uint32_t *)TIMER0_VALUE_REG;
}

/**
 * timer0_read_status - return the raw STATUS register.
 *
 * Test return value with TIMER_STATUS_INT_PENDING to poll for expiry.
 */
static inline uint32_t timer0_read_status(void)
{
    return *(volatile uint32_t *)TIMER0_STATUS_REG;
}

/**
 * timer0_clear_irq - clear INT_PENDING and deassert the IRQ line.
 *
 * Call this from the IRQ handler (INTID 34) before issuing GICC_EOIR.
 */
static inline void timer0_clear_irq(void)
{
    *(volatile uint32_t *)TIMER0_INTCLR_REG = 1;
}

/* -------------------------------------------------------------------------
 * IRQ handler integration note
 * -------------------------------------------------------------------------
 *
 * The existing c_irq_handler in main.c dispatches on the INTID read from
 * GICC_IAR.  To also handle timer0 interrupts, add a branch like:
 *
 *   #include "timer_driver.h"
 *
 *   void c_irq_handler(void) {
 *       uint32_t intid = mmio_read32(GICC_IAR) & 0x3FFu;
 *
 *       if (intid == CONSOLE_UART_IRQ_INTID) {          // 32
 *           // … UART handling …
 *       } else if (intid == TIMER0_IRQ_INTID) {         // 34
 *           timer0_clear_irq();
 *           // … timer handling …
 *       } else if (intid == 1023u) {
 *           // spurious
 *       }
 *       mmio_write32(GICC_EOIR, intid);
 *   }
 *
 * GIC init sequence: call gic_init() (enables INTID 32) then
 *   timer0_gic_enable()  (enables INTID 34).
 * ---------------------------------------------------------------------- */
