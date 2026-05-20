#include <stddef.h>
#include <stdint.h>
#include "console_uart.h"

static void runtime_send_hex32(uint32_t value)
{
    static const char hex[] = "0123456789ABCDEF";
    char buf[11];
    int i;

    buf[0] = '0';
    buf[1] = 'x';
    for (i = 0; i < 8; i++) {
        buf[2 + i] = hex[(value >> (28 - (i * 4))) & 0xFU];
    }
    buf[10] = '\0';
    send_string(buf);
}

void *memset(void *dest, int value, size_t len)
{
    unsigned char *out = (unsigned char *)dest;

    while (len-- != 0U) {
        *out++ = (unsigned char)value;
    }

    return dest;
}

void *memcpy(void *dest, const void *src, size_t len)
{
    unsigned char *out = (unsigned char *)dest;
    const unsigned char *in = (const unsigned char *)src;

    while (len-- != 0U) {
        *out++ = *in++;
    }

    return dest;
}

void firmware_hardfault_handler(uint32_t *stack_frame)
{
    send_string("[FAULT] HardFault\n");
    if (stack_frame != NULL) {
        send_string("[FAULT] stacked_pc=");
        runtime_send_hex32(stack_frame[6]);
        send_string(" stacked_lr=");
        runtime_send_hex32(stack_frame[5]);
        send_string(" xpsr=");
        runtime_send_hex32(stack_frame[7]);
        send_string("\n");
    }
    send_string("[FAULT] CFSR=");
    runtime_send_hex32(*(volatile uint32_t *)0xE000ED28U);
    send_string(" HFSR=");
    runtime_send_hex32(*(volatile uint32_t *)0xE000ED2CU);
    send_string(" BFAR=");
    runtime_send_hex32(*(volatile uint32_t *)0xE000ED38U);
    send_string("\n");
}

void firmware_defaultfault_handler(void)
{
    send_string("[FAULT] Default exception\n");
}
