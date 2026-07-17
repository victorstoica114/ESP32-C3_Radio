#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <RadioLib.h>
#include <EEPROM.h>
#include <U8g2lib.h>

#ifndef CC1101_MODULE_NAME
#define CC1101_MODULE_NAME "CC1101"
#endif

#ifndef CC1101_DISPLAY_LINE1
#define CC1101_DISPLAY_LINE1 "RADIO"
#endif

#ifndef CC1101_DISPLAY_LINE2
#define CC1101_DISPLAY_LINE2 "CC1101"
#endif

#ifndef CC1101_HELP_TITLE
#define CC1101_HELP_TITLE "AT Shell for CC1101 Radio Module"
#endif

#ifndef CC1101_CONFIG_TITLE
#define CC1101_CONFIG_TITLE "====== CC1101 CONFIGURATION ======"
#endif

#ifndef CC1101_BOOT_TITLE
#define CC1101_BOOT_TITLE "CC1101 AT Bridge"
#endif

#ifndef CC1101_BOOT_SUBTITLE
#define CC1101_BOOT_SUBTITLE "115200 8N1 <-> 433 MHz Radio"
#endif

#ifndef CC1101_DEF_FREQUENCY_MHZ
#define CC1101_DEF_FREQUENCY_MHZ 433.92f
#endif

#ifndef CC1101_DEF_TX_POWER_DBM
#define CC1101_DEF_TX_POWER_DBM 10
#endif

#ifndef CC1101_NOMINAL_TX_POWER_DBM
#define CC1101_NOMINAL_TX_POWER_DBM 10
#endif

#ifndef CC1101_EEPROM_MAGIC
#define CC1101_EEPROM_MAGIC 0x43433031UL
#endif

/*
  CC1101 AT Bridge - Comunicatie bidirectionala cu comenzi AT
  
  Serial (115200 8N1) <---> CC1101 Radio
  
  Conexiuni CC1101 -> ESP32-C3:
  - VCC  -> 3.3V
  - GND  -> GND
  - CSN  -> GPIO 7
  - SCK  -> GPIO 4
  - MOSI -> GPIO 6
  - MISO -> GPIO 5
  - GDO0 -> GPIO 10
  - GDO2 -> GPIO 3
*/

#define OLED_RESET U8X8_PIN_NONE
#define OLED_SDA   5
#define OLED_SCL   6

// SSD1306 128x64, hardware I2C
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, OLED_RESET, OLED_SCL, OLED_SDA);

static void drawCentered(const char* text, int baselineY, const uint8_t* font) {
  u8g2.setFont(font);
  int w = u8g2.getStrWidth(text);
  int x = (128 - w) / 2;
  if (x < 0) x = 0;
  u8g2.drawStr(x, baselineY, text);
}

// =============================================================================
// HW PINS (ESP32-C3)
// =============================================================================
static const int CC1101_CS_PIN   = 7;
static const int CC1101_GDO0_PIN = 10;
static const int CC1101_GDO2_PIN = 3;
static const int LED_PIN         = 8;
static const int SPI_SCK_PIN     = 4;
static const int SPI_MISO_PIN    = 5;
static const int SPI_MOSI_PIN    = 6;
static const int SPI_SS_PIN      = CC1101_CS_PIN;

// =============================================================================
// UART
// =============================================================================
static const uint32_t USB_BAUD = 115200;

// =============================================================================
// DEFAULT RADIO CONFIG
// =============================================================================
static const float    DEF_FREQUENCY    = CC1101_DEF_FREQUENCY_MHZ; // MHz
static const float    DEF_BITRATE      = 4.8;      // kbps
static const float    DEF_FREQ_DEV     = 5.2;      // kHz
static const float    DEF_RX_BW        = 135.0;    // kHz
static const int8_t   DEF_TX_POWER     = CC1101_DEF_TX_POWER_DBM;   // dBm
static const uint8_t  DEF_PREAMBLE     = 16;       // bits
static const uint8_t  DEF_SYNC_WORD_H  = 0xD3;
static const uint8_t  DEF_SYNC_WORD_L  = 0x91;

// Valid bandwidth values for CC1101
static const float VALID_BANDWIDTHS[] = {
  58.03, 67.71, 81.25, 101.56, 116.07, 135.09, 162.50, 203.12,
  232.14, 270.83, 325.00, 406.25, 464.29, 541.67, 650.00, 812.50
};
static const int NUM_BANDWIDTHS = 16;

// Valid bitrates for CC1101
static const float VALID_BITRATES[] = {
  0.6, 1.2, 2.4, 4.8, 9.6, 19.2, 38.4, 76.8, 153.6, 250.0, 500.0
};
static const int NUM_BITRATES = 11;

// TX Power levels accepted by RadioLib's CC1101 driver (dBm).
// Some CC1101-based modules, such as E07-433M20S, have an external PA and a
// higher nominal module output, but still use these CC1101 PATABLE presets here.
static const int8_t VALID_POWERS[] = { -30, -20, -15, -10, 0, 5, 7, 10 };
static const int NUM_POWERS = 8;

// =============================================================================
// EEPROM PERSISTENCE
// =============================================================================
static const uint32_t EEPROM_MAGIC   = CC1101_EEPROM_MAGIC;
static const uint16_t EEPROM_VERSION = 0x0003;
static const size_t   EEPROM_SIZE    = 512;

struct RadioConfig {
  float    frequency;
  float    bitRate;
  float    freqDev;
  float    rxBandwidth;
  int8_t   txPower;
  uint8_t  preambleLen;
  uint8_t  syncWordH;
  uint8_t  syncWordL;
  bool     crcEnabled;
  uint8_t  modMode;              // 0=2FSK, 1=GFSK, 2=OOK/ASK, 3=4FSK
  uint8_t  dataShaping;          // RADIOLIB_SHAPING_NONE or RADIOLIB_SHAPING_0_5
  uint8_t  encoding;             // RADIOLIB_ENCODING_*
  bool     fixedPacketLen;
  uint8_t  packetLen;
  bool     addressFiltering;
  uint8_t  nodeAddress;
  uint8_t  broadcastAddrs;       // RadioLib CC1101 accepts 1 or 2 when address filtering is ON
  bool     promiscuous;
  bool     requireCarrierSense;
  uint8_t  syncMaxErrBits;       // 0 or 1
};

struct EepromBlob {
  uint32_t    magic;
  uint16_t    version;
  uint16_t    length;
  RadioConfig cfg;
  uint32_t    crc;
};

// =============================================================================
// GLOBALS
// =============================================================================
class DebuggableCC1101 : public CC1101 {
public:
  explicit DebuggableCC1101(Module* module) : CC1101(module) {}

  uint8_t rxByteCount() {
    int16_t value = SPIgetRegValue(RADIOLIB_CC1101_REG_RXBYTES, 6, 0);
    return (value < 0) ? 0 : (uint8_t)value;
  }

  uint8_t marcState() {
    int16_t value = SPIgetRegValue(RADIOLIB_CC1101_REG_MARCSTATE, 4, 0);
    return (value < 0) ? 0xFF : (uint8_t)value;
  }
};

DebuggableCC1101 radio(new Module(CC1101_CS_PIN, CC1101_GDO0_PIN, RADIOLIB_NC, CC1101_GDO2_PIN));

static RadioConfig cfgDefault;
static RadioConfig cfgCurrent;

