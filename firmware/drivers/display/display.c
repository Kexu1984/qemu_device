#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "display.h"
#include "mmio.h"

#define DISPLAY_TEST_WIDTH        16U
#define DISPLAY_TEST_HEIGHT       16U
#define DISPLAY_TEST_STRIDE       (DISPLAY_TEST_WIDTH * 2U)
#define DISPLAY_TEST_FB           (SRAM_BASE + 0x7000U)
#define DISPLAY_FORMAT_RGB565     0U
#define DISPLAY_CTRL_ENABLE       0x1U
#define DISPLAY_CTRL_OUTPUT_EN    0x4U
#define DISPLAY_INT_FRAME_DONE    0x1U
#define DISPLAY_STATUS_FRAME_DONE 0x2U
#define DISPLAY_LAYER0_ENABLE     0x1U
#define DISPLAY_LAYER1_ENABLE     0x2U
#define DISPLAY_LAYER1_COLORKEY   0x100U

static volatile int display_irq_fired = 0;

static void send_hex32(uint32_t value)
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

static uint32_t crc32_update(uint32_t crc, uint8_t byte)
{
    uint32_t i;
    crc ^= byte;
    for (i = 0; i < 8U; i++) {
        crc = (crc & 1U) ? ((crc >> 1) ^ 0xEDB88320U) : (crc >> 1);
    }
    return crc;
}

static uint16_t display_pixel(uint32_t x, uint32_t y)
{
    uint32_t red = (x * 31U) / (DISPLAY_TEST_WIDTH - 1U);
    uint32_t green = (y * 63U) / (DISPLAY_TEST_HEIGHT - 1U);
    uint32_t blue = ((x ^ y) * 31U) / (DISPLAY_TEST_WIDTH - 1U);
    return (uint16_t)((red << 11) | (green << 5) | blue);
}

