#include <stdio.h>
#include <string.h>
#include "at_modem.h"
#include "radio.h"
#include "sx126x-board.h"
#include "timer.h"
#include "tremo_flash.h"
#include "tremo_gpio.h"
#include "tremo_uart.h"

#define CFG_MAGIC                  0x52413038UL
#define CFG_VERSION                1
#define INVALID_CHANNEL            0xFF
#define TX_TIMEOUT_MS              60000UL
#define RX_SYMBOL_TIMEOUT          0

#define LED_GPIO                   GPIOA
#define LED_PIN                    GPIO_PIN_4
#define LED_ON_MS                  80UL
#define LED_IDLE_OFF_MS            500UL
#define LED_RX_OFF_MS              180UL
#define LED_TX_OFF_MS              120UL
#define LED_SLEEP_OFF_MS           1200UL
#define LED_EVENT_PULSE_MS         120UL

#define ERR_UNKNOWN                1
#define ERR_BAD_PARAM              2
#define ERR_RANGE                  3
#define ERR_BUSY                   4
#define ERR_SLEEP                  5
#define ERR_PAYLOAD                6
#define ERR_OVERFLOW               7
#define ERR_NO_PACKET              8

static const uint32_t k_channels[] = {
    433000000UL,
    433175000UL,
    433350000UL,
    433525000UL,
    433700000UL,
    433875000UL
};

static volatile uint8_t s_rx_ring[RA08_UART_RX_RING_SIZE];
static volatile uint16_t s_rx_head;
static volatile uint16_t s_rx_tail;
static volatile bool s_rx_overflow;

static char s_line[RA08_AT_LINE_SIZE];
static uint16_t s_line_len;

static ra08_modem_config_t s_cfg;
static RadioEvents_t s_radio_events;
static bool s_radio_ready;
static bool s_rx_enabled;
static bool s_sleeping;
static bool s_tx_busy;
static bool s_led_on;
static TimerTime_t s_led_next_ms;
static TimerTime_t s_led_pulse_end_ms;

static volatile bool s_evt_tx_done;
static volatile bool s_evt_tx_timeout;
static volatile bool s_evt_rx_done;
static volatile bool s_evt_rx_timeout;
static volatile bool s_evt_rx_error;

static uint8_t s_rx_payload[RA08_MAX_PAYLOAD_SIZE];
static uint16_t s_rx_size;
static int16_t s_rx_rssi;
static int8_t s_rx_snr;
static bool s_last_pkt_valid;

static void on_tx_done(void);
static void on_tx_timeout(void);
static void on_rx_done(uint8_t* payload, uint16_t size, int16_t rssi, int8_t snr);
static void on_rx_timeout(void);
static void on_rx_error(void);

static void led_set(bool on)
{
    gpio_write(LED_GPIO, LED_PIN, on ? GPIO_LEVEL_HIGH : GPIO_LEVEL_LOW);
    s_led_on = on;
}

static void led_init(void)
{
    gpio_set_iomux(LED_GPIO, LED_PIN, 0);
    gpio_init(LED_GPIO, LED_PIN, GPIO_MODE_OUTPUT_PP_LOW);
    s_led_on = false;
    s_led_pulse_end_ms = 0;
    s_led_next_ms = TimerGetCurrentTime() + 100UL;
}

static uint32_t led_off_time_ms(void)
{
    if (s_sleeping) {
        return LED_SLEEP_OFF_MS;
    }
    if (s_tx_busy) {
        return LED_TX_OFF_MS;
    }
    if (s_rx_enabled) {
        return LED_RX_OFF_MS;
    }
    return LED_IDLE_OFF_MS;
}

static void led_pulse(void)
{
    TimerTime_t now = TimerGetCurrentTime();

    s_led_pulse_end_ms = now + LED_EVENT_PULSE_MS;
    s_led_next_ms = s_led_pulse_end_ms + LED_ON_MS;
    led_set(true);
}

static void led_process(void)
{
    TimerTime_t now = TimerGetCurrentTime();

    if (s_led_pulse_end_ms != 0) {
        if (now < s_led_pulse_end_ms) {
            return;
        }
        s_led_pulse_end_ms = 0;
        led_set(false);
        return;
    }

    if (now < s_led_next_ms) {
        return;
    }

    if (s_led_on) {
        led_set(false);
        s_led_next_ms = now + led_off_time_ms();
    } else {
        led_set(true);
        s_led_next_ms = now + LED_ON_MS;
    }
}

