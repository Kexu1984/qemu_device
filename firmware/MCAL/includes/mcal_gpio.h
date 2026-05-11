#ifndef FIRMWARE_MCAL_GPIO_H
#define FIRMWARE_MCAL_GPIO_H

#include <stdint.h>
#include "mcal_types.h"

#define MCAL_GPIO_MAX_CHANNELS 32U

typedef uint32_t Mcal_GpioChannelType;

typedef enum {
    MCAL_GPIO_LOW = 0U,
    MCAL_GPIO_HIGH = 1U
} Mcal_GpioLevelType;

typedef enum {
    MCAL_GPIO_INPUT = 0U,
    MCAL_GPIO_OUTPUT = 1U
} Mcal_GpioDirectionType;

typedef struct {
    Mcal_GpioChannelType channel;
    Mcal_GpioDirectionType direction;
    Mcal_GpioLevelType initial_level;
} Mcal_GpioChannelConfigType;

typedef struct {
    const Mcal_GpioChannelConfigType *channels;
    uint32_t num_channels;
} Mcal_GpioConfigType;

Mcal_ReturnType Mcal_Gpio_Init(const Mcal_GpioConfigType *config);
Mcal_ReturnType Mcal_Gpio_SetDirection(Mcal_GpioChannelType channel, Mcal_GpioDirectionType direction);
Mcal_ReturnType Mcal_Gpio_WriteChannel(Mcal_GpioChannelType channel, Mcal_GpioLevelType level);
Mcal_GpioLevelType Mcal_Gpio_ReadChannel(Mcal_GpioChannelType channel);
Mcal_GpioLevelType Mcal_Gpio_ToggleChannel(Mcal_GpioChannelType channel);

#endif /* FIRMWARE_MCAL_GPIO_H */