static bool bridgeEnabled = true;
static bool debugEnabled  = false;

// Serial buffer
#define SERIAL_BUFFER_SIZE 64
static char serialBuffer[SERIAL_BUFFER_SIZE];
static int  serialBufferIndex = 0;
static unsigned long lastSerialTime = 0;
#define SERIAL_TIMEOUT 50

// Radio RX flag
static volatile bool radioReceived = false;
static bool inReceiveMode = true;
static bool radioSleeping = false;
static bool receiveModeBeforeSleep = true;
static bool receiveActionsAttached = false;
static bool lastGdo0State = false;
static bool lastGdo2State = false;

// LED 1Hz
static uint32_t ledTickMs = 0;
static bool ledState = false;

static void beginRadioSpiBus() {
  SPI.end();
  delay(5);
  pinMode(CC1101_CS_PIN, OUTPUT);
  digitalWrite(CC1101_CS_PIN, HIGH);
  SPI.begin(SPI_SCK_PIN, SPI_MISO_PIN, SPI_MOSI_PIN, SPI_SS_PIN);
  SPI.setFrequency(1000000);
  delay(5);
}

static void releaseOledI2CBus() {
  delay(10);
  Wire.end();

  pinMode(OLED_SDA, INPUT);
  pinMode(OLED_SCL, INPUT);
  delay(5);
}

static void oled_setup() {
  SPI.end();
  delay(10);
  Wire.end();
  delay(2);
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(400000);
  delay(10);

  u8g2.setBusClock(400000);
  u8g2.begin();
  u8g2.setPowerSave(0);
  u8g2.setContrast(255);

  u8g2.clearBuffer();
  drawCentered(CC1101_DISPLAY_LINE1, 42, u8g2_font_logisoso18_tr);
  drawCentered(CC1101_DISPLAY_LINE2, 63, u8g2_font_logisoso18_tr);
  u8g2.sendBuffer();

  releaseOledI2CBus();
}

// =============================================================================
// CRC32
// =============================================================================
static uint32_t crc32_update(uint32_t crc, uint8_t data) {
  crc ^= data;
  for (int i = 0; i < 8; i++) {
    uint32_t mask = -(int32_t)(crc & 1u);
    crc = (crc >> 1) ^ (0xEDB88320u & mask);
  }
  return crc;
}

static uint32_t crc32_calc(const uint8_t* data, size_t len) {
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; i++) crc = crc32_update(crc, data[i]);
  return ~crc;
}

// =============================================================================
// EEPROM Functions
// =============================================================================
static bool eepromLoad(RadioConfig& out) {
  EepromBlob b;
  EEPROM.get(0, b);
  if (b.magic != EEPROM_MAGIC) return false;
  if (b.version != EEPROM_VERSION) return false;
  if (b.length != (uint16_t)sizeof(RadioConfig)) return false;
  uint32_t c = crc32_calc((const uint8_t*)&b.cfg, sizeof(RadioConfig));
  if (c != b.crc) return false;
  out = b.cfg;
  return true;
}

static bool eepromSave(const RadioConfig& in) {
  EepromBlob b;
  b.magic   = EEPROM_MAGIC;
  b.version = EEPROM_VERSION;
  b.length  = (uint16_t)sizeof(RadioConfig);
  b.cfg     = in;
  b.crc     = crc32_calc((const uint8_t*)&b.cfg, sizeof(RadioConfig));
  EEPROM.put(0, b);
  return EEPROM.commit();
}

// =============================================================================
// LED Heartbeat
// =============================================================================
static void led1HzService() {
  uint32_t now = millis();
  if (now - ledTickMs >= 500) {
    ledTickMs = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState ? HIGH : LOW);
  }
}

// =============================================================================
// Radio Interrupt
// =============================================================================
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void radioInterrupt(void) {
  radioReceived = true;
}

static void detachReceiveActions() {
  if (!receiveActionsAttached) return;
  radio.clearPacketReceivedAction();
  radio.clearGdo2Action();
  receiveActionsAttached = false;
}

static void attachReceiveActions() {
  detachReceiveActions();
  pinMode(CC1101_GDO0_PIN, INPUT);
  pinMode(CC1101_GDO2_PIN, INPUT);
  radio.setPacketReceivedAction(radioInterrupt);
  lastGdo0State = digitalRead(CC1101_GDO0_PIN) == HIGH;
  lastGdo2State = digitalRead(CC1101_GDO2_PIN) == HIGH;
  receiveActionsAttached = true;
}

static void pollReceivePins() {
  if (!inReceiveMode || radioSleeping || radioReceived) return;
  if (digitalRead(CC1101_GDO0_PIN) == HIGH) {
    radioReceived = true;
    return;
  }

  uint8_t rxBytes = radio.rxByteCount();
  if (rxBytes > 0 && radio.marcState() == RADIOLIB_CC1101_MARC_STATE_IDLE) {
    radioReceived = true;
  }
}

// =============================================================================
// Radio Functions
// =============================================================================
static void startReceive() {
  // Clear orice flag anterior
  radioReceived = false;
  
  // Flush RX FIFO inainte de a incepe receptia
  digitalWrite(CC1101_CS_PIN, LOW);
  SPI.transfer(0x3A);  // SFRX - Flush RX FIFO
  digitalWrite(CC1101_CS_PIN, HIGH);
  delayMicroseconds(100);
  
  int state = radio.startReceive();
  
  if (debugEnabled && state != RADIOLIB_ERR_NONE) {
    Serial.print(F("[DEBUG] startReceive() failed: "));
    Serial.println(state);
  }

  if (state == RADIOLIB_ERR_NONE) {
    attachReceiveActions();
  }
  
  inReceiveMode = true;
}

