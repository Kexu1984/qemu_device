#include <stdint.h>
#include "gpio.h"
#include "mcal_gpio.h"

static Mcal_BooleanType gpio_channel_valid(Mcal_GpioChannelType channel)
{
    return channel < MCAL_GPIO_MAX_CHANNELS ? MCAL_TRUE : MCAL_FALSE;
}

Mcal_ReturnType Mcal_Gpio_Init(const Mcal_GpioConfigType *config)
{
    gpio_init();

    if (config == 0) {
        return MCAL_OK;
    }

    for (uint32_t i = 0; i < config->num_channels; i++) {
        Mcal_GpioChannelType channel = config->channels[i].channel;
        if (gpio_channel_valid(channel) == MCAL_FALSE) {
            return MCAL_NOT_OK;
        }
        if (Mcal_Gpio_SetDirection(channel, config->channels[i].direction) != MCAL_OK) {
            return MCAL_NOT_OK;
        }
        if (config->channels[i].direction == MCAL_GPIO_OUTPUT &&
            Mcal_Gpio_WriteChannel(channel, config->channels[i].initial_level) != MCAL_OK) {
            return MCAL_NOT_OK;
        }
    }

    return MCAL_OK;
}

Mcal_ReturnType Mcal_Gpio_SetDirection(Mcal_GpioChannelType channel, Mcal_GpioDirectionType direction)
{
    uint32_t mask;
    uint32_t dir;

    if (gpio_channel_valid(channel) == MCAL_FALSE) {
        return MCAL_NOT_OK;
    }

    mask = 1U << channel;
    dir = gpio_get_direction();
    if (direction == MCAL_GPIO_OUTPUT) {
        dir |= mask;
    } else {
        dir &= ~mask;
    }
    gpio_set_direction(dir);
    return MCAL_OK;
}

Mcal_ReturnType Mcal_Gpio_WriteChannel(Mcal_GpioChannelType channel, Mcal_GpioLevelType level)
{
    uint32_t mask;

    if (gpio_channel_valid(channel) == MCAL_FALSE) {
        return MCAL_NOT_OK;
    }

    mask = 1U << channel;
    if ((gpio_get_direction() & mask) == 0U) {
        return MCAL_NOT_OK;
    }

    if (level == MCAL_GPIO_HIGH) {
        gpio_set_bits(mask);
    } else {
        gpio_clear_bits(mask);
    }
    return MCAL_OK;
}

Mcal_GpioLevelType Mcal_Gpio_ReadChannel(Mcal_GpioChannelType channel)
{
    if (gpio_channel_valid(channel) == MCAL_FALSE) {
        return MCAL_GPIO_LOW;
    }

    return (gpio_read_input() & (1U << channel)) != 0U ? MCAL_GPIO_HIGH : MCAL_GPIO_LOW;
}

Mcal_GpioLevelType Mcal_Gpio_ToggleChannel(Mcal_GpioChannelType channel)
{
    uint32_t mask;

    if (gpio_channel_valid(channel) == MCAL_FALSE) {
        return MCAL_GPIO_LOW;
    }

    mask = 1U << channel;
    if ((gpio_get_direction() & mask) == 0U) {
        return MCAL_GPIO_LOW;
    }

    gpio_toggle_bits(mask);
    return Mcal_Gpio_ReadChannel(channel);
}