static uint32_t cfg_crc32(const uint8_t* data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFFUL;

    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; bit++) {
            if (crc & 1) {
                crc = (crc >> 1) ^ 0xEDB88320UL;
            } else {
                crc >>= 1;
            }
        }
    }

    return ~crc;
}

static void cfg_finalize(ra08_modem_config_t* cfg)
{
    cfg->magic = CFG_MAGIC;
    cfg->version = CFG_VERSION;
    cfg->length = sizeof(*cfg);
    cfg->crc32 = 0;
    cfg->crc32 = cfg_crc32((const uint8_t*)cfg, sizeof(*cfg) - sizeof(cfg->crc32));
}

static void cfg_defaults(ra08_modem_config_t* cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    cfg->freq_hz = RA08_DEFAULT_FREQ_HZ;
    cfg->channel = 0;
    cfg->tx_power_dbm = RA08_DEFAULT_POWER_DBM;
    cfg->sf = RA08_DEFAULT_SF;
    cfg->bw = RA08_DEFAULT_BW;
    cfg->cr = RA08_DEFAULT_CR;
    cfg->preamble = RA08_DEFAULT_PREAMBLE;
    cfg->crc_on = 1;
    cfg->fixed_len = 0;
    cfg->iq_inverted = 0;
    cfg->public_network = 0;
    cfg_finalize(cfg);
}

static bool cfg_is_valid(const ra08_modem_config_t* cfg)
{
    ra08_modem_config_t tmp;

    if (cfg->magic != CFG_MAGIC || cfg->version != CFG_VERSION || cfg->length != sizeof(*cfg)) {
        return false;
    }

    memcpy(&tmp, cfg, sizeof(tmp));
    uint32_t crc = tmp.crc32;
    tmp.crc32 = 0;

    return crc == cfg_crc32((const uint8_t*)&tmp, sizeof(tmp) - sizeof(tmp.crc32));
}

static void cfg_save(void)
{
    ra08_modem_config_t tmp;

    memcpy(&tmp, &s_cfg, sizeof(tmp));
    cfg_finalize(&tmp);
    flash_erase_page(RA08_CONFIG_FLASH_ADDR);
    flash_program_bytes(RA08_CONFIG_FLASH_ADDR, (uint8_t*)&tmp, sizeof(tmp));
    memcpy(&s_cfg, &tmp, sizeof(s_cfg));
}

static void cfg_load(void)
{
    memcpy(&s_cfg, (const void*)RA08_CONFIG_FLASH_ADDR, sizeof(s_cfg));
    if (!cfg_is_valid(&s_cfg)) {
        cfg_defaults(&s_cfg);
        cfg_save();
    }
}

static char ascii_upper(char c)
{
    if (c >= 'a' && c <= 'z') {
        return (char)(c - ('a' - 'A'));
    }
    return c;
}

static bool str_ieq(const char* a, const char* b)
{
    while (*a && *b) {
        if (ascii_upper(*a) != ascii_upper(*b)) {
            return false;
        }
        a++;
        b++;
    }
    return *a == '\0' && *b == '\0';
}

static bool str_istarts(const char* s, const char* prefix)
{
    while (*prefix) {
        if (ascii_upper(*s) != ascii_upper(*prefix)) {
            return false;
        }
        s++;
        prefix++;
    }
    return true;
}

static char* trim(char* s)
{
    while (*s == ' ' || *s == '\t') {
        s++;
    }

    char* end = s + strlen(s);
    while (end > s && (end[-1] == ' ' || end[-1] == '\t')) {
        *--end = '\0';
    }

    return s;
}

static bool parse_u32(const char* s, uint32_t* out)
{
    uint32_t value = 0;
    bool any = false;

    while (*s == ' ' || *s == '\t') {
        s++;
    }
    if (*s == '\0') {
        return false;
    }

    while (*s >= '0' && *s <= '9') {
        uint32_t digit = (uint32_t)(*s - '0');
        if (value > (0xFFFFFFFFUL - digit) / 10UL) {
            return false;
        }
        value = value * 10UL + digit;
        any = true;
        s++;
    }

    while (*s == ' ' || *s == '\t') {
        s++;
    }

    if (*s != '\0' || !any) {
        return false;
    }

    *out = value;
    return true;
}