static uint32_t fill_framebuffer_and_crc(void)
{
    volatile uint16_t *fb = (volatile uint16_t *)(uintptr_t)DISPLAY_TEST_FB;
    uint32_t crc = 0xFFFFFFFFU;
    uint32_t y;

    for (y = 0; y < DISPLAY_TEST_HEIGHT; y++) {
        uint32_t x;
        for (x = 0; x < DISPLAY_TEST_WIDTH; x++) {
            uint16_t pixel = display_pixel(x, y);
            fb[(y * DISPLAY_TEST_WIDTH) + x] = pixel;
            crc = crc32_update(crc, (uint8_t)(pixel & 0xFFU));
            crc = crc32_update(crc, (uint8_t)(pixel >> 8));
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

void display_irq_handler(void)
{
    display_irq_fired++;
    mmio_write32(DISPLAY_INT_CLEAR_REG, DISPLAY_INT_FRAME_DONE);
    mmio_write32(DISPLAY_CTRL_REG, 0U);
    send_string("[IRQ] Display frame done! INTID=9\n");
}

void display_scanout_once(uint32_t fb_base, uint32_t width, uint32_t height, uint32_t stride)
{
    display_scanout_layers_once(fb_base, 0U, 0U, 0U, width, height, stride, 0U);
}

void display_scanout_layers_once(uint32_t layer0_fb_base,
                                 uint32_t layer1_fb_base,
                                 uint32_t layer1_x,
                                 uint32_t layer1_y,
                                 uint32_t width,
                                 uint32_t height,
                                 uint32_t stride,
                                 uint32_t layer1_colorkey)
{
    uint32_t tries;
    uint32_t layer_ctrl = DISPLAY_LAYER0_ENABLE;

    display_irq_fired = 0;
    if (layer1_fb_base != 0U) {
        layer_ctrl |= DISPLAY_LAYER1_ENABLE | DISPLAY_LAYER1_COLORKEY;
    }

    mmio_write32(DISPLAY_CTRL_REG, 0U);
    mmio_write32(DISPLAY_FB_BASE_REG, layer0_fb_base);
    mmio_write32(DISPLAY_FB_STRIDE_REG, stride);
    mmio_write32(DISPLAY_WIDTH_REG, width);
    mmio_write32(DISPLAY_HEIGHT_REG, height);
    mmio_write32(DISPLAY_FORMAT_REG, DISPLAY_FORMAT_RGB565);
    mmio_write32(DISPLAY_L1_FB_BASE_REG, layer1_fb_base);
    mmio_write32(DISPLAY_L1_FB_STRIDE_REG, stride);
    mmio_write32(DISPLAY_L1_X_REG, layer1_x);
    mmio_write32(DISPLAY_L1_Y_REG, layer1_y);
    mmio_write32(DISPLAY_L1_WIDTH_REG, width - layer1_x);
    mmio_write32(DISPLAY_L1_HEIGHT_REG, height - layer1_y);
    mmio_write32(DISPLAY_L1_FORMAT_REG, DISPLAY_FORMAT_RGB565);
    mmio_write32(DISPLAY_L1_COLORKEY_REG, layer1_colorkey);
    mmio_write32(DISPLAY_LAYER_CTRL_REG, layer_ctrl);
    mmio_write32(DISPLAY_H_TIMING_REG, (2U << 20) | (2U << 10) | 2U);
    mmio_write32(DISPLAY_V_TIMING_REG, (2U << 20) | (2U << 10) | 2U);
    mmio_write32(DISPLAY_PIXEL_CLOCK_HZ_REG, 1000000U);
    mmio_write32(DISPLAY_INT_CLEAR_REG, DISPLAY_INT_FRAME_DONE);
    mmio_write32(DISPLAY_INT_ENABLE_REG, DISPLAY_INT_FRAME_DONE);
    mmio_write32(DISPLAY_OUTPUT_CTRL_REG, 0x3U);
    mmio_write32(DISPLAY_CTRL_REG, DISPLAY_CTRL_ENABLE | DISPLAY_CTRL_OUTPUT_EN);

    for (tries = 0; tries < 1000000U; tries++) {
        if (display_irq_fired || (mmio_read32(DISPLAY_STATUS_REG) & DISPLAY_STATUS_FRAME_DONE)) {
            break;
        }
        __asm__ volatile ("wfi");
    }
}

void test_display(void)
{
    uint32_t expected_crc;
    uint32_t frame_crc;
    uint32_t tries;

    send_string("[FW] Display RGB565 framebuffer test.\n");

    if (mmio_read32(DISPLAY_ID_REG) != 0x50534944U) {
        send_string("[DISPLAY] ID check FAILED!\n");
        return;
    }
    send_string("[DISPLAY] ID DISP PASSED!\n");

    expected_crc = fill_framebuffer_and_crc();
    display_irq_fired = 0;

    mmio_write32(DISPLAY_CTRL_REG, 0U);
    mmio_write32(DISPLAY_FB_BASE_REG, DISPLAY_TEST_FB);
    mmio_write32(DISPLAY_FB_STRIDE_REG, DISPLAY_TEST_STRIDE);
    mmio_write32(DISPLAY_WIDTH_REG, DISPLAY_TEST_WIDTH);
    mmio_write32(DISPLAY_HEIGHT_REG, DISPLAY_TEST_HEIGHT);
    mmio_write32(DISPLAY_FORMAT_REG, DISPLAY_FORMAT_RGB565);
    mmio_write32(DISPLAY_LAYER_CTRL_REG, DISPLAY_LAYER0_ENABLE);
    mmio_write32(DISPLAY_H_TIMING_REG, (2U << 20) | (2U << 10) | 2U);
    mmio_write32(DISPLAY_V_TIMING_REG, (2U << 20) | (2U << 10) | 2U);
    mmio_write32(DISPLAY_PIXEL_CLOCK_HZ_REG, 1000000U);
    mmio_write32(DISPLAY_INT_CLEAR_REG, DISPLAY_INT_FRAME_DONE);
    mmio_write32(DISPLAY_INT_ENABLE_REG, DISPLAY_INT_FRAME_DONE);
    mmio_write32(DISPLAY_OUTPUT_CTRL_REG, 0x3U);

    send_string("[DISPLAY] Scanout enabled. Waiting for frame_done IRQ...\n");
    mmio_write32(DISPLAY_CTRL_REG, DISPLAY_CTRL_ENABLE | DISPLAY_CTRL_OUTPUT_EN);

    for (tries = 0; tries < 1000000U; tries++) {
        if (display_irq_fired || (mmio_read32(DISPLAY_STATUS_REG) & DISPLAY_STATUS_FRAME_DONE)) {
            break;
        }
        __asm__ volatile ("wfi");
    }

    frame_crc = mmio_read32(DISPLAY_FRAME_CRC_REG);

    if (!display_irq_fired) {
        send_string("[DISPLAY] Frame done IRQ FAILED!\n");
        return;
    }
    send_string("[DISPLAY] Frame done IRQ PASSED!\n");

    if (frame_crc == expected_crc) {
        send_string("[DISPLAY] Frame CRC ");
        send_hex32(frame_crc);
        send_string(" PASSED!\n");
    } else {
        send_string("[DISPLAY] Frame CRC FAILED! expected=");
        send_hex32(expected_crc);
        send_string(" actual=");
        send_hex32(frame_crc);
        send_string("\n");
    }
}