static bool applyConfig(const RadioConfig& cfg) {
  beginRadioSpiBus();

  // Opreste receptia si pune in standby
  radio.standby();
  radioSleeping = false;
  delay(10);
  
  int state;
  if (cfg.modMode == 3) {
    state = radio.beginFSK4(
      cfg.frequency,
      cfg.bitRate,
      cfg.freqDev,
      cfg.rxBandwidth,
      cfg.txPower,
      cfg.preambleLen
    );
  } else {
    state = radio.begin(
      cfg.frequency,
      cfg.bitRate,
      cfg.freqDev,
      cfg.rxBandwidth,
      cfg.txPower,
      cfg.preambleLen
    );
  }
  
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] begin() failed: "));
      Serial.println(state);
    }
    return false;
  }
  
  if (cfg.modMode != 3) {
    state = radio.setOOK(cfg.modMode == 2);
    if (state != RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.print(F("[DEBUG] setOOK() failed: "));
        Serial.println(state);
      }
      return false;
    }
  }

  uint8_t shaping = (cfg.modMode == 1) ? RADIOLIB_SHAPING_0_5 : cfg.dataShaping;
  state = radio.setDataShaping(shaping);
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] setDataShaping() failed: "));
      Serial.println(state);
    }
    return false;
  }

  state = radio.setEncoding(cfg.encoding);
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] setEncoding() failed: "));
      Serial.println(state);
    }
    return false;
  }

  if (cfg.promiscuous) {
    state = radio.setPromiscuousMode(true, cfg.requireCarrierSense);
    if (state != RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.print(F("[DEBUG] setPromiscuousMode() failed: "));
        Serial.println(state);
      }
      return false;
    }
  } else {
    // Set sync word and optional carrier-sense requirement.
    uint8_t syncWord[] = { cfg.syncWordH, cfg.syncWordL };
    state = radio.setSyncWord(syncWord, 2, cfg.syncMaxErrBits, cfg.requireCarrierSense);
    if (state != RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.print(F("[DEBUG] setSyncWord() failed: "));
        Serial.println(state);
      }
      return false;
    }

    // Set CRC
    state = radio.setCrcFiltering(cfg.crcEnabled);
    if (state != RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.print(F("[DEBUG] setCrcFiltering() failed: "));
        Serial.println(state);
      }
      return false;
    }

    if (cfg.addressFiltering) {
      state = radio.setNodeAddress(cfg.nodeAddress, cfg.broadcastAddrs);
    } else {
      state = radio.disableAddressFiltering();
    }
    if (state != RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.print(F("[DEBUG] address filtering failed: "));
        Serial.println(state);
      }
      return false;
    }
  }

  if (cfg.fixedPacketLen) {
    state = radio.fixedPacketLengthMode(cfg.packetLen);
  } else {
    state = radio.variablePacketLengthMode(cfg.packetLen);
  }
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] packet length mode failed: "));
      Serial.println(state);
    }
    return false;
  }
  
  // IMPORTANT: Clear RX FIFO
  digitalWrite(CC1101_CS_PIN, LOW);
  SPI.transfer(0x3A);  // SFRX - Flush RX FIFO
  digitalWrite(CC1101_CS_PIN, HIGH);
  delayMicroseconds(100);
  
  // IMPORTANT: Reset flag-ul inainte de a seta interrupt handler
  radioReceived = false;
  detachReceiveActions();
  
  return true;
}

static bool transmitData(const char* data, int length) {
  if (radioSleeping) return false;

  const bool restoreReceive = inReceiveMode;
  inReceiveMode = false;

  // Some CC1101 V1 boards do not route GDO2 to the ESP32. RadioLib's
  // blocking transmit() waits for that pin and therefore adds a 5x-airtime
  // timeout after every frame even though the packet was sent correctly.
  // Start TX normally, then poll the CC1101 MARCSTATE over SPI until the
  // radio returns to IDLE. This works with both V1 and V2 wiring.
  int state = radio.startTransmit((uint8_t*)data, length);
  if (state == RADIOLIB_ERR_NONE) {
    const float preambleBytes = cfgCurrent.preambleLen / 8.0f;
    const float estimatedMs =
        ((length + preambleBytes + 5.0f) * 8.0f) / cfgCurrent.bitRate;
    const uint32_t timeoutMs = (uint32_t)ceilf(estimatedMs * 2.0f + 20.0f);
    const uint32_t startedMs = millis();
    delayMicroseconds(200);
    while (radio.marcState() != RADIOLIB_CC1101_MARC_STATE_IDLE &&
           (uint32_t)(millis() - startedMs) < timeoutMs) {
      delayMicroseconds(100);
    }
    if (radio.marcState() == RADIOLIB_CC1101_MARC_STATE_IDLE) {
      state = radio.finishTransmit();
    } else {
      radio.standby();
      state = RADIOLIB_ERR_TX_TIMEOUT;
    }
  }
  
  if (debugEnabled) {
    Serial.print(F("[TX] "));
    Serial.print(length);
    Serial.print(F(" bytes, state: "));
    Serial.println(state);
  }
  
  // Restore the state selected by AT+RX. Power measurements use RX=OFF so
  // the post-TX current returns to standby instead of becoming part of the
  // measured packet-energy window.
  if (restoreReceive) {
    startReceive();
  } else {
    detachReceiveActions();
    radioReceived = false;
    radio.standby();
    inReceiveMode = false;
  }
  
  return state == RADIOLIB_ERR_NONE;
}

static bool transmitBurst(size_t totalBytes, size_t frameBytes,
                          uint32_t interFrameGapMs = 0) {
  static const char alphabet[] =
      "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_";
  static const size_t alphabetLength = sizeof(alphabet) - 1;

  if (radioSleeping || frameBytes < 3 || frameBytes > 64 || totalBytes < 1 ||
      totalBytes > 1024) {
    return false;
  }

  size_t remaining = totalBytes;
  size_t frames = 0;
  uint8_t frame[64];
  while (remaining > 0) {
    const size_t length = min(frameBytes, remaining);
    if (length < 3) return false;

    const size_t contentLength = length - 2;
    for (size_t index = 0; index < contentLength; index++) {
      frame[index] = alphabet[index % alphabetLength];
    }
    frame[contentLength] = '\r';
    frame[contentLength + 1] = '\n';

    if (!transmitData((const char*)frame, (int)length)) return false;
    remaining -= length;
    frames++;
    if (remaining > 0 && interFrameGapMs > 0) {
      delay(interFrameGapMs);
    }
  }

  Serial.print(F("TXBURST="));
  Serial.print(totalBytes);
  Serial.print(F(",FRAMES="));
  Serial.print(frames);
  Serial.print(F(",FRAME_MAX="));
  Serial.print(frameBytes);
  Serial.print(F(",GAP_MS="));
  Serial.println(interFrameGapMs);
  return true;
}

static bool transmitContinuous(uint32_t durationMs, size_t frameBytes,
                               uint32_t interFrameGapMs = 0) {
  static const char alphabet[] =
      "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_";
  static const size_t alphabetLength = sizeof(alphabet) - 1;

  if (radioSleeping || durationMs < 1000 || durationMs > 600000 ||
      frameBytes < 3 || frameBytes > 64) {
    return false;
  }

  uint8_t frame[64];
  const size_t contentLength = frameBytes - 2;
  for (size_t index = 0; index < contentLength; index++) {
    frame[index] = alphabet[index % alphabetLength];
  }
  frame[contentLength] = '\r';
  frame[contentLength + 1] = '\n';

  const uint32_t startMs = millis();
  uint32_t frames = 0;
  while ((uint32_t)(millis() - startMs) < durationMs) {
    if (!transmitData((const char*)frame, (int)frameBytes)) return false;
    frames++;
    if (interFrameGapMs > 0 &&
        (uint32_t)(millis() - startMs) < durationMs) {
      delay(interFrameGapMs);
    }
  }

  const uint32_t elapsedMs = (uint32_t)(millis() - startMs);
  Serial.print(F("TXCONT="));
  Serial.print(durationMs);
  Serial.print(F(",ELAPSED_MS="));
  Serial.print(elapsedMs);
  Serial.print(F(",FRAMES="));
  Serial.print(frames);
  Serial.print(F(",BYTES="));
  Serial.print((uint32_t)(frames * frameBytes));
  Serial.print(F(",FRAME="));
  Serial.print(frameBytes);
  Serial.print(F(",GAP_MS="));
  Serial.println(interFrameGapMs);
  return true;
}