static bool parse_i32(const char* s, int32_t* out)
{
    bool neg = false;
    uint32_t value = 0;

    while (*s == ' ' || *s == '\t') {
        s++;
    }
    if (*s == '-') {
        neg = true;
        s++;
    } else if (*s == '+') {
        s++;
    }

    if (!parse_u32(s, &value)) {
        return false;
    }
    if (!neg && value > 2147483647UL) {
        return false;
    }
    if (neg && value > 2147483648UL) {
        return false;
    }

    *out = neg ? -(int32_t)value : (int32_t)value;
    return true;
}

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    c = ascii_upper(c);
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

static bool parse_hex_payload(const char* s, uint8_t* out, uint16_t* out_len)
{
    uint16_t len = 0;
    int high = -1;

    while (*s) {
        int n = hex_nibble(*s++);
        if (n < 0) {
            return false;
        }

        if (high < 0) {
            high = n;
        } else {
            if (len >= RA08_MAX_PAYLOAD_SIZE) {
                return false;
            }
            out[len++] = (uint8_t)((high << 4) | n);
            high = -1;
        }
    }

    if (high >= 0 || len == 0) {
        return false;
    }

    *out_len = len;
    return true;
}

static void print_hex(const uint8_t* data, uint16_t len)
{
    static const char hex[] = "0123456789ABCDEF";

    for (uint16_t i = 0; i < len; i++) {
        uart_send_data(CONFIG_DEBUG_UART, (uint8_t)hex[data[i] >> 4]);
        uart_send_data(CONFIG_DEBUG_UART, (uint8_t)hex[data[i] & 0x0F]);
    }
}

static void rsp_ok(void)
{
    printf("\r\nOK\r\n");
}

static const char* error_text(uint8_t err)
{
    switch (err) {
    case ERR_UNKNOWN:
        return "UNKNOWN_COMMAND";
    case ERR_BAD_PARAM:
        return "BAD_PARAMETER";
    case ERR_RANGE:
        return "OUT_OF_RANGE";
    case ERR_BUSY:
        return "RADIO_BUSY";
    case ERR_SLEEP:
        return "RADIO_SLEEPING (send AT+WAKE)";
    case ERR_PAYLOAD:
        return "BAD_PAYLOAD";
    case ERR_OVERFLOW:
        return "UART_OVERFLOW";
    case ERR_NO_PACKET:
        return "NO_PACKET";
    default:
        return "INTERNAL";
    }
}

static void rsp_error(uint8_t err)
{
    printf("\r\n#ERROR: %s\r\n", error_text(err));
}

static void radio_apply_config(void)
{
    if (!s_radio_ready) {
        s_radio_events.TxDone = on_tx_done;
        s_radio_events.TxTimeout = on_tx_timeout;
        s_radio_events.RxDone = on_rx_done;
        s_radio_events.RxTimeout = on_rx_timeout;
        s_radio_events.RxError = on_rx_error;
        s_radio_events.FhssChangeChannel = 0;
        s_radio_events.CadDone = 0;

        Radio.Init(&s_radio_events);
        s_radio_ready = true;
    }

    Radio.SetPublicNetwork(s_cfg.public_network ? true : false);
    Radio.SetChannel(s_cfg.freq_hz);
    Radio.SetTxConfig(MODEM_LORA, s_cfg.tx_power_dbm, 0, s_cfg.bw, s_cfg.sf, s_cfg.cr,
        s_cfg.preamble, s_cfg.fixed_len ? true : false, s_cfg.crc_on ? true : false,
        false, 0, s_cfg.iq_inverted ? true : false, TX_TIMEOUT_MS);
    Radio.SetRxConfig(MODEM_LORA, s_cfg.bw, s_cfg.sf, s_cfg.cr, 0, s_cfg.preamble,
        RX_SYMBOL_TIMEOUT, s_cfg.fixed_len ? true : false, 0, s_cfg.crc_on ? true : false,
        false, 0, s_cfg.iq_inverted ? true : false, true);
    Radio.SetMaxPayloadLength(MODEM_LORA, RA08_MAX_PAYLOAD_SIZE);
}

static void radio_start_rx(void)
{
    radio_apply_config();
    Radio.Rx(0);
}

