#ifndef __AT_MODEM_H
#define __AT_MODEM_H

#include <stdbool.h>
#include <stdint.h>

#define RA08_MODEM_VERSION          "0.1.3"

#define RA08_FREQ_MIN_HZ            410000000UL
#define RA08_FREQ_MAX_HZ            525000000UL
#define RA08_DEFAULT_FREQ_HZ        433000000UL
#define RA08_DEFAULT_POWER_DBM      14
#define RA08_DEFAULT_SF             7
#define RA08_DEFAULT_BW             0
#define RA08_DEFAULT_CR             1
#define RA08_DEFAULT_PREAMBLE       8
#define RA08_POWER_MIN_DBM          2
#define RA08_POWER_MAX_DBM          22

#define RA08_MAX_PAYLOAD_SIZE       255
#define RA08_AT_LINE_SIZE           560
#define RA08_UART_RX_RING_SIZE      768
#define RA08_CONFIG_FLASH_ADDR      0x0801F000UL

typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t length;
    uint32_t freq_hz;
    uint8_t channel;
    int8_t tx_power_dbm;
    uint8_t sf;
    uint8_t bw;
    uint8_t cr;
    uint8_t preamble;
    uint8_t crc_on;
    uint8_t fixed_len;
    uint8_t iq_inverted;
    uint8_t public_network;
    uint8_t reserved[8];
    uint32_t crc32;
} ra08_modem_config_t;

void ra08_modem_init(void);
void ra08_modem_process(void);
void ra08_modem_uart_rx_isr(uint8_t byte);

#endif
