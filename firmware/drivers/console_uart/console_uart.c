#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "mmio.h"

static volatile int irq_count = 0;

void console_uart_init(void)
{
    mmio_write32(CONSOLE_UART_CTRL_REG, UART_CTRL_ENABLE);
}

void send_char(char c)
{
    mmio_write8(CONSOLE_UART_TXDATA_REG, (uint8_t)c);
}

void send_string(const char *str)
{
    while (*str) {
        send_char(*str++);
    }
}

static char read_char(void)
{
    mmio_write32(CONSOLE_UART_CTRL_REG, UART_CTRL_ENABLE | UART_CTRL_RX_IRQ_EN);
    while (!(mmio_read32(CONSOLE_UART_STATUS_REG) & UART_STATUS_RXREADY)) {
        __asm__ volatile ("wfi");
    }
    return (char)(mmio_read32(CONSOLE_UART_RXDATA_REG) & 0x7F);
}

int recv_line(char *buf, int len)
{
    int n = 0;
    while (n < len - 1) {
        char c = read_char();
        if (c == '\n' || c == '\r') {
            send_string("\n");
            break;
        }
        send_char(c);
        buf[n++] = c;
    }
    buf[n] = '\0';
    return n;
}

void console_uart_reset_irq_count(void)
{
    irq_count = 0;
}

void uart_irq_handler(void)
{
    irq_count++;
    send_string("[IRQ] UART interrupt! INTID=0\n");
}

void test_uart_irq(void)
{
    send_string("[FW] IRQs enabled. Waiting for UART interrupt from Python server...\n");
    send_string("[FW] (Python server will assert IRQ ~2 s after connection)\n");
    while (irq_count == 0) {
        __asm__ volatile ("wfi");
    }
    send_string("[FW] UART interrupt handled successfully!\n");
}