// =============================================================================
// Default Config
// =============================================================================
static RadioConfig makeDefaultConfig() {
  RadioConfig c;
  c.frequency   = DEF_FREQUENCY;
  c.bitRate     = DEF_BITRATE;
  c.freqDev     = DEF_FREQ_DEV;
  c.rxBandwidth = DEF_RX_BW;
  c.txPower     = DEF_TX_POWER;
  c.preambleLen = DEF_PREAMBLE;
  c.syncWordH   = DEF_SYNC_WORD_H;
  c.syncWordL   = DEF_SYNC_WORD_L;
  c.crcEnabled  = true;
  c.modMode = 0;
  c.dataShaping = RADIOLIB_SHAPING_NONE;
  c.encoding = RADIOLIB_ENCODING_NRZ;
  c.fixedPacketLen = false;
  c.packetLen = 64;
  c.addressFiltering = false;
  c.nodeAddress = 0x01;
  c.broadcastAddrs = 1;
  c.promiscuous = false;
  c.requireCarrierSense = false;
  c.syncMaxErrBits = 0;
  return c;
}

// =============================================================================
// Helpers
// =============================================================================
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("#ERROR")); }
static inline void serialError(const __FlashStringHelper* msg) {
  Serial.print(F("#ERROR: "));
  Serial.println(msg);
}

static String readLineUSB() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (buf.length() == 0) continue;
      String line = buf;
      buf = "";
      line.trim();
      return line;
    } else {
      if (buf.length() < 200) buf += c;
    }
  }
  return "";
}

static bool startsWithAT(const String& s) {
  if (s.length() < 2) return false;
  char a = s[0], t = s[1];
  return (a == 'A' || a == 'a') && (t == 'T' || t == 't');
}

static bool parseFloat(const String& s, float& out) {
  char* endp = nullptr;
  float v = strtof(s.c_str(), &endp);
  if (!(endp && (*endp == '\0' || *endp == ' '))) return false;
  out = v;
  return true;
}

static bool parseInt8(const String& s, int8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < -128 || v > 127) return false;
  out = (int8_t)v;
  return true;
}

