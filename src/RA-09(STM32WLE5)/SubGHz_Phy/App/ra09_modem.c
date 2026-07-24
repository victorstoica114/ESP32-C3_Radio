#include "ra09_modem.h"

#include "main.h"
#include "radio.h"
#include "radio_driver.h"
#include "stm32_seq.h"
#include "stm32_timer.h"
#include "timer_if.h"
#include "usart_if.h"
#include "utilities_def.h"

#include "stm32_tiny_vsnprintf.h"

#include <ctype.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define MODEM_VERSION                "0.1.0"
#define CONFIG_ADDRESS               0x0803F000UL
#define CONFIG_MAGIC                 0x52413039UL
#define CONFIG_VERSION               1U

#define UART_IDLE_MS                 15U
#define UART_MAX_MESSAGE             520U
#define MODEM_MAX_PAYLOAD            255U
#define LORA_SYMBOL_TIMEOUT          5U

#define EVENT_TX_DONE                (1UL << 0)
#define EVENT_TX_TIMEOUT             (1UL << 1)
#define EVENT_RX_DONE                (1UL << 2)
#define EVENT_RX_TIMEOUT             (1UL << 3)
#define EVENT_RX_ERROR               (1UL << 4)

typedef struct
{
  uint32_t magic;
  uint16_t version;
  uint16_t size;
  uint32_t frequency_hz;
  int8_t power_dbm;
  uint8_t spreading_factor;
  uint8_t bandwidth;
  uint8_t coding_rate;
  uint16_t preamble_length;
  uint8_t crc_enabled;
  uint8_t iq_inverted;
  uint8_t sync_word;
  uint8_t reserved[3];
  uint32_t crc32;
} modem_config_t;

typedef struct
{
  uint8_t data[MODEM_MAX_PAYLOAD];
  uint8_t length;
  int16_t rssi;
  int8_t snr;
  bool valid;
} received_packet_t;

static const modem_config_t default_config =
{
  .magic = CONFIG_MAGIC,
  .version = CONFIG_VERSION,
  .size = sizeof(modem_config_t),
  .frequency_hz = 433000000UL,
  .power_dbm = 14,
  .spreading_factor = 7,
  .bandwidth = 0,
  .coding_rate = 1,
  .preamble_length = 8,
  .crc_enabled = 1,
  .iq_inverted = 0,
  .sync_word = 0x12,
  .reserved = {0, 0, 0},
  .crc32 = 0
};

static modem_config_t config;
static RadioEvents_t radio_events;
static UTIL_TIMER_Object_t uart_idle_timer;

static uint8_t uart_buffer[UART_MAX_MESSAGE];
static uint8_t message_buffer[UART_MAX_MESSAGE + 1U];
static uint8_t hex_tx_buffer[MODEM_MAX_PAYLOAD];
static volatile uint16_t uart_length;
static volatile bool uart_message_ready;
static volatile bool uart_overflow;

static uint8_t rx_buffer[MODEM_MAX_PAYLOAD];
static volatile uint8_t rx_length;
static volatile int16_t rx_rssi;
static volatile int8_t rx_snr;

static received_packet_t last_packet;
static volatile uint32_t pending_events;
static bool rx_enabled = true;
static bool sleeping;
static bool tx_busy;
static bool debug_enabled;

static uint32_t crc32_update(uint32_t crc, uint8_t value)
{
  crc ^= value;
  for (uint8_t bit = 0; bit < 8U; bit++)
  {
    uint32_t mask = (uint32_t)-(int32_t)(crc & 1U);
    crc = (crc >> 1) ^ (0xEDB88320UL & mask);
  }
  return crc;
}

static uint32_t config_crc32(const modem_config_t *record)
{
  const uint8_t *bytes = (const uint8_t *)record;
  uint32_t crc = 0xFFFFFFFFUL;

  for (size_t index = 0; index < offsetof(modem_config_t, crc32); index++)
  {
    crc = crc32_update(crc, bytes[index]);
  }
  return ~crc;
}