static void radio_reconfigure_idle(void)
{
    if (s_sleeping || s_tx_busy) {
        return;
    }

    Radio.Standby();
    radio_apply_config();
    if (s_rx_enabled) {
        Radio.Rx(0);
    }
}

static void config_set_freq(uint32_t freq_hz, uint8_t channel)
{
    s_cfg.freq_hz = freq_hz;
    s_cfg.channel = channel;
    cfg_save();
    radio_reconfigure_idle();
}

static uint32_t bw_to_hz(uint8_t bw)
{
    switch (bw) {
    case 0:
        return 125000UL;
    case 1:
        return 250000UL;
    case 2:
        return 500000UL;
    default:
        return 0;
    }
}

static bool parse_bw(const char* s, uint8_t* bw, bool* out_of_range)
{
    uint32_t value;

    *out_of_range = false;

    if (str_ieq(s, "125K") || str_ieq(s, "125KHZ")) {
        *bw = 0;
        return true;
    }
    if (str_ieq(s, "250K") || str_ieq(s, "250KHZ")) {
        *bw = 1;
        return true;
    }
    if (str_ieq(s, "500K") || str_ieq(s, "500KHZ")) {
        *bw = 2;
        return true;
    }
    if (!parse_u32(s, &value)) {
        return false;
    }

    if (value == 0 || value == 125000UL || value == 125UL) {
        *bw = 0;
        return true;
    }
    if (value == 1 || value == 250000UL || value == 250UL) {
        *bw = 1;
        return true;
    }
    if (value == 2 || value == 500000UL || value == 500UL) {
        *bw = 2;
        return true;
    }

    *out_of_range = true;
    return false;
}

static bool parse_cr(const char* s, uint8_t* cr, bool* out_of_range)
{
    uint32_t value;

    *out_of_range = false;

    if (str_ieq(s, "4/5")) {
        *cr = 1;
        return true;
    }
    if (str_ieq(s, "4/6")) {
        *cr = 2;
        return true;
    }
    if (str_ieq(s, "4/7")) {
        *cr = 3;
        return true;
    }
    if (str_ieq(s, "4/8")) {
        *cr = 4;
        return true;
    }
    if (!parse_u32(s, &value)) {
        return false;
    }
    if (value < 1 || value > 4) {
        *out_of_range = true;
        return false;
    }

    *cr = (uint8_t)value;
    return true;
}

static const char* cr_to_text(uint8_t cr)
{
    switch (cr) {
    case 1:
        return "4/5";
    case 2:
        return "4/6";
    case 3:
        return "4/7";
    case 4:
        return "4/8";
    default:
        return "?";
    }
}

static void print_help(void)
{
    printf("\r\nRA08 AT commands:\r\n");
    printf("AT\r\n");
    printf("AT?\r\n");
    printf("AT+?\r\n");
    printf("AT+HELP\r\n");
    printf("AT+VERSION?\r\n");
    printf("AT+CFG?\r\n");
    printf("AT+STATUS?\r\n");
    printf("AT+DEFAULT\r\n");
    printf("AT+FREQ?\r\n");
    printf("AT+FREQ=<410000000..525000000>\r\n");
    printf("AT+CHAN?\r\n");
    printf("AT+CHAN=<n>\r\n");
    printf("AT+PWR?\r\n");
    printf("AT+PWR=<2..22>\r\n");
    printf("AT+SF?\r\n");
    printf("AT+SF=<5..12>\r\n");
    printf("AT+BW?\r\n");
    printf("AT+BW=<0|1|2|125000|250000|500000>\r\n");
    printf("AT+CR?\r\n");
    printf("AT+CR=<1..4|4/5..4/8>\r\n");
    printf("AT+RX?\r\n");
    printf("AT+RX=ON\r\n");
    printf("AT+RX=OFF\r\n");
    printf("AT+SEND=<hex>\r\n");
    printf("AT+LASTPKT?\r\n");
    printf("AT+SLEEP?\r\n");
    printf("AT+SLEEP\r\n");
    printf("AT+WAKE\r\n");
    printf("+RX:<rssi>,<snr>,<len>,<hex>\r\n");
    printf("CHAN=-1 means manual frequency set with AT+FREQ\r\n");
    rsp_ok();
}

