#include "console_uart.h"
#include "mcal_uart.h"

static Mcal_BooleanType uart_channel_valid(Mcal_UartChannelType channel)
{
    return channel == MCAL_UART_CONSOLE ? MCAL_TRUE : MCAL_FALSE;
}

Mcal_ReturnType Mcal_Uart_Init(const Mcal_UartConfigType *config)
{
    if (config != 0 && uart_channel_valid(config->channel) == MCAL_FALSE) {
        return MCAL_NOT_OK;
    }

    console_uart_init();
    return MCAL_OK;
}

Mcal_ReturnType Mcal_Uart_WriteChar(Mcal_UartChannelType channel, char value)
{
    if (uart_channel_valid(channel) == MCAL_FALSE) {
        return MCAL_NOT_OK;
    }

    send_char(value);
    return MCAL_OK;
}

Mcal_ReturnType Mcal_Uart_WriteString(Mcal_UartChannelType channel, const char *value)
{
    if (uart_channel_valid(channel) == MCAL_FALSE || value == 0) {
        return MCAL_NOT_OK;
    }

    send_string(value);
    return MCAL_OK;
}

int Mcal_Uart_ReadLine(Mcal_UartChannelType channel, char *buf, int len)
{
    if (uart_channel_valid(channel) == MCAL_FALSE || buf == 0 || len <= 0) {
        return -1;
    }

    return recv_line(buf, len);
}
