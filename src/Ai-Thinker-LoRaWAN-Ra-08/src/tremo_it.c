#include "at_modem.h"
#include "timer.h"
#include "rtc-board.h"
#include "tremo_it.h"
#include "tremo_uart.h"

extern void RadioOnDioIrq(void);
extern void RtcOnIrq(void);

void NMI_Handler(void)
{
}

void HardFault_Handler(void)
{
    while (1) { }
}

void MemManage_Handler(void)
{
    while (1) { }
}

void BusFault_Handler(void)
{
    while (1) { }
}

void UsageFault_Handler(void)
{
    while (1) { }
}

void SVC_Handler(void)
{
}

void PendSV_Handler(void)
{
}

void SysTick_Handler(void)
{
}

void PWR_IRQHandler(void)
{
}

void LORA_IRQHandler(void)
{
    RadioOnDioIrq();
}

void RTC_IRQHandler(void)
{
    RtcOnIrq();
}

void UART0_IRQHandler(void)
{
    if (uart_get_interrupt_status(CONFIG_DEBUG_UART, UART_INTERRUPT_RX_DONE)) {
        uart_clear_interrupt(CONFIG_DEBUG_UART, UART_INTERRUPT_RX_DONE);
    }
    if (uart_get_interrupt_status(CONFIG_DEBUG_UART, UART_INTERRUPT_RX_TIMEOUT)) {
        uart_clear_interrupt(CONFIG_DEBUG_UART, UART_INTERRUPT_RX_TIMEOUT);
    }

    while (!uart_get_flag_status(CONFIG_DEBUG_UART, UART_FLAG_RX_FIFO_EMPTY)) {
        ra08_modem_uart_rx_isr(uart_receive_data(CONFIG_DEBUG_UART));
    }
}
