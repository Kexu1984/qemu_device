#include <stdint.h>
#include "awtk.h"
#include "awtk_global.h"
#include "awtk_demo.h"
#include "base/lcd.h"
#include "base/system_info.h"
#include "console_uart.h"
#include "display.h"
#include "lcd/lcd_mem_rgb565.h"
#include "mmio_devices.h"

#define AWTK_DEMO_WIDTH  96U
#define AWTK_DEMO_HEIGHT 64U
#define AWTK_DEMO_STRIDE (AWTK_DEMO_WIDTH * 2U)
#define AWTK_DEMO_BG_FB  (SRAM_BASE + 0x14000U)
#define AWTK_DEMO_FG_FB  (SRAM_BASE + 0x1A000U)
#define AWTK_DEMO_TRANSPARENT 0U
#define AWTK_POINTER_FRAMES 5U

typedef struct awtk_pointer_demo_t {
    uint32_t frame;
} awtk_pointer_demo_t;

typedef struct awtk_point_t {
    int8_t x;
    int8_t y;
} awtk_point_t;

static const awtk_point_t s_pointer_tip[] = {
    {-17, 17}, {-22, 7}, {-22, -6}, {-14, -18}, {0, -24}, {14, -18},
    {22, -6}, {22, 7}, {17, 17}, {22, 7}, {14, -18}, {0, -24}
};

static const awtk_point_t s_tick_outer[] = {
    {-24, 18}, {-28, 8}, {-26, -5}, {-18, -17}, {-6, -24}, {6, -24}, {18, -17}, {26, -5}, {28, 8}, {24, 18}
};

static color_t awtk_color(uint8_t r, uint8_t g, uint8_t b)
{
    return color_init(r, g, b, 0xffU);
}

static uint16_t awtk_rgb565(uint8_t r, uint8_t g, uint8_t b)
{
    return (uint16_t)((((uint32_t)r >> 3) << 11) | (((uint32_t)g >> 2) << 5) | ((uint32_t)b >> 3));
}

static void awtk_raw_fill_rect_fb(uint32_t fb_base, int32_t x, int32_t y, int32_t w, int32_t h, uint16_t color)
{
    volatile uint16_t *fb = (volatile uint16_t *)(uintptr_t)fb_base;
    int32_t row;
    int32_t col;

    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > (int32_t)AWTK_DEMO_WIDTH) {
        w = (int32_t)AWTK_DEMO_WIDTH - x;
    }
    if (y + h > (int32_t)AWTK_DEMO_HEIGHT) {
        h = (int32_t)AWTK_DEMO_HEIGHT - y;
    }
    if (w <= 0 || h <= 0) {
        return;
    }

    for (row = 0; row < h; row++) {
        for (col = 0; col < w; col++) {
            fb[((y + row) * AWTK_DEMO_WIDTH) + x + col] = color;
        }
    }
}

static void awtk_clear_framebuffer(uint32_t fb_base, uint16_t color)
{
    volatile uint16_t *fb = (volatile uint16_t *)(uintptr_t)fb_base;
    uint32_t i;

    for (i = 0; i < AWTK_DEMO_WIDTH * AWTK_DEMO_HEIGHT; i++) {
        fb[i] = color;
    }
}

static int32_t awtk_abs32(int32_t value)
{
    return value < 0 ? -value : value;
}

static void awtk_lcd_fill_rect(lcd_t *lcd, int32_t x, int32_t y, int32_t w, int32_t h)
{
    static point_t points[AWTK_DEMO_WIDTH];
    int32_t row;
    int32_t col;

    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > (int32_t)AWTK_DEMO_WIDTH) {
        w = (int32_t)AWTK_DEMO_WIDTH - x;
    }
    if (y + h > (int32_t)AWTK_DEMO_HEIGHT) {
        h = (int32_t)AWTK_DEMO_HEIGHT - y;
    }
    if (w <= 0 || h <= 0) {
        return;
    }

    lcd_set_stroke_color(lcd, lcd->fill_color);
    for (row = 0; row < h; row++) {
        for (col = 0; col < w; col++) {
            points[col].x = (xy_t)(x + col);
            points[col].y = (xy_t)(y + row);
        }
        lcd_draw_points(lcd, points, (uint32_t)w);
    }
}

static void awtk_draw_rect_line(lcd_t *lcd, int32_t x1, int32_t y1, int32_t x2, int32_t y2, int32_t thickness)
{
    int32_t dx = awtk_abs32(x2 - x1);
    int32_t sx = x1 < x2 ? 1 : -1;
    int32_t dy = -awtk_abs32(y2 - y1);
    int32_t sy = y1 < y2 ? 1 : -1;
    int32_t err = dx + dy;
    int32_t half = thickness / 2;

    for (;;) {
        awtk_lcd_fill_rect(lcd, x1 - half, y1 - half, thickness, thickness);
        if (x1 == x2 && y1 == y2) {
            break;
        }
        if ((err * 2) >= dy) {
            err += dy;
            x1 += sx;
        }
        if ((err * 2) <= dx) {
            err += dx;
            y1 += sy;
        }
    }
}

