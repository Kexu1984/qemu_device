#ifndef FIRMWARE_MCAL_UART_H
#define FIRMWARE_MCAL_UART_H

#include <stdint.h>
#include "mcal_types.h"

#define MCAL_UART_CONSOLE 0U

typedef uint32_t Mcal_UartChannelType;

typedef struct {
    Mcal_UartChannelType channel;
    uint32_t baudrate;
} Mcal_UartConfigType;

Mcal_ReturnType Mcal_Uart_Init(const Mcal_UartConfigType *config);
Mcal_ReturnType Mcal_Uart_WriteChar(Mcal_UartChannelType channel, char value);
Mcal_ReturnType Mcal_Uart_WriteString(Mcal_UartChannelType channel, const char *value);
int Mcal_Uart_ReadLine(Mcal_UartChannelType channel, char *buf, int len);

#endif /* FIRMWARE_MCAL_UART_H */