static bool config_values_valid(const modem_config_t *record)
{
  return record->frequency_hz >= 410000000UL &&
         record->frequency_hz <= 525000000UL &&
         record->power_dbm >= -9 &&
         record->power_dbm <= 22 &&
         record->spreading_factor >= 5U &&
         record->spreading_factor <= 12U &&
         record->bandwidth <= 2U &&
         record->coding_rate >= 1U &&
         record->coding_rate <= 4U &&
         record->preamble_length >= 6U &&
         record->crc_enabled <= 1U &&
         record->iq_inverted <= 1U;
}

static bool config_load(void)
{
  const modem_config_t *stored = (const modem_config_t *)CONFIG_ADDRESS;

  if (stored->magic != CONFIG_MAGIC ||
      stored->version != CONFIG_VERSION ||
      stored->size != sizeof(modem_config_t) ||
      stored->crc32 != config_crc32(stored) ||
      !config_values_valid(stored))
  {
    config = default_config;
    return false;
  }

  config = *stored;
  return true;
}

static bool config_save(void)
{
  FLASH_EraseInitTypeDef erase = {0};
  uint32_t page_error = 0;
  uint32_t address = CONFIG_ADDRESS;
  uint64_t words[(sizeof(modem_config_t) + 7U) / 8U];

  config.magic = CONFIG_MAGIC;
  config.version = CONFIG_VERSION;
  config.size = sizeof(modem_config_t);
  config.crc32 = config_crc32(&config);

  memset(words, 0xFF, sizeof(words));
  memcpy(words, &config, sizeof(config));

  if (HAL_FLASH_Unlock() != HAL_OK)
  {
    return false;
  }

  erase.TypeErase = FLASH_TYPEERASE_PAGES;
  erase.Page = (CONFIG_ADDRESS - FLASH_BASE) / FLASH_PAGE_SIZE;
  erase.NbPages = 1;

  if (HAL_FLASHEx_Erase(&erase, &page_error) != HAL_OK)
  {
    HAL_FLASH_Lock();
    return false;
  }

  for (size_t index = 0; index < (sizeof(words) / sizeof(words[0])); index++)
  {
    if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_DOUBLEWORD, address, words[index]) != HAL_OK)
    {
      HAL_FLASH_Lock();
      return false;
    }
    address += 8U;
  }

  HAL_FLASH_Lock();
  return true;
}

static void uart_write(const void *data, uint16_t length)
{
  if (length > 0U)
  {
    vcom_Trace((uint8_t *)data, length);
  }
}

static void uart_text(const char *text)
{
  uart_write(text, (uint16_t)strlen(text));
}

static void uart_printf(const char *format, ...)
{
  char output[256];
  va_list args;
  int length;

  va_start(args, format);
  length = tiny_vsnprintf_like(output, sizeof(output), format, args);
  va_end(args);

  if (length > 0)
  {
    uart_write(output, (uint16_t)length);
  }
}

static void reply_ok(void)
{
  uart_text("OK\r\n");
}

static void reply_error(const char *reason)
{
  uart_printf("#ERROR: %s\r\n", reason);
}

static void schedule_command_task(void)
{
  UTIL_SEQ_SetTask(1UL << CFG_SEQ_Task_Vcom, CFG_SEQ_Prio_1);
}

static void schedule_radio_task(void)
{
  UTIL_SEQ_SetTask(1UL << CFG_SEQ_Task_LoraProcess, CFG_SEQ_Prio_0);
}

static void set_event(uint32_t event)
{
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  pending_events |= event;
  __set_PRIMASK(primask);
  schedule_radio_task();
}

static uint32_t take_events(void)
{
  uint32_t primask = __get_PRIMASK();
  uint32_t events;

  __disable_irq();
  events = pending_events;
  pending_events = 0;
  __set_PRIMASK(primask);
  return events;
}