static void awtk_background_draw(void)
{
    const int32_t cx = 48;
    const int32_t cy = 38;
    uint32_t i;

    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 0, 0, AWTK_DEMO_WIDTH, AWTK_DEMO_HEIGHT, awtk_rgb565(10U, 14U, 22U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 8, 8, 80, 48, awtk_rgb565(22U, 32U, 44U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 8, 8, 80, 1, awtk_rgb565(90U, 104U, 128U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 8, 55, 80, 1, awtk_rgb565(90U, 104U, 128U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 8, 8, 1, 48, awtk_rgb565(90U, 104U, 128U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 87, 8, 1, 48, awtk_rgb565(90U, 104U, 128U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 20, 52, 56, 1, awtk_rgb565(148U, 163U, 184U));

    for (i = 0; i < sizeof(s_tick_outer) / sizeof(s_tick_outer[0]); i++) {
        awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB,
                              cx + s_tick_outer[i].x - 1,
                              cy + s_tick_outer[i].y - 1,
                              3,
                              3,
                              (i == 0U || i == 9U) ? awtk_rgb565(248U, 113U, 113U) : awtk_rgb565(203U, 213U, 225U));
    }

    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 18, 14, 22, 3, awtk_rgb565(226U, 232U, 240U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 44, 14, 34, 3, awtk_rgb565(226U, 232U, 240U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_BG_FB, 34, 48, 28, 6, awtk_rgb565(15U, 23U, 42U));
}

static void awtk_pointer_draw(lcd_t *lcd, awtk_pointer_demo_t *demo)
{
    const int32_t cx = 48;
    const int32_t cy = 38;
    const awtk_point_t tip = s_pointer_tip[demo->frame % (sizeof(s_pointer_tip) / sizeof(s_pointer_tip[0]))];

    awtk_raw_fill_rect_fb(AWTK_DEMO_FG_FB, 20, 10, 60, 46, AWTK_DEMO_TRANSPARENT);

    lcd_set_fill_color(lcd, awtk_color(45U, 212U, 191U));
    awtk_draw_rect_line(lcd, cx, cy, cx + tip.x, cy + tip.y, 3);
    lcd_set_fill_color(lcd, awtk_color(251U, 191U, 36U));
    awtk_lcd_fill_rect(lcd, cx - 2, cy - 2, 5, 5);

    awtk_raw_fill_rect_fb(AWTK_DEMO_FG_FB, 36, 49, 4, 2, awtk_rgb565(94U, 234U, 212U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_FG_FB, 43, 49, 4, 2, awtk_rgb565(94U, 234U, 212U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_FG_FB, 50, 49, 4, 2, awtk_rgb565(94U, 234U, 212U));
    awtk_raw_fill_rect_fb(AWTK_DEMO_FG_FB, 57, 49, 4, 2, awtk_rgb565(94U, 234U, 212U));
}

static void awtk_scanout_pointer_frames(lcd_t *lcd, awtk_pointer_demo_t *demo)
{
    uint32_t frame;

    for (frame = 0; frame < AWTK_POINTER_FRAMES; frame++) {
        demo->frame = frame;
        awtk_pointer_draw(lcd, demo);
        display_scanout_layers_once(AWTK_DEMO_BG_FB,
                                    AWTK_DEMO_FG_FB,
                                    0U,
                                    0U,
                                    AWTK_DEMO_WIDTH,
                                    AWTK_DEMO_HEIGHT,
                                    AWTK_DEMO_STRIDE,
                                    AWTK_DEMO_TRANSPARENT);
    }
}

void test_awtk_display(void)
{
    static awtk_pointer_demo_t demo;
    lcd_t *lcd;

    send_string("[AWTK] animated pointer demo start.\n");
    awtk_background_draw();
    awtk_clear_framebuffer(AWTK_DEMO_FG_FB, AWTK_DEMO_TRANSPARENT);
    send_string("[AWTK] layer framebuffers prepared.\n");

    send_string("[AWTK] tk_pre_init begin.\n");
    if (tk_pre_init() != RET_OK) {
        send_string("[AWTK] tk_pre_init FAILED!\n");
        return;
    }
    send_string("[AWTK] tk_pre_init OK.\n");

    send_string("[AWTK] system_info_init begin.\n");
    if (system_info_init(APP_MOBILE, "qemu-display", "") != RET_OK) {
        send_string("[AWTK] system_info_init FAILED!\n");
        return;
    }
    send_string("[AWTK] system_info_init OK.\n");

    send_string("[AWTK] tk_init_internal begin.\n");
    if (tk_init_internal() != RET_OK) {
        send_string("[AWTK] tk_init_internal FAILED!\n");
        return;
    }
    send_string("[AWTK] tk_init_internal OK.\n");

    send_string("[AWTK] lcd_mem_rgb565_create begin.\n");
    lcd = lcd_mem_rgb565_create_single_fb(AWTK_DEMO_WIDTH, AWTK_DEMO_HEIGHT, (uint8_t *)(uintptr_t)AWTK_DEMO_FG_FB);
    if (lcd == NULL) {
        send_string("[AWTK] lcd_mem_rgb565_create FAILED!\n");
        return;
    }
    send_string("[AWTK] lcd_mem_rgb565_create OK.\n");

    send_string("[AWTK] pointer animation begin.\n");
    awtk_scanout_pointer_frames(lcd, &demo);
    send_string("[AWTK] pointer animation done.\n");

    lcd_destroy(lcd);

    send_string("[AWTK] RGB565 display demo done.\n");
}