static void print_cfg(void)
{
    int chan = (s_cfg.channel == INVALID_CHANNEL) ? -1 : (int)s_cfg.channel;

    printf("\r\n+CFG:FREQ=%lu,CHAN=%d,PWR=%d,SF=%u,BW=%lu,CR=%s,RX=%s,SLEEP=%u,MAXPL=%u\r\n",
        s_cfg.freq_hz, chan, s_cfg.tx_power_dbm, s_cfg.sf, bw_to_hz(s_cfg.bw),
        cr_to_text(s_cfg.cr), s_rx_enabled ? "ON" : "OFF", s_sleeping ? 1 : 0,
        RA08_MAX_PAYLOAD_SIZE);
    rsp_ok();
}

static void print_status(void)
{
    int chan = (s_cfg.channel == INVALID_CHANNEL) ? -1 : (int)s_cfg.channel;

    printf("\r\n+STATUS:VERSION=%s,FREQ=%lu,CHAN=%d,PWR=%d,SF=%u,BW=%lu,CR=%s,RX=%s,SLEEP=%u,TXBUSY=%u,LASTPKT=%u\r\n",
        RA08_MODEM_VERSION, s_cfg.freq_hz, chan, s_cfg.tx_power_dbm, s_cfg.sf,
        bw_to_hz(s_cfg.bw), cr_to_text(s_cfg.cr), s_rx_enabled ? "ON" : "OFF",
        s_sleeping ? 1 : 0, s_tx_busy ? 1 : 0, s_last_pkt_valid ? 1 : 0);
    rsp_ok();
}

static void print_last_pkt(void)
{
    if (!s_last_pkt_valid) {
        printf("\r\n+LASTPKT:NONE\r\n");
        rsp_ok();
        return;
    }

    printf("\r\n+LASTPKT:%d,%d,%u,", s_rx_rssi, s_rx_snr, s_rx_size);
    print_hex(s_rx_payload, s_rx_size);
    printf("\r\n");
    rsp_ok();
}

static void cmd_send(const char* arg)
{
    uint8_t tx_buf[RA08_MAX_PAYLOAD_SIZE];
    uint16_t tx_len = 0;

    if (s_sleeping) {
        rsp_error(ERR_SLEEP);
        return;
    }
    if (s_tx_busy) {
        rsp_error(ERR_BUSY);
        return;
    }
    if (!parse_hex_payload(arg, tx_buf, &tx_len)) {
        rsp_error(ERR_PAYLOAD);
        return;
    }

    Radio.Standby();
    radio_apply_config();
    s_tx_busy = true;
    Radio.Send(tx_buf, (uint8_t)tx_len);
    rsp_ok();
}

