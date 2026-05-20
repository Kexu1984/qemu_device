#include <stdint.h>
#include <stddef.h>
#include "FreeRTOS.h"
#include "task.h"
#include "console_uart.h"
#include "tkc/mem.h"
#include "tkc/platform.h"

#ifndef TK_HEAP_MEM_SIZE
#define TK_HEAP_MEM_SIZE (24 * 1024)
#endif

static void awtk_send_uint(uint32_t value)
{
    char buf[11];
    uint32_t i = 0;

    if (value == 0U) {
        send_char('0');
        return;
    }

    while (value != 0U && i < sizeof(buf)) {
        buf[i++] = (char)('0' + (value % 10U));
        value /= 10U;
    }
    while (i > 0U) {
        send_char(buf[--i]);
    }
}

uint64_t get_time_ms64(void)
{
    return (uint64_t)xTaskGetTickCount();
}

uint64_t get_time_us64(void)
{
    return get_time_ms64() * 1000ULL;
}

void sleep_ms(uint32_t ms)
{
    vTaskDelay(pdMS_TO_TICKS(ms));
}

void sleep_us(uint32_t us)
{
    if (us >= 1000U) {
        sleep_ms(us / 1000U);
    }
}

ret_t platform_prepare(void)
{
    static uint32_t heap_mem[TK_HEAP_MEM_SIZE / sizeof(uint32_t)];
    static int inited;
    ret_t ret;

    if (inited) {
        send_string("[AWTK] platform_prepare already done.\n");
        return RET_OK;
    }

    send_string("[AWTK] platform_prepare begin.\n");
    inited = 1;
    ret = tk_mem_init(heap_mem, sizeof(heap_mem));
    send_string(ret == RET_OK ? "[AWTK] tk_mem_init OK.\n" : "[AWTK] tk_mem_init FAILED.\n");
    return ret;
}

void __assert_func(const char *file, int line, const char *func, const char *expr)
{
    send_string("[AWTK] assert failed: ");
    send_string(file != NULL ? file : "<unknown>");
    send_string(":");
    awtk_send_uint((uint32_t)line);
    send_string(" ");
    send_string(func != NULL ? func : "<unknown>");
    send_string(" ");
    send_string(expr != NULL ? expr : "<expr>");
    send_string("\n");
    for (;;) {
    }
}

char *strchr(const char *str, int ch)
{
    char needle = (char)ch;

    while (*str != '\0') {
        if (*str == needle) {
            return (char *)str;
        }
        str++;
    }

    return needle == '\0' ? (char *)str : NULL;
}

const char _ctype_[257] = {0};