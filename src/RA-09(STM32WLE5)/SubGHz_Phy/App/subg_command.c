/**
  * @file    subg_command.c
  * @brief   UART RX bridge to the RA-09 modem.
  */
#include "platform.h"
#include "subg_command.h"
#include "ra09_modem.h"
#include "stm32_adv_trace.h"

static void (*NotifyCb)(void) = NULL;
static void modem_uart_rx_callback(uint8_t *rxChar, uint16_t size, uint8_t error);

void CMD_Init(void (*CmdProcessNotify)(void))
{
  UTIL_ADV_TRACE_StartRxProcess(modem_uart_rx_callback);
  if (CmdProcessNotify != NULL)
  {
    NotifyCb = CmdProcessNotify;
  }
}

void CMD_Process(void)
{
  RA09_ModemCommandProcess();
}

static void modem_uart_rx_callback(uint8_t *rxChar, uint16_t size, uint8_t error)
{
  (void)size;
  (void)error;
  RA09_ModemOnUartByte(*rxChar);
  if (NotifyCb != NULL)
  {
    NotifyCb();
  }
}
