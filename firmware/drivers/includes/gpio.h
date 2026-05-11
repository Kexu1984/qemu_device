#ifndef FIRMWARE_DRIVERS_GPIO_H
#define FIRMWARE_DRIVERS_GPIO_H

#include <stdint.h>

#define GPIO_ID_EXPECTED 0x4F495047U

void gpio_init(void);
uint32_t gpio_id(void);
void gpio_set_direction(uint32_t mask);
uint32_t gpio_get_direction(void);
void gpio_write(uint32_t value);
uint32_t gpio_read_output(void);
uint32_t gpio_read_input(void);
void gpio_set_bits(uint32_t mask);
void gpio_clear_bits(uint32_t mask);
void gpio_toggle_bits(uint32_t mask);
void gpio_set_input_sim(uint32_t value);
void gpio_irq_enable(uint32_t mask);
void gpio_irq_clear(uint32_t mask);
uint32_t gpio_irq_status(void);
void gpio_reset_irq_seen(void);
int gpio_irq_seen(void);
void gpio_handle_irq(void);
void test_gpio(void);

#endif /* FIRMWARE_DRIVERS_GPIO_H */