static void cmd_dispatch(char* line)
{
    uint32_t value;
    int32_t ivalue;
    char* arg;

    line = trim(line);
    if (*line == '\0') {
        return;
    }

    if (str_ieq(line, "AT")) {
        rsp_ok();
    } else if (str_ieq(line, "AT+HELP") || str_ieq(line, "AT?") || str_ieq(line, "AT+?")) {
        print_help();
    } else if (str_ieq(line, "AT+VERSION?")) {
        printf("\r\n+VERSION:%s\r\n", RA08_MODEM_VERSION);
        rsp_ok();
    } else if (str_ieq(line, "AT+CFG?")) {
        print_cfg();
    } else if (str_ieq(line, "AT+STATUS?")) {
        print_status();
    } else if (str_ieq(line, "AT+DEFAULT")) {
        if (s_tx_busy) {
            rsp_error(ERR_BUSY);
            return;
        }
        cfg_defaults(&s_cfg);
        cfg_save();
        s_rx_enabled = false;
        s_sleeping = false;
        radio_apply_config();
        Radio.Standby();
        rsp_ok();
    } else if (str_ieq(line, "AT+FREQ?")) {
        printf("\r\n+FREQ:%lu\r\n", s_cfg.freq_hz);
        rsp_ok();
    } else if (str_istarts(line, "AT+FREQ=")) {
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
            return;
        }
        arg = trim(line + 8);
        if (!parse_u32(arg, &value)) {
            rsp_error(ERR_BAD_PARAM);
        } else if (value < RA08_FREQ_MIN_HZ || value > RA08_FREQ_MAX_HZ) {
            rsp_error(ERR_RANGE);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            config_set_freq(value, INVALID_CHANNEL);
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+CHAN?")) {
        int chan = (s_cfg.channel == INVALID_CHANNEL) ? -1 : (int)s_cfg.channel;
        if (chan < 0) {
            printf("\r\n+CHAN:-1 (manual frequency)\r\n");
        } else {
            printf("\r\n+CHAN:%d\r\n", chan);
        }
        rsp_ok();
    } else if (str_istarts(line, "AT+CHAN=")) {
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
            return;
        }
        arg = trim(line + 8);
        if (!parse_u32(arg, &value)) {
            rsp_error(ERR_BAD_PARAM);
        } else if (value >= (sizeof(k_channels) / sizeof(k_channels[0]))) {
            rsp_error(ERR_RANGE);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            config_set_freq(k_channels[value], (uint8_t)value);
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+PWR?")) {
        printf("\r\n+PWR:%d\r\n", s_cfg.tx_power_dbm);
        rsp_ok();
    } else if (str_istarts(line, "AT+PWR=")) {
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
            return;
        }
        arg = trim(line + 7);
        if (!parse_i32(arg, &ivalue)) {
            rsp_error(ERR_BAD_PARAM);
        } else if (ivalue < RA08_POWER_MIN_DBM || ivalue > RA08_POWER_MAX_DBM) {
            rsp_error(ERR_RANGE);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_cfg.tx_power_dbm = (int8_t)ivalue;
            cfg_save();
            radio_reconfigure_idle();
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+SF?")) {
        printf("\r\n+SF:%u\r\n", s_cfg.sf);
        rsp_ok();
    } else if (str_istarts(line, "AT+SF=")) {
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
            return;
        }
        arg = trim(line + 6);
        if (!parse_u32(arg, &value)) {
            rsp_error(ERR_BAD_PARAM);
        } else if (value < 5 || value > 12) {
            rsp_error(ERR_RANGE);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_cfg.sf = (uint8_t)value;
            cfg_save();
            radio_reconfigure_idle();
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+BW?")) {
        printf("\r\n+BW:%lu\r\n", bw_to_hz(s_cfg.bw));
        rsp_ok();
    } else if (str_istarts(line, "AT+BW=")) {
        uint8_t bw;
        bool out_of_range;
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
            return;
        }
        arg = trim(line + 6);
        if (!parse_bw(arg, &bw, &out_of_range)) {
            rsp_error(out_of_range ? ERR_RANGE : ERR_BAD_PARAM);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_cfg.bw = bw;
            cfg_save();
            radio_reconfigure_idle();
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+CR?")) {
        printf("\r\n+CR:%s\r\n", cr_to_text(s_cfg.cr));
        rsp_ok();
    } else if (str_istarts(line, "AT+CR=")) {
        uint8_t cr;
        bool out_of_range;
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
            return;
        }
        arg = trim(line + 6);
        if (!parse_cr(arg, &cr, &out_of_range)) {
            rsp_error(out_of_range ? ERR_RANGE : ERR_BAD_PARAM);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_cfg.cr = cr;
            cfg_save();
            radio_reconfigure_idle();
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+RX?")) {
        printf("\r\n+RX:%s\r\n", s_rx_enabled ? "ON" : "OFF");
        rsp_ok();
    } else if (str_ieq(line, "AT+RX=ON")) {
        if (s_sleeping) {
            rsp_error(ERR_SLEEP);
        } else if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_rx_enabled = true;
            radio_start_rx();
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+RX=OFF")) {
        if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_rx_enabled = false;
            if (!s_sleeping) {
                Radio.Standby();
            }
            rsp_ok();
        }
    } else if (str_istarts(line, "AT+SEND=")) {
        cmd_send(trim(line + 8));
    } else if (str_ieq(line, "AT+LASTPKT?")) {
        print_last_pkt();
    } else if (str_ieq(line, "AT+SLEEP?")) {
        printf("\r\n+SLEEP:%u\r\n", s_sleeping ? 1 : 0);
        rsp_ok();
    } else if (str_ieq(line, "AT+SLEEP")) {
        if (s_tx_busy) {
            rsp_error(ERR_BUSY);
        } else {
            s_rx_enabled = false;
            s_sleeping = true;
            Radio.Sleep();
            rsp_ok();
        }
    } else if (str_ieq(line, "AT+WAKE")) {
        s_sleeping = false;
        radio_apply_config();
        Radio.Standby();
        rsp_ok();
    } else {
        rsp_error(ERR_UNKNOWN);
    }
}