static bool parseUInt8(const String& s, uint8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseHex8(const String& s, uint8_t& out) {
  String t = s;
  t.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) {
    t = t.substring(2);
  }
  char* endp = nullptr;
  long v = strtol(t.c_str(), &endp, 16);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseOnOff(const String& s, bool& out) {
  String t = s; t.trim(); t.toUpperCase();
  if (t == "ON" || t == "1" || t == "TRUE")  { out = true;  return true; }
  if (t == "OFF"|| t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

static bool isValidPreamble(uint8_t preambleBits) {
  switch (preambleBits) {
    case 16: case 24: case 32: case 48:
    case 64: case 96: case 128: case 192:
      return true;
    default:
      return false;
  }
}

static bool isValidTxPower(int8_t power) {
  for (int i = 0; i < NUM_POWERS; i++) {
    if (VALID_POWERS[i] == power) return true;
  }
  return false;
}

static const char* modModeName(uint8_t mode) {
  switch (mode) {
    case 1: return "GFSK";
    case 2: return "OOK";
    case 3: return "4FSK";
    default: return "2FSK";
  }
}

static bool parseModMode(String s, uint8_t& out) {
  s.trim();
  s.toUpperCase();
  if (s == "2FSK" || s == "FSK" || s == "0") { out = 0; return true; }
  if (s == "GFSK" || s == "1") { out = 1; return true; }
  if (s == "OOK" || s == "ASK" || s == "2") { out = 2; return true; }
  if (s == "4FSK" || s == "4-FSK" || s == "3") { out = 3; return true; }
  return false;
}

static const char* encodingName(uint8_t encoding) {
  switch (encoding) {
    case RADIOLIB_ENCODING_MANCHESTER: return "MANCHESTER";
    case RADIOLIB_ENCODING_WHITENING: return "WHITENING";
    default: return "NRZ";
  }
}

static bool parseEncoding(String s, uint8_t& out) {
  s.trim();
  s.toUpperCase();
  if (s == "NRZ" || s == "0") { out = RADIOLIB_ENCODING_NRZ; return true; }
  if (s == "MANCHESTER" || s == "MAN" || s == "1") { out = RADIOLIB_ENCODING_MANCHESTER; return true; }
  if (s == "WHITENING" || s == "WHITE" || s == "2") { out = RADIOLIB_ENCODING_WHITENING; return true; }
  return false;
}

static const char* shapingName(uint8_t shaping) {
  return shaping == RADIOLIB_SHAPING_0_5 ? "0.5" : "NONE";
}

static bool parseShaping(String s, uint8_t& out) {
  s.trim();
  s.toUpperCase();
  if (s == "NONE" || s == "OFF" || s == "0") { out = RADIOLIB_SHAPING_NONE; return true; }
  if (s == "0.5" || s == "05" || s == "GFSK") { out = RADIOLIB_SHAPING_0_5; return true; }
  return false;
}

static int findNearestBandwidth(float bw) {
  int best = 0;
  float bestDiff = abs(bw - VALID_BANDWIDTHS[0]);
  for (int i = 1; i < NUM_BANDWIDTHS; i++) {
    float diff = abs(bw - VALID_BANDWIDTHS[i]);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  }
  return best;
}

// =============================================================================
// Print Config
// =============================================================================
static void printConfigPretty(const RadioConfig& c) {
  Serial.println(F(CC1101_CONFIG_TITLE));
  Serial.print(F("Module:       ")); Serial.println(F(CC1101_MODULE_NAME));
  Serial.print(F("Module max TX:")); Serial.print(CC1101_NOMINAL_TX_POWER_DBM); Serial.println(F(" dBm nominal"));
  Serial.print(F("Frequency:    ")); Serial.print(c.frequency, 2); Serial.println(F(" MHz"));
  Serial.print(F("Bit Rate:     ")); Serial.print(c.bitRate, 1); Serial.println(F(" kbps"));
  Serial.print(F("Freq Dev:     ")); Serial.print(c.freqDev, 1); Serial.println(F(" kHz"));
  Serial.print(F("RX Bandwidth: ")); Serial.print(c.rxBandwidth, 2); Serial.println(F(" kHz"));
  Serial.print(F("TX Power:     ")); Serial.print(c.txPower); Serial.println(F(" dBm"));
  Serial.print(F("Preamble:     ")); Serial.print(c.preambleLen); Serial.println(F(" bits"));
  Serial.print(F("Sync Word:    0x")); 
  if (c.syncWordH < 0x10) Serial.print("0");
  Serial.print(c.syncWordH, HEX);
  if (c.syncWordL < 0x10) Serial.print("0");
  Serial.println(c.syncWordL, HEX);
  Serial.print(F("CRC:          ")); Serial.println(c.crcEnabled ? F("Enabled") : F("Disabled"));
  Serial.print(F("Modulation:   ")); Serial.println(modModeName(c.modMode));
  Serial.print(F("Data shaping: ")); Serial.println(shapingName(c.dataShaping));
  Serial.print(F("Encoding:     ")); Serial.println(encodingName(c.encoding));
  Serial.print(F("Packet mode:  ")); Serial.println(c.fixedPacketLen ? F("FIXED") : F("VARIABLE"));
  Serial.print(F("Packet len:   ")); Serial.println(c.packetLen);
  Serial.print(F("Address filt: ")); Serial.println(c.addressFiltering ? F("ON") : F("OFF"));
  Serial.print(F("Node addr:    0x"));
  if (c.nodeAddress < 0x10) Serial.print('0');
  Serial.println(c.nodeAddress, HEX);
  Serial.print(F("Broadcasts:   ")); Serial.println(c.broadcastAddrs);
  Serial.print(F("Promiscuous:  ")); Serial.println(c.promiscuous ? F("ON") : F("OFF"));
  Serial.print(F("Carrier sense:")); Serial.println(c.requireCarrierSense ? F("ON") : F("OFF"));
  Serial.print(F("Sync err bits:")); Serial.println(c.syncMaxErrBits);
  Serial.print(F("Sleep:        ")); Serial.println(radioSleeping ? F("YES") : F("NO"));
  Serial.println(F("=================================="));
}

// =============================================================================
// HELP
// =============================================================================
static void printHelp() {
  Serial.println(F(""));
  Serial.println(F(CC1101_HELP_TITLE));
  Serial.println(F(""));
  Serial.println(F("Core Commands:"));
  Serial.println(F("  AT               -> OK (test)"));
  Serial.println(F("  AT+HELP          -> This help"));
  Serial.println(F("  AT+CFG?          -> Show current config"));
  Serial.println(F("  AT+APPLY         -> Apply config to radio + save EEPROM"));
  Serial.println(F("  AT+RESET         -> Reset radio module"));
  Serial.println(F("  AT+DEFAULT       -> Restore defaults + save EEPROM"));
  Serial.println(F("  AT+BRIDGE=ON/OFF -> Enable/disable bridge mode"));
  Serial.println(F("  AT+DEBUG=ON/OFF  -> Enable/disable debug output"));
  Serial.println(F(""));
  Serial.println(F("Radio Parameters:"));
  Serial.println(F("  AT+FREQ=<MHz>    / AT+FREQ?    (300-928 MHz)"));
  Serial.println(F("  AT+BR=<kbps>     / AT+BR?      (0.6-500 kbps)"));
  Serial.println(F("  AT+DEV=<kHz>     / AT+DEV?"));
  Serial.println(F("  AT+BW=<kHz>      / AT+BW?"));
  Serial.println(F("  AT+PWR=<dBm>     / AT+PWR?     (-30, -20, -15, -10, 0, 5, 7, 10 dBm)"));
  Serial.println(F("  AT+PRE=<bits>    / AT+PRE?     (16/24/32/48/64/96/128/192)"));
  Serial.println(F("  AT+SYNC=<XXXX>   / AT+SYNC?    (hex, e.g. D391)"));
  Serial.println(F("  AT+SYNCERR=0|1   / AT+SYNCERR?"));
  Serial.println(F("  AT+CRC=ON/OFF    / AT+CRC?"));
  Serial.println(F("  AT+MOD=2FSK|GFSK|OOK|4FSK / AT+MOD?"));
  Serial.println(F("  AT+SHAPE=NONE|0.5 / AT+SHAPE?"));
  Serial.println(F("  AT+ENC=NRZ|MANCHESTER|WHITENING / AT+ENC?"));
  Serial.println(F("  AT+PKT=VARIABLE,<1..64> / AT+PKT?"));
  Serial.println(F("  AT+PKT=FIXED,<1..64>"));
  Serial.println(F("  AT+ADDR=OFF      / AT+ADDR?"));
  Serial.println(F("  AT+ADDR=<node>,<broadcasts 1..2>"));
  Serial.println(F("  AT+PROMISC=ON|OFF / AT+PROMISC?"));
  Serial.println(F("  AT+CS=ON|OFF     / AT+CS?      (carrier sense with sync/promisc)"));
  Serial.println(F(""));
  Serial.println(F("Indexed Setters:"));
  Serial.println(F("  AT+BW1..16       -> Bandwidth presets:"));
  Serial.println(F("                      1=58, 2=68, 3=81, 4=102, 5=116, 6=135,"));
  Serial.println(F("                      7=163, 8=203, 9=232, 10=271, 11=325,"));
  Serial.println(F("                      12=406, 13=464, 14=542, 15=650, 16=813 kHz"));
  Serial.println(F("  AT+BR1..11       -> Bitrate presets:"));
  Serial.println(F("                      1=0.6, 2=1.2, 3=2.4, 4=4.8, 5=9.6,"));
  Serial.println(F("                      6=19.2, 7=38.4, 8=76.8, 9=153.6,"));
  Serial.println(F("                      10=250, 11=500 kbps"));
  Serial.println(F("  AT+PWR1..8       -> Power presets:"));
  Serial.println(F("                      1=-30, 2=-20, 3=-15, 4=-10,"));
  Serial.println(F("                      5=0, 6=5, 7=7, 8=10 dBm"));
  if (CC1101_NOMINAL_TX_POWER_DBM > 10) {
    Serial.print(F("  Note: module nominal max TX is "));
    Serial.print(CC1101_NOMINAL_TX_POWER_DBM);
    Serial.println(F(" dBm; AT+PWR controls CC1101 drive presets up to 10 dBm."));
  }
  Serial.println(F(""));
  Serial.println(F("Set All (one command):"));
  Serial.println(F("  AT+SETRADIO=FREQ,BR,DEV,BW,PWR,PRE,SYNC,CRC"));
  Serial.println(F("    Example: AT+SETRADIO=433.0,4.8,5.2,135,10,16,D391,1"));
  Serial.println(F(""));
  Serial.println(F("Info:"));
  Serial.println(F("  AT+STATUS?       -> Chip/status + current RSSI/LQI"));
  Serial.println(F("  AT+RSSI?         -> Show last RSSI"));
  Serial.println(F("  AT+LQI?          -> Show last LQI"));
  Serial.println(F("  AT+RX=ON/OFF     -> Start RX / standby"));
  Serial.println(F("  AT+TXBURST=<total>,<frame>[,<gap_ms>] -> TX transfer (max 1024/64 B)"));
  Serial.println(F("  AT+TXCONT=<duration_ms>,<frame>[,<gap_ms>] -> Continuous framed TX"));
  Serial.println(F("  AT+SLEEP         -> Sleep (low power)"));
  Serial.println(F("  AT+WAKE          -> Wake + restore RX"));
  Serial.println(F("  AT+RANDOM?       -> one RSSI-noise random byte"));
  Serial.println(F(""));
}

static bool putRadioToSleep() {
  receiveModeBeforeSleep = inReceiveMode;
  inReceiveMode = false;
  radioReceived = false;
  detachReceiveActions();

  int state = radio.sleep();
  if (state != RADIOLIB_ERR_NONE) return false;

  radioSleeping = true;
  return true;
}

static bool applySaveStartReceive() {
  bool ok = applyConfig(cfgCurrent);
  if (ok) {
    eepromSave(cfgCurrent);
    startReceive();
  }
  return ok;
}

static bool wakeRadioFromSleep() {
  int state = radio.standby();
  if (state != RADIOLIB_ERR_NONE) return false;

  radioSleeping = false;

  if (receiveModeBeforeSleep) {
    startReceive();
  } else {
    inReceiveMode = false;
  }

  return true;
}

// =============================================================================
// AT Command Handler
// =============================================================================
static bool handleAT(const String& lineRaw) {
  String line = lineRaw;
  line.trim();
  String u = line; u.toUpperCase();

  // Basic commands
  if (u == "AT") { serialOK(); return true; }
  if (u == "AT+HELP" || u == "AT?") { printHelp(); serialOK(); return true; }

  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }
  if (u == "AT+DEBUG?") {
    Serial.print(F("DEBUG="));
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }

  if (u == "AT+BRIDGE=ON")  { bridgeEnabled = true;  serialOK(); return true; }
  if (u == "AT+BRIDGE=OFF") { bridgeEnabled = false; serialOK(); return true; }
  if (u == "AT+BRIDGE?") {
    Serial.print(F("BRIDGE="));
    Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }

  if (u == "AT+CFG?") {
    printConfigPretty(cfgCurrent);
    serialOK();
    return true;
  }

  if (u == "AT+APPLY") {
    bool ok = applyConfig(cfgCurrent);
    if (ok) {
      eepromSave(cfgCurrent);
      startReceive();
    }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+DEFAULT") {
    cfgCurrent = cfgDefault;
    bool ok = applyConfig(cfgCurrent);
    if (ok) {
      eepromSave(cfgCurrent);
      startReceive();
    }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RESET") {
  Serial.print(F("[RADIO] Resetting... "));
  
  // Trimite SRES (strobe reset) direct prin SPI
  digitalWrite(CC1101_CS_PIN, LOW);
  SPI.transfer(0x30);  // SRES command
  digitalWrite(CC1101_CS_PIN, HIGH);
  delay(100);
  
  // Reinitializeaza cu configuratia curenta
  bool ok = applyConfig(cfgCurrent);
  if (ok) {
    startReceive();
    Serial.println(F("OK"));
  } else {
    Serial.println(F("FAILED"));
  }
  ok ? serialOK() : serialERR();
  return true;
  }

  if (u == "AT+SLEEP") {
    putRadioToSleep() ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+WAKE") {
    wakeRadioFromSleep() ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RSSI?") {
    Serial.print(F("RSSI: "));
    Serial.print(radio.getRSSI());
    Serial.println(F(" dBm"));
    serialOK();
    return true;
  }

  if (u == "AT+LQI?") {
    Serial.print(F("LQI: "));
    Serial.println(radio.getLQI());
    serialOK();
    return true;
  }

  if (u == "AT+STATUS?") {
    Serial.print(F("CHIP_VERSION=0x"));
    int16_t chip = radio.getChipVersion();
    if (chip >= 0 && chip < 16) Serial.print('0');
    Serial.println(chip, HEX);
    Serial.print(F("RSSI=")); Serial.println(radio.getRSSI());
    Serial.print(F("LQI=")); Serial.println(radio.getLQI());
    Serial.print(F("MODE=")); Serial.println(modModeName(cfgCurrent.modMode));
    Serial.print(F("RX=")); Serial.println(inReceiveMode ? F("ON") : F("OFF"));
    Serial.print(F("SLEEP=")); Serial.println(radioSleeping ? F("YES") : F("NO"));
    Serial.print(F("BRIDGE=")); Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }

  if (u == "AT+RANDOM?") {
    uint8_t b = radio.randomByte();
    Serial.print(F("RANDOM=0x"));
    if (b < 16) Serial.print('0');
    Serial.println(b, HEX);
    serialOK();
    return true;
  }

  if (u == "AT+RX=OFF") {
    inReceiveMode = false;
    radioReceived = false;
    detachReceiveActions();
    int state = radio.standby();
    radioSleeping = false;
    (state == RADIOLIB_ERR_NONE) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RX=ON") {
    radioSleeping = false;
    startReceive();
    serialOK();
    return true;
  }

  if (u.startsWith("AT+TXBURST=")) {
    String args = line.substring(11);
    int firstComma = args.indexOf(',');
    if (firstComma <= 0 || firstComma >= (int)args.length() - 1) {
      serialError(F("TXBURST_FORMAT (AT+TXBURST=<1..1024>,<3..64>[,<0..1000>])"));
      return true;
    }
    String remainder = args.substring(firstComma + 1);
    int secondComma = remainder.indexOf(',');
    long totalBytes = args.substring(0, firstComma).toInt();
    long frameBytes = (secondComma >= 0)
        ? remainder.substring(0, secondComma).toInt()
        : remainder.toInt();
    long interFrameGapMs = (secondComma >= 0)
        ? remainder.substring(secondComma + 1).toInt()
        : 0;
    if (totalBytes < 1 || totalBytes > 1024 || frameBytes < 3 || frameBytes > 64 ||
        interFrameGapMs < 0 || interFrameGapMs > 1000 ||
        (totalBytes % frameBytes != 0 && totalBytes % frameBytes < 3)) {
      serialError(F("TXBURST_RANGE"));
      return true;
    }
    if (transmitBurst((size_t)totalBytes, (size_t)frameBytes,
                      (uint32_t)interFrameGapMs)) {
      serialOK();
    } else {
      serialError(F("TXBURST_FAILED"));
    }
    return true;
  }

  if (u.startsWith("AT+TXCONT=")) {
    String args = line.substring(10);
    int firstComma = args.indexOf(',');
    if (firstComma <= 0 || firstComma >= (int)args.length() - 1) {
      serialError(F("TXCONT_FORMAT (AT+TXCONT=<1000..600000>,<3..64>[,<0..1000>])"));
      return true;
    }
    String remainder = args.substring(firstComma + 1);
    int secondComma = remainder.indexOf(',');
    long durationMs = args.substring(0, firstComma).toInt();
    long frameBytes = (secondComma >= 0)
        ? remainder.substring(0, secondComma).toInt()
        : remainder.toInt();
    long interFrameGapMs = (secondComma >= 0)
        ? remainder.substring(secondComma + 1).toInt()
        : 0;
    if (durationMs < 1000 || durationMs > 600000 ||
        frameBytes < 3 || frameBytes > 64 ||
        interFrameGapMs < 0 || interFrameGapMs > 1000) {
      serialError(F("TXCONT_RANGE"));
      return true;
    }
    if (transmitContinuous((uint32_t)durationMs, (size_t)frameBytes,
                           (uint32_t)interFrameGapMs)) {
      serialOK();
    } else {
      serialError(F("TXCONT_FAILED"));
    }
    return true;
  }

  if (u == "AT+FREQ?") { Serial.print(F("FREQ=")); Serial.println(cfgCurrent.frequency, 3); serialOK(); return true; }
  if (u == "AT+BR?") { Serial.print(F("BR=")); Serial.println(cfgCurrent.bitRate, 3); serialOK(); return true; }
  if (u == "AT+DEV?") { Serial.print(F("DEV=")); Serial.println(cfgCurrent.freqDev, 3); serialOK(); return true; }
  if (u == "AT+BW?") { Serial.print(F("BW=")); Serial.println(cfgCurrent.rxBandwidth, 2); serialOK(); return true; }
  if (u == "AT+PWR?") { Serial.print(F("PWR=")); Serial.println(cfgCurrent.txPower); serialOK(); return true; }
  if (u == "AT+PRE?") { Serial.print(F("PRE=")); Serial.println(cfgCurrent.preambleLen); serialOK(); return true; }
  if (u == "AT+SYNC?") {
    Serial.print(F("SYNC=0x"));
    if (cfgCurrent.syncWordH < 0x10) Serial.print('0');
    Serial.print(cfgCurrent.syncWordH, HEX);
    if (cfgCurrent.syncWordL < 0x10) Serial.print('0');
    Serial.println(cfgCurrent.syncWordL, HEX);
    serialOK();
    return true;
  }
  if (u == "AT+SYNCERR?") { Serial.print(F("SYNCERR=")); Serial.println(cfgCurrent.syncMaxErrBits); serialOK(); return true; }
  if (u == "AT+CRC?") { Serial.print(F("CRC=")); Serial.println(cfgCurrent.crcEnabled ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+MOD?") { Serial.print(F("MOD=")); Serial.println(modModeName(cfgCurrent.modMode)); serialOK(); return true; }
  if (u == "AT+SHAPE?") { Serial.print(F("SHAPE=")); Serial.println(shapingName(cfgCurrent.dataShaping)); serialOK(); return true; }
  if (u == "AT+ENC?") { Serial.print(F("ENC=")); Serial.println(encodingName(cfgCurrent.encoding)); serialOK(); return true; }
  if (u == "AT+PKT?") {
    Serial.print(F("PKT="));
    Serial.print(cfgCurrent.fixedPacketLen ? F("FIXED") : F("VARIABLE"));
    Serial.print(',');
    Serial.println(cfgCurrent.packetLen);
    serialOK();
    return true;
  }
  if (u == "AT+ADDR?") {
    Serial.print(F("ADDR="));
    if (!cfgCurrent.addressFiltering) {
      Serial.println(F("OFF"));
    } else {
      Serial.print(F("0x"));
      if (cfgCurrent.nodeAddress < 0x10) Serial.print('0');
      Serial.print(cfgCurrent.nodeAddress, HEX);
      Serial.print(',');
      Serial.println(cfgCurrent.broadcastAddrs);
    }
    serialOK();
    return true;
  }
  if (u == "AT+PROMISC?") { Serial.print(F("PROMISC=")); Serial.println(cfgCurrent.promiscuous ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+CS?") { Serial.print(F("CS=")); Serial.println(cfgCurrent.requireCarrierSense ? F("ON") : F("OFF")); serialOK(); return true; }

  if (u.startsWith("AT+MOD=")) {
    uint8_t mode;
    if (!parseModMode(line.substring(7), mode)) { serialERR(); return true; }
    cfgCurrent.modMode = mode;
    if (mode == 1) cfgCurrent.dataShaping = RADIOLIB_SHAPING_0_5;
    if (mode == 0 || mode == 2 || mode == 3) cfgCurrent.dataShaping = RADIOLIB_SHAPING_NONE;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+SHAPE=")) {
    uint8_t shaping;
    if (!parseShaping(line.substring(9), shaping)) { serialERR(); return true; }
    cfgCurrent.dataShaping = shaping;
    cfgCurrent.modMode = (shaping == RADIOLIB_SHAPING_0_5) ? 1 : 0;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+ENC=")) {
    uint8_t encoding;
    if (!parseEncoding(line.substring(7), encoding)) { serialERR(); return true; }
    cfgCurrent.encoding = encoding;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+PKT=")) {
    String p = line.substring(7);
    p.trim();
    String up = p;
    up.toUpperCase();
    int comma = p.indexOf(',');
    if (comma < 0) { serialERR(); return true; }
    String mode = up.substring(0, comma);
    uint8_t len;
    if (!parseUInt8(p.substring(comma + 1), len) || len < 1 || len > 64) { serialERR(); return true; }
    if (mode == "FIXED") cfgCurrent.fixedPacketLen = true;
    else if (mode == "VARIABLE" || mode == "VAR") cfgCurrent.fixedPacketLen = false;
    else { serialERR(); return true; }
    cfgCurrent.packetLen = len;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+ADDR=OFF") {
    cfgCurrent.addressFiltering = false;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+ADDR=")) {
    String p = line.substring(8);
    int comma = p.indexOf(',');
    if (comma < 0) { serialERR(); return true; }
    uint8_t node;
    uint8_t broadcasts;
    if (!parseHex8(p.substring(0, comma), node)) { serialERR(); return true; }
    if (!parseUInt8(p.substring(comma + 1), broadcasts) || broadcasts < 1 || broadcasts > 2) { serialERR(); return true; }
    cfgCurrent.addressFiltering = true;
    cfgCurrent.nodeAddress = node;
    cfgCurrent.broadcastAddrs = broadcasts;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+PROMISC=")) {
    bool on;
    if (!parseOnOff(line.substring(11), on)) { serialERR(); return true; }
    cfgCurrent.promiscuous = on;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+CS=")) {
    bool on;
    if (!parseOnOff(line.substring(6), on)) { serialERR(); return true; }
    cfgCurrent.requireCarrierSense = on;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+SYNCERR=")) {
    uint8_t v;
    if (!parseUInt8(line.substring(11), v) || v > 1) { serialERR(); return true; }
    cfgCurrent.syncMaxErrBits = v;
    bool ok = applySaveStartReceive();
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Frequency ---
  if (u.startsWith("AT+FREQ=")) {
    float v;
    if (!parseFloat(line.substring(8), v)) { serialERR(); return true; }
    if (v < 300.0 || v > 928.0) { serialERR(); return true; }
    cfgCurrent.frequency = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Bit Rate (direct value) ---
  if (u.startsWith("AT+BR=")) {
    float v;
    if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    if (v < 0.3 || v > 600.0) { serialERR(); return true; }
    cfgCurrent.bitRate = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Bit Rate (indexed) ---
  if (u.startsWith("AT+BR") && u.length() > 5 && isDigit(u[5])) {
    int idx = u.substring(5).toInt();
    if (idx < 1 || idx > NUM_BITRATES) { serialERR(); return true; }
    cfgCurrent.bitRate = VALID_BITRATES[idx - 1];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Frequency Deviation ---
  if (u.startsWith("AT+DEV=")) {
    float v;
    if (!parseFloat(line.substring(7), v)) { serialERR(); return true; }
    if (v < 1.0 || v > 380.0) { serialERR(); return true; }
    cfgCurrent.freqDev = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- RX Bandwidth (direct value) ---
  if (u.startsWith("AT+BW=")) {
    float v;
    if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    int idx = findNearestBandwidth(v);
    cfgCurrent.rxBandwidth = VALID_BANDWIDTHS[idx];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- RX Bandwidth (indexed) ---
  if (u.startsWith("AT+BW") && u.length() > 5 && isDigit(u[5])) {
    int idx = u.substring(5).toInt();
    if (idx < 1 || idx > NUM_BANDWIDTHS) { serialERR(); return true; }
    cfgCurrent.rxBandwidth = VALID_BANDWIDTHS[idx - 1];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- TX Power (direct value) ---
  if (u.startsWith("AT+PWR=")) {
    int8_t v;
    if (!parseInt8(line.substring(7), v)) { serialERR(); return true; }
    if (!isValidTxPower(v)) { serialERR(); return true; }
    cfgCurrent.txPower = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- TX Power (indexed) ---
  if (u.startsWith("AT+PWR") && u.length() > 6 && isDigit(u[6])) {
    int idx = u.substring(6).toInt();
    if (idx < 1 || idx > NUM_POWERS) { serialERR(); return true; }
    cfgCurrent.txPower = VALID_POWERS[idx - 1];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Preamble ---
  if (u.startsWith("AT+PRE=")) {
    uint8_t v;
    if (!parseUInt8(line.substring(7), v)) { serialERR(); return true; }
    if (!isValidPreamble(v)) { serialERR(); return true; }
    cfgCurrent.preambleLen = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Sync Word ---
  if (u.startsWith("AT+SYNC=")) {
    String hexStr = line.substring(8);
    hexStr.trim();
    if (hexStr.startsWith("0x") || hexStr.startsWith("0X")) {
      hexStr = hexStr.substring(2);
    }
    if (hexStr.length() != 4) { serialERR(); return true; }
    
    uint8_t h, l;
    if (!parseHex8(hexStr.substring(0, 2), h)) { serialERR(); return true; }
    if (!parseHex8(hexStr.substring(2, 4), l)) { serialERR(); return true; }
    
    cfgCurrent.syncWordH = h;
    cfgCurrent.syncWordL = l;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- CRC ---
  if (u.startsWith("AT+CRC=")) {
    bool v;
    if (!parseOnOff(line.substring(7), v)) { serialERR(); return true; }
    cfgCurrent.crcEnabled = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Set All Radio Params ---
  // AT+SETRADIO=FREQ,BR,DEV,BW,PWR,PRE,SYNC,CRC
  if (u.startsWith("AT+SETRADIO=")) {
    String p = line.substring(12);
    p.trim();

    String parts[8];
    int partsCount = 0;

    while (partsCount < 8) {
      int comma = p.indexOf(',');
      if (comma < 0) {
        parts[partsCount++] = p;
        break;
      }
      parts[partsCount++] = p.substring(0, comma);
      p = p.substring(comma + 1);
    }

    if (partsCount != 8) { serialERR(); return true; }

    float freq, br, dev, bw;
    int8_t pwr;
    uint8_t pre;
    uint8_t syncH, syncL;
    bool crc;

    if (!parseFloat(parts[0], freq) || freq < 300.0 || freq > 928.0) { serialERR(); return true; }
    if (!parseFloat(parts[1], br) || br < 0.3 || br > 600.0) { serialERR(); return true; }
    if (!parseFloat(parts[2], dev) || dev < 1.0 || dev > 380.0) { serialERR(); return true; }
    if (!parseFloat(parts[3], bw)) { serialERR(); return true; }
    if (!parseInt8(parts[4], pwr) || !isValidTxPower(pwr)) { serialERR(); return true; }
    if (!parseUInt8(parts[5], pre) || !isValidPreamble(pre)) { serialERR(); return true; }
    
    // Sync word
    String syncStr = parts[6];
    syncStr.trim();
    if (syncStr.startsWith("0x") || syncStr.startsWith("0X")) {
      syncStr = syncStr.substring(2);
    }
    if (syncStr.length() != 4) { serialERR(); return true; }
    if (!parseHex8(syncStr.substring(0, 2), syncH)) { serialERR(); return true; }
    if (!parseHex8(syncStr.substring(2, 4), syncL)) { serialERR(); return true; }
    
    // CRC
    String crcStr = parts[7]; crcStr.trim();
    if (crcStr == "1" || crcStr.equalsIgnoreCase("ON") || crcStr.equalsIgnoreCase("TRUE")) {
      crc = true;
    } else if (crcStr == "0" || crcStr.equalsIgnoreCase("OFF") || crcStr.equalsIgnoreCase("FALSE")) {
      crc = false;
    } else {
      serialERR(); return true;
    }

    cfgCurrent.frequency   = freq;
    cfgCurrent.bitRate     = br;
    cfgCurrent.freqDev     = dev;
    cfgCurrent.rxBandwidth = VALID_BANDWIDTHS[findNearestBandwidth(bw)];
    cfgCurrent.txPower     = pwr;
    cfgCurrent.preambleLen = pre;
    cfgCurrent.syncWordH   = syncH;
    cfgCurrent.syncWordL   = syncL;
    cfgCurrent.crcEnabled  = crc;

    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // Unknown AT command
  if (startsWithAT(line)) return false;
  return false;
}

// =============================================================================
// Setup
// =============================================================================
void setup() {
  // oled_setup();
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(USB_BAUD);
  delay(1000);

  Serial.println();
  Serial.println(F("=========================================="));
  Serial.print(F("   "));
  Serial.println(F(CC1101_BOOT_TITLE));
  Serial.print(F("   "));
  Serial.println(F(CC1101_BOOT_SUBTITLE));
  Serial.println(F("=========================================="));
  Serial.println();

  

  beginRadioSpiBus();

  // EEPROM
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin failed"));
  }

  // Load or create config
  cfgDefault = makeDefaultConfig();
  cfgCurrent = cfgDefault;

  if (eepromLoad(cfgCurrent)) {
    Serial.println(F("[EEPROM] Config loaded"));
  } else {
    Serial.println(F("[EEPROM] Using defaults"));
    eepromSave(cfgCurrent);
  }

  // Init radio
  Serial.print(F("[RADIO] Initializing... "));
  if (applyConfig(cfgCurrent)) {
    Serial.println(F("OK"));
  } else {
    Serial.println(F("FAILED"));
    Serial.println(F("[WARN] Using defaults"));
    cfgCurrent = cfgDefault;
    if (!applyConfig(cfgCurrent)) {
      serialError(F("Radio init failed"));
      while (true) delay(1000);
    }
  }

  printConfigPretty(cfgCurrent);

  // Start receiving
  startReceive();

  oled_setup();
  beginRadioSpiBus();
  
  radio.standby();
  delay(10);
  bool ok = applyConfig(cfgCurrent);
  delay(100);
  
  radio.standby();
  delay(10);
  // Reinitializeaza complet modulul
  ok = applyConfig(cfgCurrent);
  if (ok) {
    startReceive();
    Serial.println(F("[READY] Bridge ON. Type AT+HELP for commands."));
    Serial.println(F("------------------------------------------"));
  } else {
    Serial.println(F("FAILED"));
  }
}


// =============================================================================
// Loop
// =============================================================================
void loop() {
  // LED heartbeat
  led1HzService();

  // ========== RADIO RX ==========
  pollReceivePins();

  if (radioReceived && !radioSleeping) {
    radioReceived = false;
    delay(2);
    
    uint8_t radioBuffer[64];
    int length = radio.getPacketLength();
    
    if (length > 0 && length <= 64) {
      int state = radio.readData(radioBuffer, length);
      
      if (state == RADIOLIB_ERR_NONE) {
        // Send to Serial
        Serial.write(radioBuffer, length);
        
        if (debugEnabled) {
          Serial.print(F("\n[RX] "));
          Serial.print(length);
          Serial.print(F(" bytes, RSSI: "));
          Serial.print(radio.getRSSI());
          Serial.print(F(" dBm, LQI: "));
          Serial.println(radio.getLQI());
        }
      }
    }
    
    startReceive();
  }

  // ========== SERIAL RX (AT commands or bridge data) ==========
  String line = readLineUSB();
  if (line.length() > 0) {
    if (startsWithAT(line)) {
      if (!handleAT(line)) {
        serialERR();
      }
    } else {
      if (!bridgeEnabled) {
        serialError(F("BRIDGE_OFF (send AT+BRIDGE=ON)"));
        return;
      }
      if (radioSleeping) {
        serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
        return;
      }

      // Bridge mode: send via radio with \r\n appended
      String dataWithCRLF = line + "\r\n";
      if (transmitData(dataWithCRLF.c_str(), dataWithCRLF.length())) {
        if (debugEnabled) {
          Serial.print(F("[TX] "));
          Serial.print(dataWithCRLF.length());
          Serial.println(F(" bytes"));
        }
      } else {
        if (debugEnabled) {
          Serial.println(F("[TX] FAILED"));
        }
      }
    }
  }
}
