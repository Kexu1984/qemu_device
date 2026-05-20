#ifndef FIRMWARE_DRIVERS_DISPLAY_H
#define FIRMWARE_DRIVERS_DISPLAY_H

#include <stdint.h>

void display_irq_handler(void);
void display_scanout_once(uint32_t fb_base, uint32_t width, uint32_t height, uint32_t stride);
void display_scanout_layers_once(uint32_t layer0_fb_base,
								 uint32_t layer1_fb_base,
								 uint32_t layer1_x,
								 uint32_t layer1_y,
								 uint32_t width,
								 uint32_t height,
								 uint32_t stride,
								 uint32_t layer1_colorkey);
void test_display(void);

#endif /* FIRMWARE_DRIVERS_DISPLAY_H */