static bool ring_pop(uint8_t* out)
{
    if (s_rx_head == s_rx_tail) {
        return false;
    }

    *out = s_rx_ring[s_rx_tail];
    s_rx_tail = (uint16_t)((s_rx_tail + 1) % RA08_UART_RX_RING_SIZE);
    return true;
}

static void process_uart(void)
{
    uint8_t byte;

    if (s_rx_overflow) {
        s_rx_overflow = false;
        s_line_len = 0;
        rsp_error(ERR_OVERFLOW);
    }

    while (ring_pop(&byte)) {
        if (byte == '\r' || byte == '\n') {
            if (s_line_len > 0) {
                s_line[s_line_len] = '\0';
                cmd_dispatch(s_line);
                s_line_len = 0;
            }
            continue;
        }

        if (s_line_len >= (RA08_AT_LINE_SIZE - 1)) {
            s_line_len = 0;
            rsp_error(ERR_OVERFLOW);
            continue;
        }

        s_line[s_line_len++] = (char)byte;
    }
}

static void process_radio_events(void)
{
    Radio.IrqProcess();

    if (s_evt_rx_done) {
        s_evt_rx_done = false;
        printf("\r\n+RX:%d,%d,%u,", s_rx_rssi, s_rx_snr, s_rx_size);
        print_hex(s_rx_payload, s_rx_size);
        printf("\r\n");
        led_pulse();
        if (s_rx_enabled && !s_tx_busy && !s_sleeping) {
            Radio.Rx(0);
        }
    }

    if (s_evt_rx_error) {
        s_evt_rx_error = false;
        printf("\r\n+RXERROR\r\n");
        if (s_rx_enabled && !s_tx_busy && !s_sleeping) {
            Radio.Rx(0);
        }
    }

    if (s_evt_rx_timeout) {
        s_evt_rx_timeout = false;
        printf("\r\n+RXTIMEOUT\r\n");
        if (s_rx_enabled && !s_tx_busy && !s_sleeping) {
            Radio.Rx(0);
        }
    }

    if (s_evt_tx_done) {
        s_evt_tx_done = false;
        s_tx_busy = false;
        printf("\r\n+TXDONE\r\n");
        led_pulse();
        if (s_rx_enabled && !s_sleeping) {
            radio_start_rx();
        } else {
            Radio.Standby();
        }
    }

    if (s_evt_tx_timeout) {
        s_evt_tx_timeout = false;
        s_tx_busy = false;
        printf("\r\n+TXTIMEOUT\r\n");
        led_pulse();
        if (s_rx_enabled && !s_sleeping) {
            radio_start_rx();
        } else {
            Radio.Standby();
        }
    }
}

void ra08_modem_uart_rx_isr(uint8_t byte)
{
    uint16_t next = (uint16_t)((s_rx_head + 1) % RA08_UART_RX_RING_SIZE);

    if (next == s_rx_tail) {
        s_rx_overflow = true;
        return;
    }

    s_rx_ring[s_rx_head] = byte;
    s_rx_head = next;
}

void ra08_modem_init(void)
{
    cfg_load();
    led_init();
    radio_apply_config();
    Radio.Standby();

    printf("\r\nRA-08 UART modem %s\r\n", RA08_MODEM_VERSION);
    printf("ready\r\n");
}

void ra08_modem_process(void)
{
    process_radio_events();
    process_uart();
    led_process();
}

static void on_tx_done(void)
{
    s_evt_tx_done = true;
}

static void on_tx_timeout(void)
{
    s_evt_tx_timeout = true;
}

static void on_rx_done(uint8_t* payload, uint16_t size, int16_t rssi, int8_t snr)
{
    if (size > RA08_MAX_PAYLOAD_SIZE) {
        size = RA08_MAX_PAYLOAD_SIZE;
    }
    memcpy(s_rx_payload, payload, size);
    s_rx_size = size;
    s_rx_rssi = rssi;
    s_rx_snr = snr;
    s_last_pkt_valid = true;
    s_evt_rx_done = true;
}

static void on_rx_timeout(void)
{
    s_evt_rx_timeout = true;
}

static void on_rx_error(void)
{
    s_evt_rx_error = true;
}
