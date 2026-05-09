#ifndef FIRMWARE_DRIVERS_CONSOLE_UART_H
#define FIRMWARE_DRIVERS_CONSOLE_UART_H

#include <stdint.h>

#define UART_STATUS_TXREADY  (1u << 0)
#define UART_STATUS_RXREADY  (1u << 1)

#define UART_CTRL_ENABLE     (1u << 0)
#define UART_CTRL_RX_IRQ_EN  (1u << 1)

void console_uart_init(void);
void send_char(char c);
void send_string(const char *str);
int recv_line(char *buf, int len);
void console_uart_reset_irq_count(void);
void test_uart_irq(void);
void uart_irq_handler(void);

#endif /* FIRMWARE_DRIVERS_CONSOLE_UART_H */
