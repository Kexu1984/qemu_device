#include "mcal.h"
#include "mcal_gpio.h"

Mcal_ReturnType Mcal_Init(void)
{
    return Mcal_Gpio_Init(0);
}