static void on_tx_done(void)
{
  set_event(EVENT_TX_DONE);
}

static void on_tx_timeout(void)
{
  set_event(EVENT_TX_TIMEOUT);
}

static void on_rx_done(uint8_t *payload, uint16_t size, int16_t rssi, int8_t snr)
{
  if (size > MODEM_MAX_PAYLOAD)
  {
    size = MODEM_MAX_PAYLOAD;
  }

  memcpy(rx_buffer, payload, size);
  rx_length = (uint8_t)size;
  rx_rssi = rssi;
  rx_snr = snr;
  set_event(EVENT_RX_DONE);
}

static void on_rx_timeout(void)
{
  set_event(EVENT_RX_TIMEOUT);
}

static void on_rx_error(void)
{
  set_event(EVENT_RX_ERROR);
}

static void radio_apply_config(void)
{
  Radio.SetChannel(config.frequency_hz);
  Radio.SetTxConfig(MODEM_LORA,
                    config.power_dbm,
                    0,
                    config.bandwidth,
                    config.spreading_factor,
                    config.coding_rate,
                    config.preamble_length,
                    false,
                    config.crc_enabled != 0U,
                    false,
                    0,
                    config.iq_inverted != 0U,
                    60000);
  Radio.SetRxConfig(MODEM_LORA,
                    config.bandwidth,
                    config.spreading_factor,
                    config.coding_rate,
                    0,
                    config.preamble_length,
                    LORA_SYMBOL_TIMEOUT,
                    false,
                    0,
                    config.crc_enabled != 0U,
                    false,
                    0,
                    config.iq_inverted != 0U,
                    true);
  Radio.SetMaxPayloadLength(MODEM_LORA, MODEM_MAX_PAYLOAD);
  Radio.SetPublicNetwork(config.sync_word == 0x34U);
  SUBGRF_WriteRegister(REG_LR_SYNCWORD, (config.sync_word & 0xF0U) | 0x04U);
  SUBGRF_WriteRegister(REG_LR_SYNCWORD + 1U, (config.sync_word << 4) | 0x04U);
}

static void radio_resume_rx(void)
{
  if (!sleeping && !tx_busy && rx_enabled)
  {
    Radio.Rx(0);
  }
}

static bool radio_reconfigure(void)
{
  if (tx_busy)
  {
    return false;
  }

  if (!sleeping)
  {
    Radio.Standby();
    radio_apply_config();
    radio_resume_rx();
  }
  return true;
}

static bool config_commit(void)
{
  if (!radio_reconfigure())
  {
    return false;
  }
  return config_save();
}

static bool radio_send(const uint8_t *data, uint8_t length)
{
  radio_status_t status;

  if (sleeping)
  {
    reply_error("RADIO_SLEEPING");
    return false;
  }
  if (tx_busy)
  {
    reply_error("RADIO_BUSY");
    return false;
  }
  if (length == 0U)
  {
    reply_error("EMPTY_PAYLOAD");
    return false;
  }

  Radio.Standby();
  tx_busy = true;
  status = Radio.Send((uint8_t *)data, length);
  if (status != RADIO_STATUS_OK)
  {
    tx_busy = false;
    radio_resume_rx();
    reply_error("TX_START_FAILED");
    return false;
  }
  return true;
}

static bool string_equal_ci(const char *left, const char *right)
{
  while (*left != '\0' && *right != '\0')
  {
    if (toupper((unsigned char)*left) != toupper((unsigned char)*right))
    {
      return false;
    }
    left++;
    right++;
  }
  return *left == '\0' && *right == '\0';
}

static bool string_starts_ci(const char *text, const char *prefix)
{
  while (*prefix != '\0')
  {
    if (*text == '\0' ||
        toupper((unsigned char)*text) != toupper((unsigned char)*prefix))
    {
      return false;
    }
    text++;
    prefix++;
  }
  return true;
}

