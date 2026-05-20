#include <stdint.h>
#include "base/lcd.h"
#include "base/main_loop.h"
#include "console_uart.h"
#include "lcd/lcd_mem_rgb565.h"
#include "main_loop/main_loop_simple.h"

#define AWTK_FB_ADDR ((uint8_t *)(uintptr_t)0x2001A000U)

lcd_t *platform_create_lcd(wh_t w, wh_t h)
{
    lcd_t *lcd;

    send_string("[AWTK] platform_create_lcd begin.\n");
    lcd = lcd_mem_rgb565_create_single_fb(w, h, AWTK_FB_ADDR);
    send_string(lcd != NULL ? "[AWTK] platform_create_lcd OK.\n" : "[AWTK] platform_create_lcd FAILED.\n");
    return lcd;
}

uint8_t platform_disaptch_input(main_loop_t *loop)
{
    (void)loop;
    return 0U;
}

#include "main_loop/main_loop_raw.inc"