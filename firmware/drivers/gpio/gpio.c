#include <stdint.h>
#include "mmio_devices.h"
#include "console_uart.h"
#include "gpio.h"
#include "mcal_gpio.h"
#include "mmio.h"

static volatile int gpio_irq_fired = 0;

void gpio_init(void)
{
    mmio_write32(SV_TIMER_GPIO_IRQ_EN_REG, 0U);
    mmio_write32(SV_TIMER_GPIO_IRQ_STATUS_REG, 0xFFFFFFFFU);
    mmio_write32(SV_TIMER_GPIO_DIR_REG, 0U);
    mmio_write32(SV_TIMER_GPIO_DATA_OUT_REG, 0U);
    mmio_write32(SV_TIMER_GPIO_INPUT_SIM_REG, 0U);
    gpio_irq_fired = 0;
}

uint32_t gpio_id(void)
{
    return mmio_read32(SV_TIMER_GPIO_ID_REG);
}

void gpio_set_direction(uint32_t mask)
{
    mmio_write32(SV_TIMER_GPIO_DIR_REG, mask);
}

uint32_t gpio_get_direction(void)
{
    return mmio_read32(SV_TIMER_GPIO_DIR_REG);
}

void gpio_write(uint32_t value)
{
    mmio_write32(SV_TIMER_GPIO_DATA_OUT_REG, value);
}

uint32_t gpio_read_output(void)
{
    return mmio_read32(SV_TIMER_GPIO_DATA_OUT_REG);
}

uint32_t gpio_read_input(void)
{
    return mmio_read32(SV_TIMER_GPIO_DATA_IN_REG);
}

void gpio_set_bits(uint32_t mask)
{
    mmio_write32(SV_TIMER_GPIO_SET_REG, mask);
}

void gpio_clear_bits(uint32_t mask)
{
    mmio_write32(SV_TIMER_GPIO_CLR_REG, mask);
}

void gpio_toggle_bits(uint32_t mask)
{
    mmio_write32(SV_TIMER_GPIO_TOGGLE_REG, mask);
}

void gpio_set_input_sim(uint32_t value)
{
    mmio_write32(SV_TIMER_GPIO_INPUT_SIM_REG, value);
}

void gpio_irq_enable(uint32_t mask)
{
    mmio_write32(SV_TIMER_GPIO_IRQ_EN_REG, mask);
}

void gpio_irq_clear(uint32_t mask)
{
    mmio_write32(SV_TIMER_GPIO_IRQ_STATUS_REG, mask);
}

uint32_t gpio_irq_status(void)
{
    return mmio_read32(SV_TIMER_GPIO_IRQ_STATUS_REG);
}

void gpio_reset_irq_seen(void)
{
    gpio_irq_fired = 0;
}

int gpio_irq_seen(void)
{
    return gpio_irq_fired != 0;
}

void gpio_handle_irq(void)
{
    uint32_t status = gpio_irq_status();
    if (status != 0U) {
        gpio_irq_clear(status);
        gpio_irq_fired++;
        send_string("[IRQ] SV GPIO changed! INTID=5\n");
    }
}

void test_gpio(void)
{
    int ok;

    send_string("[GPIO] SV GPIO test.\n");
    gpio_init();
    send_string(gpio_id() == GPIO_ID_EXPECTED ? "[GPIO] SV GPIO ID GPIO PASSED!\n"
                                               : "[GPIO] SV GPIO ID FAILED!\n");

    gpio_set_direction(0x0000000FU);
    gpio_write(0U);
    gpio_set_bits(0x00000005U);
    ok = (gpio_read_output() & 0xFU) == 0x5U && (gpio_read_input() & 0xFU) == 0x5U;
    send_string(ok ? "[GPIO] Output set/readback PASSED!\n" : "[GPIO] Output set/readback FAILED!\n");

    gpio_toggle_bits(0x00000003U);
    ok = (gpio_read_output() & 0xFU) == 0x6U && (gpio_read_input() & 0xFU) == 0x6U;
    send_string(ok ? "[GPIO] Output toggle PASSED!\n" : "[GPIO] Output toggle FAILED!\n");

    gpio_set_input_sim(0x000000A0U);
    ok = (gpio_read_input() & 0xF0U) == 0xA0U;
    send_string(ok ? "[GPIO] Input simulation PASSED!\n" : "[GPIO] Input simulation FAILED!\n");

    gpio_irq_clear(0xFFFFFFFFU);
    gpio_reset_irq_seen();
    gpio_irq_enable(0x00000001U);
    gpio_write(gpio_read_output() & ~0x1U);
    gpio_irq_clear(0xFFFFFFFFU);
    gpio_write(gpio_read_output() | 0x1U);
    while (!gpio_irq_seen()) {
        __asm__ volatile ("wfi");
    }
    gpio_irq_enable(0U);
    send_string("[GPIO] Change IRQ PASSED!\n");

    {
        Mcal_GpioChannelConfigType channel_cfg = { 2U, MCAL_GPIO_OUTPUT, MCAL_GPIO_LOW };
        Mcal_GpioConfigType gpio_cfg = { &channel_cfg, 1U };
        ok = Mcal_Gpio_Init(&gpio_cfg) == MCAL_OK;
        ok = ok && Mcal_Gpio_WriteChannel(2U, MCAL_GPIO_HIGH) == MCAL_OK;
        ok = ok && Mcal_Gpio_ReadChannel(2U) == MCAL_GPIO_HIGH;
        ok = ok && Mcal_Gpio_ToggleChannel(2U) == MCAL_GPIO_LOW;
        send_string(ok ? "[GPIO] MCAL output toggle PASSED!\n" : "[GPIO] MCAL output toggle FAILED!\n");
    }
}