static bool parse_u32(const char *text, uint32_t minimum, uint32_t maximum, uint32_t *value)
{
  char *end;
  unsigned long parsed;

  if (*text == '\0')
  {
    return false;
  }
  parsed = strtoul(text, &end, 10);
  if (*end != '\0' || parsed < minimum || parsed > maximum)
  {
    return false;
  }
  *value = (uint32_t)parsed;
  return true;
}

static bool parse_i32(const char *text, int32_t minimum, int32_t maximum, int32_t *value)
{
  char *end;
  long parsed;

  if (*text == '\0')
  {
    return false;
  }
  parsed = strtol(text, &end, 10);
  if (*end != '\0' || parsed < minimum || parsed > maximum)
  {
    return false;
  }
  *value = (int32_t)parsed;
  return true;
}

static bool parse_on_off(const char *text, uint8_t *value)
{
  if (string_equal_ci(text, "ON") || string_equal_ci(text, "1"))
  {
    *value = 1U;
    return true;
  }
  if (string_equal_ci(text, "OFF") || string_equal_ci(text, "0"))
  {
    *value = 0U;
    return true;
  }
  return false;
}

static bool parse_bandwidth(const char *text, uint8_t *value)
{
  if (string_equal_ci(text, "0") || string_equal_ci(text, "125000") ||
      string_equal_ci(text, "125"))
  {
    *value = 0U;
    return true;
  }
  if (string_equal_ci(text, "1") || string_equal_ci(text, "250000") ||
      string_equal_ci(text, "250"))
  {
    *value = 1U;
    return true;
  }
  if (string_equal_ci(text, "2") || string_equal_ci(text, "500000") ||
      string_equal_ci(text, "500"))
  {
    *value = 2U;
    return true;
  }
  return false;
}

static uint32_t bandwidth_hz(void)
{
  static const uint32_t values[] = {125000UL, 250000UL, 500000UL};
  return values[config.bandwidth];
}

static bool parse_coding_rate(const char *text, uint8_t *value)
{
  if (string_equal_ci(text, "1") || string_equal_ci(text, "4/5"))
  {
    *value = 1U;
    return true;
  }
  if (string_equal_ci(text, "2") || string_equal_ci(text, "4/6"))
  {
    *value = 2U;
    return true;
  }
  if (string_equal_ci(text, "3") || string_equal_ci(text, "4/7"))
  {
    *value = 3U;
    return true;
  }
  if (string_equal_ci(text, "4") || string_equal_ci(text, "4/8"))
  {
    *value = 4U;
    return true;
  }
  return false;
}

static bool parse_hex_byte(const char *text, uint8_t *value)
{
  char *end;
  unsigned long parsed;

  if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X'))
  {
    text += 2;
  }
  if (*text == '\0' || strlen(text) > 2U)
  {
    return false;
  }

  parsed = strtoul(text, &end, 16);
  if (*end != '\0' || parsed > 0xFFU)
  {
    return false;
  }
  *value = (uint8_t)parsed;
  return true;
}

static void print_config(void)
{
  uart_printf("+CFG:FREQ=%u,PWR=%d,SF=%u,BW=%u,CR=4/%u,PREAMBLE=%u,"
              "CRC=%s,IQ=%s,SYNC=0x%02X,RX=%s,SLEEP=%u,DEBUG=%s\r\n",
              config.frequency_hz,
              config.power_dbm,
              config.spreading_factor,
              bandwidth_hz(),
              (uint32_t)config.coding_rate + 4U,
              config.preamble_length,
              config.crc_enabled ? "ON" : "OFF",
              config.iq_inverted ? "INVERTED" : "NORMAL",
              config.sync_word,
              rx_enabled ? "ON" : "OFF",
              sleeping ? 1U : 0U,
              debug_enabled ? "ON" : "OFF");
}

