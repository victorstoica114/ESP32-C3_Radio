#include <stdio.h>
#include "at_modem.h"
#include "delay.h"
#include "timer.h"
#include "rtc-board.h"
#include "tremo_delay.h"
#include "tremo_gpio.h"
#include "tremo_pwr.h"
#include "tremo_rcc.h"
#include "tremo_uart.h"

static void uart0_init(void)
{
    gpio_set_iomux(GPIOB, GPIO_PIN_0, 1);
    gpio_set_iomux(GPIOB, GPIO_PIN_1, 1);

    uart_config_t uart_config;
    uart_config_init(&uart_config);
    uart_config.baudrate = UART_BAUDRATE_115200;
    uart_config.mode = UART_MODE_TXRX;
    uart_config.fifo_mode = ENABLE;

    uart_init(CONFIG_DEBUG_UART, &uart_config);
    uart_set_rx_fifo_threshold(CONFIG_DEBUG_UART, UART_RX_FIFO_LEVEL_1_8);
    uart_config_interrupt(CONFIG_DEBUG_UART, UART_INTERRUPT_RX_DONE, ENABLE);
    uart_config_interrupt(CONFIG_DEBUG_UART, UART_INTERRUPT_RX_TIMEOUT, ENABLE);

    NVIC_SetPriority(UART0_IRQn, 2);
    NVIC_EnableIRQ(UART0_IRQn);

    uart_cmd(CONFIG_DEBUG_UART, ENABLE);
}

static void board_init(void)
{
    rcc_enable_oscillator(RCC_OSC_XO32K, true);

    rcc_enable_peripheral_clk(RCC_PERIPHERAL_UART0, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_GPIOA, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_GPIOB, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_GPIOC, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_GPIOD, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_PWR, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_RTC, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_SAC, true);
    rcc_enable_peripheral_clk(RCC_PERIPHERAL_LORA, true);

    delay_ms(100);
    pwr_xo32k_lpm_cmd(true);

    uart0_init();
    RtcInit();
}

int main(void)
{
    board_init();
    ra08_modem_init();

    while (1) {
        ra08_modem_process();
    }
}

#ifdef USE_FULL_ASSERT
void assert_failed(void* file, uint32_t line)
{
    (void)file;
    (void)line;

    while (1) { }
}
#endif
