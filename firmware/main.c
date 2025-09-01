/*
 * Bare metal ARMv7-A firmware for testing MMIO socket device
 * 
 * This firmware writes "Hello from MMIO sockdev\n" to the custom MMIO device
 * which should be mapped at MMIO_BASE (0x10020000).
 */

#include <stdint.h>

#define MMIO_BASE    0x10020000
#define TXDATA_REG   (MMIO_BASE + 0x00)
#define STATUS_REG   (MMIO_BASE + 0x04)
#define CTRL_REG     (MMIO_BASE + 0x08)

/* Memory-mapped I/O access functions */
static inline void mmio_write32(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t*)addr = value;
}

static inline uint32_t mmio_read32(uint32_t addr)
{
    return *(volatile uint32_t*)addr;
}

static inline void mmio_write8(uint32_t addr, uint8_t value)
{
    *(volatile uint8_t*)addr = value;
}

/* Wait for TXREADY bit in STATUS register */
static void wait_tx_ready(void)
{
    while (!(mmio_read32(STATUS_REG) & 0x1)) {
        /* Busy wait for TXREADY */
    }
}

/* Send a character via MMIO device */
static void send_char(char c)
{
    wait_tx_ready();
    mmio_write8(TXDATA_REG, c);
}

/* Send a string via MMIO device */
static void send_string(const char *str)
{
    while (*str) {
        send_char(*str);
        str++;
    }
}

/* Main C function */
void main(void)
{
    /* Enable the device */
    mmio_write32(CTRL_REG, 0x1);
    
    /* Send test message */
    send_string("Hello from MMIO sockdev\n");
    
    /* Infinite loop - firmware complete */
    while (1) {
        __asm__ volatile ("wfi"); /* Wait for interrupt */
    }
}