static void print_help(void)
{
  uart_text("AT, AT?, AT+HELP, AT+VERSION?, AT+CFG?, AT+STATUS?\r\n");
  uart_text("AT+FREQ=<410000000..525000000>, AT+PWR=<-9..22>\r\n");
  uart_text("AT+SF=<5..12>, AT+BW=<125000|250000|500000>\r\n");
  uart_text("AT+CR=<4/5|4/6|4/7|4/8>, AT+PREAMBLE=<6..65535>\r\n");
  uart_text("AT+CRC=<ON|OFF>, AT+IQ=<NORMAL|INVERTED>\r\n");
  uart_text("AT+SYNC=<00..FF>, AT+NETWORK=<PRIVATE|PUBLIC>\r\n");
  uart_text("AT+RX=<ON|OFF>\r\n");
  uart_text("AT+SEND=<hex>, AT+LASTPKT?, AT+RSSI?, AT+SNR?\r\n");
  uart_text("AT+DEBUG=<ON|OFF>, AT+SAVE, AT+DEFAULT, AT+SLEEP, AT+WAKE\r\n");
}

static bool apply_and_save(void)
{
  if (!config_commit())
  {
    reply_error(tx_busy ? "RADIO_BUSY" : "FLASH_WRITE_FAILED");
    return false;
  }
  reply_ok();
  return true;
}

static bool parse_hex_payload(const char *text, uint8_t *data, uint8_t *length)
{
  size_t chars = strlen(text);

  if (chars == 0U || (chars & 1U) != 0U || chars > (MODEM_MAX_PAYLOAD * 2U))
  {
    return false;
  }

  *length = (uint8_t)(chars / 2U);
  for (uint16_t index = 0; index < *length; index++)
  {
    char byte_text[3] = {text[index * 2U], text[index * 2U + 1U], '\0'};
    char *end;
    unsigned long parsed = strtoul(byte_text, &end, 16);
    if (*end != '\0')
    {
      return false;
    }
    data[index] = (uint8_t)parsed;
  }
  return true;
}

static void handle_command(char *command)
{
  uint32_t unsigned_value;
  int32_t signed_value;
  uint8_t byte_value;

  if (string_equal_ci(command, "AT"))
  {
    reply_ok();
  }
  else if (string_equal_ci(command, "AT?") ||
           string_equal_ci(command, "AT+?") ||
           string_equal_ci(command, "AT+HELP"))
  {
    print_help();
  }
  else if (string_equal_ci(command, "AT+VERSION?"))
  {
    uart_printf("+ID:RA09_AT_MODEM,%s,STM32WLE5CCU6\r\n", MODEM_VERSION);
  }
  else if (string_equal_ci(command, "AT+CFG?"))
  {
    print_config();
  }
  else if (string_equal_ci(command, "AT+STATUS?"))
  {
    uart_printf("+STATUS:RX=%s,SLEEP=%u,TXBUSY=%u,LASTPKT=%u\r\n",
                rx_enabled ? "ON" : "OFF",
                sleeping ? 1U : 0U,
                tx_busy ? 1U : 0U,
                last_packet.valid ? 1U : 0U);
  }
  else if (string_equal_ci(command, "AT+FREQ?"))
  {
    uart_printf("+FREQ:%u\r\n", config.frequency_hz);
  }
  else if (string_starts_ci(command, "AT+FREQ="))
  {
    if (!parse_u32(command + 8, 410000000UL, 525000000UL, &unsigned_value))
    {
      reply_error("INVALID_FREQUENCY");
      return;
    }
    config.frequency_hz = unsigned_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+PWR?"))
  {
    uart_printf("+PWR:%d\r\n", config.power_dbm);
  }
  else if (string_starts_ci(command, "AT+PWR="))
  {
    if (!parse_i32(command + 7, -9, 22, &signed_value))
    {
      reply_error("INVALID_POWER");
      return;
    }
    config.power_dbm = (int8_t)signed_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+SF?"))
  {
    uart_printf("+SF:%u\r\n", config.spreading_factor);
  }
  else if (string_starts_ci(command, "AT+SF="))
  {
    if (!parse_u32(command + 6, 5, 12, &unsigned_value))
    {
      reply_error("INVALID_SF");
      return;
    }
    config.spreading_factor = (uint8_t)unsigned_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+BW?"))
  {
    uart_printf("+BW:%u\r\n", bandwidth_hz());
  }
  else if (string_starts_ci(command, "AT+BW="))
  {
    if (!parse_bandwidth(command + 6, &byte_value))
    {
      reply_error("INVALID_BANDWIDTH");
      return;
    }
    config.bandwidth = byte_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+CR?"))
  {
    uart_printf("+CR:4/%u\r\n", (uint32_t)config.coding_rate + 4U);
  }
  else if (string_starts_ci(command, "AT+CR="))
  {
    if (!parse_coding_rate(command + 6, &byte_value))
    {
      reply_error("INVALID_CODING_RATE");
      return;
    }
    config.coding_rate = byte_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+PREAMBLE?"))
  {
    uart_printf("+PREAMBLE:%u\r\n", config.preamble_length);
  }
  else if (string_starts_ci(command, "AT+PREAMBLE="))
  {
    if (!parse_u32(command + 12, 6, 65535, &unsigned_value))
    {
      reply_error("INVALID_PREAMBLE");
      return;
    }
    config.preamble_length = (uint16_t)unsigned_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+CRC?"))
  {
    uart_printf("+CRC:%s\r\n", config.crc_enabled ? "ON" : "OFF");
  }
  else if (string_starts_ci(command, "AT+CRC="))
  {
    if (!parse_on_off(command + 7, &byte_value))
    {
      reply_error("INVALID_CRC");
      return;
    }
    config.crc_enabled = byte_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+IQ?"))
  {
    uart_printf("+IQ:%s\r\n", config.iq_inverted ? "INVERTED" : "NORMAL");
  }
  else if (string_starts_ci(command, "AT+IQ="))
  {
    const char *value = command + 6;
    if (string_equal_ci(value, "INVERTED") || string_equal_ci(value, "ON") ||
        string_equal_ci(value, "1"))
    {
      config.iq_inverted = 1U;
    }
    else if (string_equal_ci(value, "NORMAL") || string_equal_ci(value, "OFF") ||
             string_equal_ci(value, "0"))
    {
      config.iq_inverted = 0U;
    }
    else
    {
      reply_error("INVALID_IQ");
      return;
    }
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+NETWORK?"))
  {
    const char *network = "CUSTOM";
    if (config.sync_word == 0x12U)
    {
      network = "PRIVATE";
    }
    else if (config.sync_word == 0x34U)
    {
      network = "PUBLIC";
    }
    uart_printf("+NETWORK:%s\r\n", network);
  }
  else if (string_starts_ci(command, "AT+NETWORK="))
  {
    const char *value = command + 11;
    if (string_equal_ci(value, "PUBLIC"))
    {
      config.sync_word = 0x34U;
    }
    else if (string_equal_ci(value, "PRIVATE"))
    {
      config.sync_word = 0x12U;
    }
    else
    {
      reply_error("INVALID_NETWORK");
      return;
    }
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+SYNC?"))
  {
    uart_printf("+SYNC:0x%02X\r\n", config.sync_word);
  }
  else if (string_starts_ci(command, "AT+SYNC="))
  {
    if (!parse_hex_byte(command + 8, &byte_value))
    {
      reply_error("INVALID_SYNC_WORD");
      return;
    }
    config.sync_word = byte_value;
    apply_and_save();
  }
  else if (string_equal_ci(command, "AT+RX?"))
  {
    uart_printf("+RX:%s\r\n", rx_enabled ? "ON" : "OFF");
  }
  else if (string_equal_ci(command, "AT+RX=ON"))
  {
    if (sleeping)
    {
      reply_error("RADIO_SLEEPING");
      return;
    }
    rx_enabled = true;
    radio_resume_rx();
    reply_ok();
  }
  else if (string_equal_ci(command, "AT+RX=OFF"))
  {
    if (tx_busy)
    {
      reply_error("RADIO_BUSY");
      return;
    }
    rx_enabled = false;
    if (!sleeping)
    {
      Radio.Standby();
    }
    reply_ok();
  }
  else if (string_starts_ci(command, "AT+SEND="))
  {
    uint8_t length;
    if (!parse_hex_payload(command + 8, hex_tx_buffer, &length))
    {
      reply_error("INVALID_HEX_PAYLOAD");
      return;
    }
    if (radio_send(hex_tx_buffer, length))
    {
      reply_ok();
    }
  }
  else if (string_equal_ci(command, "AT+LASTPKT?"))
  {
    if (!last_packet.valid)
    {
      reply_error("NO_PACKET");
      return;
    }
    uart_printf("+LASTPKT:%d,%d,%u,",
                last_packet.rssi, last_packet.snr, last_packet.length);
    for (uint16_t index = 0; index < last_packet.length; index++)
    {
      uart_printf("%02X", last_packet.data[index]);
    }
    uart_text("\r\n");
  }
  else if (string_equal_ci(command, "AT+RSSI?"))
  {
    if (!last_packet.valid)
    {
      reply_error("NO_PACKET");
      return;
    }
    uart_printf("+RSSI:%d\r\n", last_packet.rssi);
  }
  else if (string_equal_ci(command, "AT+SNR?"))
  {
    if (!last_packet.valid)
    {
      reply_error("NO_PACKET");
      return;
    }
    uart_printf("+SNR:%d\r\n", last_packet.snr);
  }
  else if (string_equal_ci(command, "AT+DEBUG?"))
  {
    uart_printf("+DEBUG:%s\r\n", debug_enabled ? "ON" : "OFF");
  }
  else if (string_starts_ci(command, "AT+DEBUG="))
  {
    if (!parse_on_off(command + 9, &byte_value))
    {
      reply_error("INVALID_DEBUG");
      return;
    }
    debug_enabled = byte_value != 0U;
    reply_ok();
  }
  else if (string_equal_ci(command, "AT+SAVE"))
  {
    if (config_save())
    {
      reply_ok();
    }
    else
    {
      reply_error("FLASH_WRITE_FAILED");
    }
  }
  else if (string_equal_ci(command, "AT+DEFAULT"))
  {
    if (tx_busy)
    {
      reply_error("RADIO_BUSY");
      return;
    }
    config = default_config;
    sleeping = false;
    rx_enabled = true;
    debug_enabled = false;
    Radio.Standby();
    radio_apply_config();
    radio_resume_rx();
    if (config_save())
    {
      reply_ok();
    }
    else
    {
      reply_error("FLASH_WRITE_FAILED");
    }
  }
  else if (string_equal_ci(command, "AT+SLEEP"))
  {
    if (tx_busy)
    {
      reply_error("RADIO_BUSY");
      return;
    }
    Radio.Sleep();
    sleeping = true;
    reply_ok();
  }
  else if (string_equal_ci(command, "AT+WAKE"))
  {
    sleeping = false;
    Radio.Standby();
    radio_apply_config();
    radio_resume_rx();
    reply_ok();
  }
  else
  {
    reply_error("UNKNOWN_CMD");
  }
}

static bool buffer_is_at_command(const uint8_t *data, uint16_t length)
{
  if (length == 2U)
  {
    return toupper(data[0]) == 'A' && toupper(data[1]) == 'T';
  }
  return length >= 3U &&
         toupper(data[0]) == 'A' &&
         toupper(data[1]) == 'T' &&
         (data[2] == '+' || data[2] == '?');
}

static void uart_idle_timer_callback(void *context)
{
  (void)context;
  if (uart_length > 0U)
  {
    uart_message_ready = true;
    schedule_command_task();
  }
}

void RA09_ModemInit(void)
{
  (void)config_load();

  memset(&last_packet, 0, sizeof(last_packet));
  memset(&radio_events, 0, sizeof(radio_events));
  radio_events.TxDone = on_tx_done;
  radio_events.TxTimeout = on_tx_timeout;
  radio_events.RxDone = on_rx_done;
  radio_events.RxTimeout = on_rx_timeout;
  radio_events.RxError = on_rx_error;

  UTIL_TIMER_Create(&uart_idle_timer,
                    UART_IDLE_MS,
                    UTIL_TIMER_ONESHOT,
                    uart_idle_timer_callback,
                    NULL);

  Radio.Init(&radio_events);
  radio_apply_config();
  radio_resume_rx();
}

void RA09_ModemOnUartByte(uint8_t byte)
{
  if (byte == '\r' || byte == '\n')
  {
    if (uart_length > 0U)
    {
      UTIL_TIMER_Stop(&uart_idle_timer);
      uart_message_ready = true;
      schedule_command_task();
    }
    return;
  }

  if (uart_message_ready)
  {
    return;
  }

  if (uart_length < UART_MAX_MESSAGE)
  {
    uart_buffer[uart_length++] = byte;
  }
  else
  {
    uart_overflow = true;
  }

  UTIL_TIMER_Stop(&uart_idle_timer);
  UTIL_TIMER_SetPeriod(&uart_idle_timer, UART_IDLE_MS);
  UTIL_TIMER_Start(&uart_idle_timer);
}

void RA09_ModemCommandProcess(void)
{
  uint16_t length;
  bool overflow;

  if (!uart_message_ready)
  {
    return;
  }

  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  length = uart_length;
  overflow = uart_overflow;
  memcpy(message_buffer, uart_buffer, length);
  uart_length = 0;
  uart_overflow = false;
  uart_message_ready = false;
  __set_PRIMASK(primask);

  if (overflow)
  {
    reply_error("PAYLOAD_TOO_LARGE");
    return;
  }
  if (length == 0U)
  {
    return;
  }

  message_buffer[length] = '\0';
  if (buffer_is_at_command(message_buffer, length))
  {
    handle_command((char *)message_buffer);
  }
  else if (length > MODEM_MAX_PAYLOAD)
  {
    reply_error("PAYLOAD_TOO_LARGE");
  }
  else
  {
    (void)radio_send(message_buffer, (uint8_t)length);
  }
}

void RA09_ModemRadioProcess(void)
{
  uint32_t events = take_events();

  if ((events & EVENT_TX_DONE) != 0U)
  {
    tx_busy = false;
    if (debug_enabled)
    {
      uart_text("+TXDONE\r\n");
    }
    radio_resume_rx();
  }

  if ((events & EVENT_TX_TIMEOUT) != 0U)
  {
    tx_busy = false;
    reply_error("TX_TIMEOUT");
    radio_resume_rx();
  }

  if ((events & EVENT_RX_DONE) != 0U)
  {
    uint8_t length = rx_length;
    last_packet.length = length;
    last_packet.rssi = rx_rssi;
    last_packet.snr = rx_snr;
    memcpy(last_packet.data, rx_buffer, length);
    last_packet.valid = true;

    if (debug_enabled)
    {
      uart_printf("+RX:%d,%d,%u,", last_packet.rssi, last_packet.snr, length);
      for (uint16_t index = 0; index < length; index++)
      {
        uart_printf("%02X", last_packet.data[index]);
      }
      uart_text("\r\n");
    }
    else
    {
      uart_write(last_packet.data, length);
      uart_text("\r\n");
    }
    radio_resume_rx();
  }

  if ((events & (EVENT_RX_TIMEOUT | EVENT_RX_ERROR)) != 0U)
  {
    if (debug_enabled)
    {
      uart_text((events & EVENT_RX_ERROR) ? "#ERROR: RX_ERROR\r\n" : "+RXTIMEOUT\r\n");
    }
    radio_resume_rx();
  }
}
