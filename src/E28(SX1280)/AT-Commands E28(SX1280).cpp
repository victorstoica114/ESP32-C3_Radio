#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <RadioLib.h>
#include <EEPROM.h>
#include <math.h>
#include <U8g2lib.h>

// ============================================================================
// SX1280 PINOUT (as requested)
// ============================================================================
#define NSS     7
#define DIO1    1
#define NRST    10
#define BUSY    3

#define SPI_SCK   4
#define SPI_MISO  5
#define SPI_MOSI  6
#define SPI_SS    7

#define LED_GPIO 8

// ============================================================================
// OLED (SSD1306 128x64) - HW I2C
// ============================================================================
#define OLED_RESET U8X8_PIN_NONE
#define OLED_SDA   5
#define OLED_SCL   6

static void releaseOledI2CBus();
static void prepareRadioPinsForOled();
static void recoverOledI2CBus();
static uint8_t detectOledI2CAddress();

// SSD1306 128x64, hardware I2C
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, OLED_RESET, OLED_SCL, OLED_SDA);

static void drawCentered(const char* text, int baselineY, const uint8_t* font) {
  u8g2.setFont(font);
  int w = u8g2.getStrWidth(text);
  int x = (128 - w) / 2;
  if (x < 0) x = 0;
  u8g2.drawStr(x, baselineY, text);
}

static void drawOledSplash(uint8_t i2cAddress) {
  u8g2.setI2CAddress(i2cAddress);
  u8g2.setBusClock(400000);
  u8g2.begin();
  u8g2.setPowerSave(0);
  u8g2.setContrast(255);

  u8g2.clearBuffer();

  // Safe sizes for 2 lines on 128x64 without clipping
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("SX1280", 63, u8g2_font_logisoso18_tr);

  u8g2.sendBuffer();
}

static void oled_setup() {
  recoverOledI2CBus();

  uint8_t detectedAddress = detectOledI2CAddress();
  if (detectedAddress != 0) {
    drawOledSplash(detectedAddress);
    delay(20);
    drawOledSplash(detectedAddress);
  } else {
    drawOledSplash(0x3C << 1);
    delay(20);
    drawOledSplash(0x3D << 1);
  }

  releaseOledI2CBus();
}

static void beginRadioSpiBus() {
  SPI.end();
  delay(5);
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SPI_SS);
  SPI.setFrequency(1000000);
  delay(5);
}

static void prepareRadioPinsForOled() {
  SPI.end();
  delay(5);
  pinMode(NSS, OUTPUT);
  digitalWrite(NSS, HIGH);
  pinMode(NRST, OUTPUT);
  digitalWrite(NRST, HIGH);
  pinMode(DIO1, INPUT);
  pinMode(BUSY, INPUT);
  delay(5);
}

static void i2cReleasePin(uint8_t pin) {
  pinMode(pin, INPUT_PULLUP);
}

static void i2cDriveLow(uint8_t pin) {
  digitalWrite(pin, LOW);
  pinMode(pin, OUTPUT);
}

static void recoverOledI2CBus() {
  prepareRadioPinsForOled();
  Wire.end();
  delay(5);

  i2cReleasePin(OLED_SDA);
  i2cReleasePin(OLED_SCL);
  delay(5);

  for (uint8_t i = 0; i < 18; i++) {
    i2cDriveLow(OLED_SCL);
    delayMicroseconds(8);
    i2cReleasePin(OLED_SCL);
    delayMicroseconds(8);
  }

  i2cDriveLow(OLED_SDA);
  delayMicroseconds(8);
  i2cReleasePin(OLED_SCL);
  delayMicroseconds(8);
  i2cReleasePin(OLED_SDA);
  delay(5);
}

static uint8_t detectOledI2CAddress() {
  Wire.end();
  delay(2);
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(400000);
  delay(5);

  const uint8_t addresses[] = { 0x3C, 0x3D };
  for (uint8_t i = 0; i < sizeof(addresses); i++) {
    Wire.beginTransmission(addresses[i]);
    if (Wire.endTransmission() == 0) {
      Wire.end();
      delay(2);
      return addresses[i] << 1;
    }
  }

  Wire.end();
  delay(2);
  return 0;
}

static void releaseOledI2CBus() {
  delay(10);
  Wire.end();

  pinMode(OLED_SDA, INPUT);
  pinMode(OLED_SCL, INPUT);
  delay(5);
}

SX1280 radio = new Module(NSS, DIO1, NRST, BUSY);

// ============================================================================
// USER TUNABLE DEFAULTS
// ============================================================================
static constexpr bool debug_default_state = false;

// RX IRQ flag
volatile bool receivedFlag = false;

// RX enabled by default
static bool rxEnabled = true;
static bool radioSleeping = false;
static bool rxEnabledBeforeSleep = true;

// DEBUG runtime switch
static bool debugEnabled = debug_default_state;

// Last RSSI for AT+RSSI?
static float lastPacketRSSI = NAN;
static float lastPacketSNR = NAN;
static float lastFrequencyError = NAN;

// Radio ready state
static bool radioReady = false;

// CRC graceful handling
static bool   crcForcedOff = false;           // true when CRC ON was requested but not supported
static int16_t lastCrcSetStatus = 0;          // last status returned by setCRC()

// ============================================================================
// CONFIG (SX1280 ONLY) - defaults are valid for SX1280
// ============================================================================
struct RadioConfig {
  uint8_t  modemMode = 0;          // 0=LoRa, 1=GFSK, 2=FLRC, 3=BLE
  float    freqMHz   = 2410.5;     // MHz
  float    bwkHz     = 203.125;    // kHz
  uint8_t  sf        = 10;         // spreading factor
  uint8_t  cr        = 6;          // coding rate (RadioLib: 5..8)
  uint8_t  syncWord  = 0x12;       // private network example
  int8_t   pwrDbm    = -2;         // dBm
  uint16_t preamble  = 16;         // symbols
  bool     crcOn     = false;      // CRC OFF to match your working test
  uint16_t bitRateKbps = 800;      // GFSK/BLE bit rate
  float    freqDevKHz = 400.0;     // GFSK/BLE frequency deviation
  uint16_t flrcBitRateKbps = 650;  // FLRC bit rate
  uint8_t  flrcCr = 3;             // FLRC coding rate: 2=1/2, 3=3/4, 4=1/1
  uint8_t  dataShaping = RADIOLIB_SHAPING_0_5;
  bool     implicitHdr = false;
  uint8_t  implicitLen = 32;
  bool     iqInverted = false;
  bool     highSensitivity = false;
  uint8_t  gainControl = 0;        // 0=automatic, 1..13=manual gain
  bool     whitening = true;       // GFSK/BLE only
  uint32_t accessAddress = 0x8E89BED6UL; // BLE advertising access address
  bool     fixedPacketLen = false; // GFSK/FLRC only
  uint8_t  packetLen = 64;
  uint8_t  gfskSyncLen = 2;
  uint8_t  gfskSync[5] = {0x12, 0xAD, 0x00, 0x00, 0x00};
  bool     flrcSyncOn = true;
  uint8_t  flrcSync[4] = {0x2D, 0x01, 0x4B, 0x1D};
};

RadioConfig cfg;
const RadioConfig cfgDefault;   // compile-time defaults (above)

// ============================================================================
// EEPROM PERSISTENCE
// ============================================================================
static const uint32_t EEPROM_MAGIC   = 0x53313238UL; // "S128"
static const uint16_t EEPROM_VERSION = 0x0003;       // bump to invalidate old layouts
static const size_t   EEPROM_SIZE    = 256;

// Simple CRC32
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

struct EepromRecord {
  uint32_t magic;
  uint16_t version;
  uint16_t length;
  RadioConfig cfg;
  uint32_t crc;
};

static bool eepromLoadConfig(RadioConfig& out) {
  EepromRecord rec;
  EEPROM.get(0, rec);

  if (rec.magic != EEPROM_MAGIC) return false;
  if (rec.version != EEPROM_VERSION) return false;
  if (rec.length != (uint16_t)sizeof(RadioConfig)) return false;

  uint32_t c = crc32_calc((const uint8_t*)&rec.cfg, sizeof(RadioConfig));
  if (c != rec.crc) return false;

  out = rec.cfg;
  return true;
}

static bool eepromSaveConfig(const RadioConfig& in) {
  EepromRecord rec;
  rec.magic   = EEPROM_MAGIC;
  rec.version = EEPROM_VERSION;
  rec.length  = (uint16_t)sizeof(RadioConfig);
  rec.cfg     = in;
  rec.crc     = crc32_calc((const uint8_t*)&rec.cfg, sizeof(RadioConfig));

  EEPROM.put(0, rec);
  return EEPROM.commit();
}

// ============================================================================
// RX CALLBACK
// ============================================================================
#if defined(ESP8266)
  ICACHE_RAM_ATTR
#elif defined(ESP32)
  IRAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

// ============================================================================
// SERIAL HELPERS
// ============================================================================
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("#ERROR")); }
static inline void serialError(const __FlashStringHelper* msg) {
  Serial.print(F("#ERROR: "));
  Serial.println(msg);
}

// ============================================================================
// PARSERS
// ============================================================================
static bool parseFloat(const String& s, float& out) {
  char* endp = nullptr;
  out = strtof(s.c_str(), &endp);
  return endp && (*endp == '\0');
}

static bool parseInt(const String& s, long& out) {
  char* endp = nullptr;
  out = strtol(s.c_str(), &endp, 10);
  return endp && (*endp == '\0');
}

static bool parseHexByte(const String& s, uint8_t& out) {
  String t = s;
  t.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) t = t.substring(2);
  if (t.length() == 0 || t.length() > 2) return false;

  char* endp = nullptr;
  long v = strtol(t.c_str(), &endp, 16);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 0xFF) return false;

  out = (uint8_t)v;
  return true;
}

static bool parseBoolOnOff(const String& s, bool& out) {
  String t = s;
  t.trim();
  t.toUpperCase();
  if (t == "ON" || t == "1" || t == "TRUE")   { out = true;  return true; }
  if (t == "OFF" || t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

static bool parseHex32(const String& s, uint32_t& out) {
  String t = s;
  t.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) t = t.substring(2);
  if (t.length() == 0 || t.length() > 8) return false;

  char* endp = nullptr;
  unsigned long v = strtoul(t.c_str(), &endp, 16);
  if (!(endp && *endp == '\0')) return false;

  out = (uint32_t)v;
  return true;
}

static bool parseHexBytes(String s, uint8_t* out, uint8_t maxLen, uint8_t& outLen) {
  s.trim();
  s.replace(" ", "");
  s.replace(",", "");
  s.replace(":", "");
  s.replace("-", "");
  if (s.startsWith("0x") || s.startsWith("0X")) s = s.substring(2);
  if (s.length() == 0 || (s.length() % 2) != 0) return false;

  uint8_t len = (uint8_t)(s.length() / 2);
  if (len > maxLen) return false;

  for (uint8_t i = 0; i < len; i++) {
    uint8_t b;
    if (!parseHexByte(s.substring(i * 2, i * 2 + 2), b)) return false;
    out[i] = b;
  }

  outLen = len;
  return true;
}

static const __FlashStringHelper* modemModeName(uint8_t mode) {
  switch (mode) {
    case 0: return F("LORA");
    case 1: return F("GFSK");
    case 2: return F("FLRC");
    case 3: return F("BLE");
    default: return F("UNKNOWN");
  }
}

static bool parseModemMode(const String& s, uint8_t& out) {
  String t = s;
  t.trim();
  t.toUpperCase();
  if (t == "LORA") { out = 0; return true; }
  if (t == "GFSK") { out = 1; return true; }
  if (t == "FLRC") { out = 2; return true; }
  if (t == "BLE")  { out = 3; return true; }
  return false;
}

static const __FlashStringHelper* shapingName(uint8_t shaping) {
  switch (shaping) {
    case RADIOLIB_SHAPING_NONE: return F("NONE");
    case RADIOLIB_SHAPING_0_5:  return F("0.5");
    case RADIOLIB_SHAPING_1_0:  return F("1.0");
    default: return F("UNKNOWN");
  }
}

static bool parseShaping(const String& s, uint8_t& out) {
  String t = s;
  t.trim();
  t.toUpperCase();
  if (t == "NONE" || t == "OFF" || t == "0") { out = RADIOLIB_SHAPING_NONE; return true; }
  if (t == "0.5" || t == "05" || t == "BT0.5") { out = RADIOLIB_SHAPING_0_5; return true; }
  if (t == "1.0" || t == "1" || t == "BT1.0") { out = RADIOLIB_SHAPING_1_0; return true; }
  return false;
}

static bool isValidLoRaBandwidth(float bw) {
  return fabs(bw - 203.125f) < 0.01f ||
         fabs(bw - 406.25f) < 0.01f ||
         fabs(bw - 812.5f) < 0.01f ||
         fabs(bw - 1625.0f) < 0.01f;
}

static bool isValidPreambleForMode(uint8_t mode, long preamble) {
  if (mode == 0) {
    return preamble >= 2 && preamble <= 65534 && (preamble % 2) == 0;
  }
  if (mode == 1 || mode == 2) {
    return preamble >= 4 && preamble <= 32 && (preamble % 4) == 0;
  }
  return preamble >= 0 && preamble <= 65535;
}

static void printHexBytes(const uint8_t* data, uint8_t len) {
  for (uint8_t i = 0; i < len; i++) {
    if (data[i] < 0x10) Serial.print('0');
    Serial.print(data[i], HEX);
  }
}

static bool printApplyResult() {
  if (radioReady && crcForcedOff) {
    Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
  }
  radioReady ? serialOK() : serialERR();
  return true;
}

// ============================================================================
// PRINT CONFIG/HELP
// ============================================================================
static void printConfig() {
  Serial.println(F("CFG:"));
  Serial.print(F("  MODE="));     Serial.println(modemModeName(cfg.modemMode));
  Serial.print(F("  FREQ="));     Serial.print(cfg.freqMHz, 3); Serial.println(F(" MHz"));
  Serial.print(F("  BW="));       Serial.print(cfg.bwkHz, 3);   Serial.println(F(" kHz"));
  Serial.print(F("  SF="));       Serial.println(cfg.sf);
  Serial.print(F("  CR="));       Serial.println(cfg.cr);
  Serial.print(F("  SYNC=0x"));   Serial.println(cfg.syncWord, HEX);
  Serial.print(F("  PWR="));      Serial.print(cfg.pwrDbm);     Serial.println(F(" dBm"));
  Serial.print(F("  PREAMBLE=")); Serial.println(cfg.preamble);
  Serial.print(F("  CRC="));      Serial.println(cfg.crcOn ? F("ON") : F("OFF"));
  Serial.print(F("  BR="));       Serial.print(cfg.bitRateKbps); Serial.println(F(" kbps"));
  Serial.print(F("  DEV="));      Serial.print(cfg.freqDevKHz, 1); Serial.println(F(" kHz"));
  Serial.print(F("  FLRC_BR="));  Serial.print(cfg.flrcBitRateKbps); Serial.println(F(" kbps"));
  Serial.print(F("  FLRC_CR="));  Serial.println(cfg.flrcCr);
  Serial.print(F("  SHAPE="));    Serial.println(shapingName(cfg.dataShaping));
  Serial.print(F("  HEADER="));   Serial.println(cfg.implicitHdr ? F("IMPLICIT") : F("EXPLICIT"));
  Serial.print(F("  IMPLICIT_LEN=")); Serial.println(cfg.implicitLen);
  Serial.print(F("  IQ="));       Serial.println(cfg.iqInverted ? F("ON") : F("OFF"));
  Serial.print(F("  HIGHSENS=")); Serial.println(cfg.highSensitivity ? F("ON") : F("OFF"));
  Serial.print(F("  GAIN="));     Serial.println(cfg.gainControl);
  Serial.print(F("  WHITE="));    Serial.println(cfg.whitening ? F("ON") : F("OFF"));
  Serial.print(F("  ACCESS=0x")); Serial.println(cfg.accessAddress, HEX);
  Serial.print(F("  PKT="));      Serial.print(cfg.fixedPacketLen ? F("FIXED,") : F("VARIABLE,"));
  Serial.println(cfg.packetLen);
  Serial.print(F("  GFSK_SYNC="));
  if (cfg.gfskSyncLen == 0) Serial.println(F("OFF"));
  else { printHexBytes(cfg.gfskSync, cfg.gfskSyncLen); Serial.println(); }
  Serial.print(F("  FLRC_SYNC="));
  if (!cfg.flrcSyncOn) Serial.println(F("OFF"));
  else { printHexBytes(cfg.flrcSync, 4); Serial.println(); }
  Serial.print(F("  RX="));       Serial.println(rxEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  SLEEP="));    Serial.println(radioSleeping ? F("YES") : F("NO"));
  Serial.print(F("  DEBUG="));    Serial.println(debugEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  READY="));    Serial.println(radioReady ? F("YES") : F("NO"));
  Serial.print(F("  CRC_STATUS=")); Serial.println(lastCrcSetStatus);
  Serial.print(F("  CRC_FORCED_OFF=")); Serial.println(crcForcedOff ? F("YES") : F("NO"));
}

static void printHelp() {
  Serial.println(F("AT commands for SX1280 (RadioLib)"));
  Serial.println(F(""));
  Serial.println(F("Core:"));
  Serial.println(F("  AT                  -> OK"));
  Serial.println(F("  AT? / AT+HELP       -> show this help"));
  Serial.println(F("  AT+CFG?             -> print current config + status"));
  Serial.println(F("  AT+APPLY            -> HW reset + apply current config + start RX (if RX=ON)"));
  Serial.println(F("  AT+RESET            -> HW reset + re-apply current config"));
  Serial.println(F("  AT+DEFAULT          -> load defaults + auto save + auto apply"));
  Serial.println(F(""));
  Serial.println(F("Parameters (set/query) - setters auto save + auto apply:"));
  Serial.println(F("  AT+MODE=LORA|GFSK|FLRC|BLE / AT+MODE?"));
  Serial.println(F("  AT+FREQ=<MHz>       / AT+FREQ?"));
  Serial.println(F("  AT+BW=<kHz>         / AT+BW?     (LoRa: 203.125, 406.25, 812.5, 1625)"));
  Serial.println(F("  AT+SF=<5..12>       / AT+SF?     (LoRa)"));
  Serial.println(F("  AT+CR=<4..8>        / AT+CR?     (LoRa)"));
  Serial.println(F("  AT+SYNC=<hex>       / AT+SYNC?   (LoRa, e.g. 0x12)"));
  Serial.println(F("  AT+PWR=<dBm>        / AT+PWR?    (can be negative)"));
  Serial.println(F("  AT+PREAMBLE=<n>     / AT+PREAMBLE?"));
  Serial.println(F("  AT+CRC=ON|OFF       / AT+CRC?"));
  Serial.println(F("  AT+HEADER=EXPLICIT  / AT+HEADER? (LoRa)"));
  Serial.println(F("  AT+HEADER=IMPLICIT,<1..255>"));
  Serial.println(F("  AT+IQ=ON|OFF        / AT+IQ?     (LoRa)"));
  Serial.println(F("  AT+BR=<kbps>        / AT+BR?     (GFSK/BLE: 125..2000 presets)"));
  Serial.println(F("  AT+DEV=<kHz>        / AT+DEV?    (GFSK/BLE: 62.5..1000)"));
  Serial.println(F("  AT+FLRCBR=<kbps>    / AT+FLRCBR? (260,325,520,650,1000,1300)"));
  Serial.println(F("  AT+FLRCCR=<2..4>    / AT+FLRCCR? (FLRC: 2=1/2, 3=3/4, 4=1/1)"));
  Serial.println(F("  AT+SHAPE=NONE|0.5|1.0 / AT+SHAPE? (GFSK/FLRC/BLE)"));
  Serial.println(F("  AT+WHITE=ON|OFF     / AT+WHITE?  (GFSK/BLE)"));
  Serial.println(F("  AT+ACCESS=<hex32>   / AT+ACCESS? (BLE)"));
  Serial.println(F("  AT+PKT=VARIABLE,<1..255> / AT+PKT? (GFSK/FLRC)"));
  Serial.println(F("  AT+PKT=FIXED,<1..255>"));
  Serial.println(F("  AT+GFSKSYNC=<hex 1..5 bytes>     / AT+GFSKSYNC?"));
  Serial.println(F("  AT+FLRCSYNC=OFF|<hex 4 bytes>    / AT+FLRCSYNC?"));
  Serial.println(F("  AT+HIGHSENS=ON|OFF  / AT+HIGHSENS?"));
  Serial.println(F("  AT+GAIN=<0..13>     / AT+GAIN?   (0=auto)"));
  Serial.println(F(""));
  Serial.println(F("Batch set (auto save + auto apply):"));
  Serial.println(F("  AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<PRE>,<CRC>"));
  Serial.println(F("    Example: AT+SET=2410.5,203.125,10,6,0x12,-2,16,OFF"));
  Serial.println(F(""));
  Serial.println(F("RX control:"));
  Serial.println(F("  AT+RX=ON            -> start RX"));
  Serial.println(F("  AT+RX=OFF           -> standby (stop RX)"));
  Serial.println(F("  AT+SLEEP            -> sleep (low power)"));
  Serial.println(F("  AT+WAKE             -> wake + restore RX"));
  Serial.println(F(""));
  Serial.println(F("Diagnostics:"));
  Serial.println(F("  AT+RSSI?            -> last packet RSSI"));
  Serial.println(F("  AT+SNR?             -> last packet SNR (LoRa/ranging)"));
  Serial.println(F("  AT+FERR?            -> last packet frequency error"));
  Serial.println(F("  AT+CAD?             -> channel activity detection (LoRa)"));
  Serial.println(F("  AT+RANDOM?          -> RadioLib SX128x returns 0"));
  Serial.println(F("  AT+STATUS?          -> local firmware/radio status"));
  Serial.println(F("  AT+DEBUG            -> toggle debug"));
  Serial.println(F("  AT+DEBUG=ON/OFF      / AT+DEBUG?"));
  Serial.println(F(""));
  Serial.println(F("Notes:"));
  Serial.println(F("  - Some SX1280 configs may not support CRC=ON via RadioLib;"));
  Serial.println(F("    in that case the firmware forces CRC=OFF and prints a WARN."));
}

// ============================================================================
// RADIO APPLY/RESET
// ============================================================================
static bool resetRadioHardware() {
  // SX1280 reset: pulse LOW on NRST
  pinMode(NRST, OUTPUT);
  digitalWrite(NRST, HIGH);
  delay(2);
  digitalWrite(NRST, LOW);
  delay(50);
  digitalWrite(NRST, HIGH);
  delay(20);
  return true;
}

static bool applyConfigToRadioNoReset() {
  crcForcedOff = false;
  lastCrcSetStatus = RADIOLIB_ERR_NONE;

  int st = RADIOLIB_ERR_UNKNOWN;
  if (cfg.modemMode == 0) {
    st = radio.begin(cfg.freqMHz, cfg.bwkHz, cfg.sf, cfg.cr, cfg.syncWord, cfg.pwrDbm, cfg.preamble);
  } else if (cfg.modemMode == 1) {
    st = radio.beginGFSK(cfg.freqMHz, cfg.bitRateKbps, cfg.freqDevKHz, cfg.pwrDbm, cfg.preamble);
  } else if (cfg.modemMode == 2) {
    st = radio.beginFLRC(cfg.freqMHz, cfg.flrcBitRateKbps, cfg.flrcCr, cfg.pwrDbm, cfg.preamble, cfg.dataShaping);
  } else if (cfg.modemMode == 3) {
    st = radio.beginBLE(cfg.freqMHz, cfg.bitRateKbps, cfg.freqDevKHz, cfg.pwrDbm, cfg.dataShaping);
  }

  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[SX1280] begin failed, code "));
      Serial.println(st);
    }
    return false;
  }
  radioSleeping = false;

  if (cfg.modemMode == 0) {
    st = cfg.implicitHdr ? radio.implicitHeader(cfg.implicitLen) : radio.explicitHeader();
    if (st != RADIOLIB_ERR_NONE) return false;

    st = radio.invertIQ(cfg.iqInverted);
    if (st != RADIOLIB_ERR_NONE) return false;

  } else if (cfg.modemMode == 1) {
    st = radio.setDataShaping(cfg.dataShaping);
    if (st != RADIOLIB_ERR_NONE) return false;

    st = radio.setWhitening(cfg.whitening);
    if (st != RADIOLIB_ERR_NONE) return false;

    st = radio.setSyncWord(cfg.gfskSync, cfg.gfskSyncLen);
    if (st != RADIOLIB_ERR_NONE) return false;

    st = cfg.fixedPacketLen ? radio.fixedPacketLengthMode(cfg.packetLen) : radio.variablePacketLengthMode(cfg.packetLen);
    if (st != RADIOLIB_ERR_NONE) return false;

  } else if (cfg.modemMode == 2) {
    st = radio.setDataShaping(cfg.dataShaping);
    if (st != RADIOLIB_ERR_NONE) return false;

    uint8_t flrcLen = cfg.flrcSyncOn ? 4 : 0;
    st = radio.setSyncWord(cfg.flrcSync, flrcLen);
    if (st != RADIOLIB_ERR_NONE) return false;

    st = cfg.fixedPacketLen ? radio.fixedPacketLengthMode(cfg.packetLen) : radio.variablePacketLengthMode(cfg.packetLen);
    if (st != RADIOLIB_ERR_NONE) return false;

  } else if (cfg.modemMode == 3) {
    st = radio.setWhitening(cfg.whitening);
    if (st != RADIOLIB_ERR_NONE) return false;

    st = radio.setAccessAddress(cfg.accessAddress);
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  st = radio.setHighSensitivityMode(cfg.highSensitivity);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setGainControl(cfg.gainControl);
  if (st != RADIOLIB_ERR_NONE) return false;

  uint8_t crcLen = 0;
  if (cfg.crcOn) {
    crcLen = (cfg.modemMode == 3) ? 3 : 2;
  }

  // Apply CRC (GRACEFUL)
  st = radio.setCRC(crcLen);
  lastCrcSetStatus = st;

  if (st != RADIOLIB_ERR_NONE) {
    // If CRC ON was requested but not supported, force OFF and continue.
    if (cfg.crcOn) {
      crcForcedOff = true;
      cfg.crcOn = false;  // keep runtime cfg consistent

      // Try to explicitly disable CRC (best effort)
      (void)radio.setCRC(0);

      if (debugEnabled) {
        Serial.print(F("[SX1280] setCRC(ON) not supported (code "));
        Serial.print(st);
        Serial.println(F("). Forced CRC=OFF."));
      }
    } else {
      // CRC OFF failed (unexpected) => treat as real failure
      if (debugEnabled) {
        Serial.print(F("[SX1280] setCRC(OFF) failed, code "));
        Serial.println(st);
      }
      return false;
    }
  }

  radio.setPacketReceivedAction(onRxDone);

  if (rxEnabled) {
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.print(F("[SX1280] startReceive failed, code "));
        Serial.println(st);
      }
      return false;
    }
  }

  return true;
}

static bool resetRadioByPinAndReinitAndApply() {
  beginRadioSpiBus();
  resetRadioHardware();
  return applyConfigToRadioNoReset();
}

static bool persistAndReapply() {
  // Apply first (this may force CRC OFF), then save the FINAL config to EEPROM
  bool ok = resetRadioByPinAndReinitAndApply();
  if (!ok) return false;

  // Save final (possibly corrected) cfg
  if (!eepromSaveConfig(cfg)) return false;

  return true;
}

static bool putRadioToSleep() {
  if (!radioReady) return false;

  rxEnabledBeforeSleep = rxEnabled;
  rxEnabled = false;
  receivedFlag = false;
  radio.clearPacketReceivedAction();

  int st = radio.sleep();
  if (st != RADIOLIB_ERR_NONE) return false;

  radioSleeping = true;
  return true;
}

static bool wakeRadioFromSleep() {
  int st = radio.standby();
  if (st != RADIOLIB_ERR_NONE) return false;

  radioSleeping = false;
  radioReady = true;
  rxEnabled = rxEnabledBeforeSleep;

  if (rxEnabled) {
    receivedFlag = false;
    radio.setPacketReceivedAction(onRxDone);
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  return true;
}

// ============================================================================
// SERIAL LINE READER
// ============================================================================
static String readSerialLineNonBlocking() {
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
      if (buf.length() < 256) buf += c;
    }
  }
  return "";
}

// ============================================================================
// AT HANDLER (case-insensitive)
// ============================================================================
static bool handleAT(String lineRaw) {
  String line = lineRaw;
  line.trim();

  String u = line;
  u.toUpperCase();

  // Core
  if (u == "AT") { serialOK(); return true; }
  if (u == "AT?" || u == "AT+HELP") { printHelp(); serialOK(); return true; }
  if (u == "AT+CFG?") { printConfig(); serialOK(); return true; }

  // APPLY / RESET / DEFAULT
  if (u == "AT+APPLY") {
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) {
      Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    }
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u == "AT+RESET") {
    radioReady = resetRadioByPinAndReinitAndApply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u == "AT+DEFAULT") {
    cfg = cfgDefault;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) {
      Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    }
    radioReady ? serialOK() : serialERR();
    return true;
  }

  // RX control
  if (u == "AT+RX=OFF") {
    rxEnabled = false;
    int st = radio.standby();
    radioSleeping = false;
    (st == RADIOLIB_ERR_NONE) ? serialOK() : serialERR();
    return true;
  }
  if (u == "AT+RX=ON") {
    rxEnabled = true;
    radioSleeping = false;
    radioReady = resetRadioByPinAndReinitAndApply();
    radioReady ? serialOK() : serialERR();
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

  // RSSI
  if (u == "AT+RSSI?") {
    if (isnan(lastPacketRSSI)) Serial.println(F("RSSI=N/A"));
    else { Serial.print(F("RSSI=")); Serial.println(lastPacketRSSI, 2); }
    serialOK();
    return true;
  }

  if (u == "AT+SNR?") {
    if (isnan(lastPacketSNR)) Serial.println(F("SNR=N/A"));
    else { Serial.print(F("SNR=")); Serial.println(lastPacketSNR, 2); }
    serialOK();
    return true;
  }

  if (u == "AT+FERR?") {
    if (isnan(lastFrequencyError)) Serial.println(F("FERR=N/A"));
    else { Serial.print(F("FERR=")); Serial.println(lastFrequencyError, 2); }
    serialOK();
    return true;
  }

  if (u == "AT+CAD?") {
    if (cfg.modemMode != 0) {
      serialError(F("CAD is available only in LORA mode"));
      serialERR();
      return true;
    }

    radio.clearPacketReceivedAction();
    int st = radio.scanChannel();
    if (rxEnabled && !radioSleeping) {
      receivedFlag = false;
      radio.setPacketReceivedAction(onRxDone);
      radio.startReceive();
    }
    if (st == RADIOLIB_CHANNEL_FREE) {
      Serial.println(F("CAD=FREE"));
      serialOK();
    } else if (st == RADIOLIB_PREAMBLE_DETECTED || st == RADIOLIB_LORA_DETECTED) {
      Serial.println(F("CAD=DETECTED"));
      serialOK();
    } else {
      Serial.print(F("#ERROR: CAD_ERROR="));
      Serial.println(st);
      serialERR();
    }
    return true;
  }

  if (u == "AT+RANDOM?") {
    Serial.println(F("RANDOM=0x00"));
    Serial.println(F("NOTE=RadioLib SX128x randomByte() is a compatibility stub"));
    serialOK();
    return true;
  }

  if (u == "AT+STATUS?") {
    Serial.print(F("READY=")); Serial.println(radioReady ? F("YES") : F("NO"));
    Serial.print(F("RX=")); Serial.println(rxEnabled ? F("ON") : F("OFF"));
    Serial.print(F("SLEEP=")); Serial.println(radioSleeping ? F("YES") : F("NO"));
    Serial.print(F("MODE=")); Serial.println(modemModeName(cfg.modemMode));
    if (radioReady && !radioSleeping) {
      Serial.print(F("RSSI_NOW="));
      Serial.println(radio.getRSSI(false), 2);
    }
    serialOK();
    return true;
  }

  // DEBUG
  if (u == "AT+DEBUG?") {
    Serial.print(F("DEBUG="));
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG") {
    debugEnabled = !debugEnabled;
    Serial.print(F("DEBUG="));
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }

  // Queries
  if (u == "AT+MODE?")     { Serial.print(F("MODE=")); Serial.println(modemModeName(cfg.modemMode)); serialOK(); return true; }
  if (u == "AT+FREQ?")     { Serial.print(F("FREQ=")); Serial.println(cfg.freqMHz, 3); serialOK(); return true; }
  if (u == "AT+BW?")       { Serial.print(F("BW=")); Serial.println(cfg.bwkHz, 3); serialOK(); return true; }
  if (u == "AT+SF?")       { Serial.print(F("SF=")); Serial.println(cfg.sf); serialOK(); return true; }
  if (u == "AT+CR?")       { Serial.print(F("CR=")); Serial.println(cfg.cr); serialOK(); return true; }
  if (u == "AT+SYNC?")     { Serial.print(F("SYNC=0x")); Serial.println(cfg.syncWord, HEX); serialOK(); return true; }
  if (u == "AT+PWR?")      { Serial.print(F("PWR=")); Serial.println(cfg.pwrDbm); serialOK(); return true; }
  if (u == "AT+PREAMBLE?") { Serial.print(F("PREAMBLE=")); Serial.println(cfg.preamble); serialOK(); return true; }
  if (u == "AT+CRC?")      { Serial.print(F("CRC="));  Serial.println(cfg.crcOn ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+BR?")       { Serial.print(F("BR=")); Serial.println(cfg.bitRateKbps); serialOK(); return true; }
  if (u == "AT+DEV?")      { Serial.print(F("DEV=")); Serial.println(cfg.freqDevKHz, 1); serialOK(); return true; }
  if (u == "AT+FLRCBR?")   { Serial.print(F("FLRCBR=")); Serial.println(cfg.flrcBitRateKbps); serialOK(); return true; }
  if (u == "AT+FLRCCR?")   { Serial.print(F("FLRCCR=")); Serial.println(cfg.flrcCr); serialOK(); return true; }
  if (u == "AT+SHAPE?")    { Serial.print(F("SHAPE=")); Serial.println(shapingName(cfg.dataShaping)); serialOK(); return true; }
  if (u == "AT+HEADER?")   {
    Serial.print(F("HEADER=")); Serial.println(cfg.implicitHdr ? F("IMPLICIT") : F("EXPLICIT"));
    if (cfg.implicitHdr) { Serial.print(F("LEN=")); Serial.println(cfg.implicitLen); }
    serialOK();
    return true;
  }
  if (u == "AT+IQ?")       { Serial.print(F("IQ=")); Serial.println(cfg.iqInverted ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+HIGHSENS?") { Serial.print(F("HIGHSENS=")); Serial.println(cfg.highSensitivity ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+GAIN?")     { Serial.print(F("GAIN=")); Serial.println(cfg.gainControl); serialOK(); return true; }
  if (u == "AT+WHITE?")    { Serial.print(F("WHITE=")); Serial.println(cfg.whitening ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+ACCESS?")   { Serial.print(F("ACCESS=0x")); Serial.println(cfg.accessAddress, HEX); serialOK(); return true; }
  if (u == "AT+PKT?")      {
    Serial.print(F("PKT=")); Serial.print(cfg.fixedPacketLen ? F("FIXED,") : F("VARIABLE,"));
    Serial.println(cfg.packetLen);
    serialOK();
    return true;
  }
  if (u == "AT+GFSKSYNC?") {
    Serial.print(F("GFSKSYNC="));
    if (cfg.gfskSyncLen == 0) Serial.println(F("OFF"));
    else { printHexBytes(cfg.gfskSync, cfg.gfskSyncLen); Serial.println(); }
    serialOK();
    return true;
  }
  if (u == "AT+FLRCSYNC?") {
    Serial.print(F("FLRCSYNC="));
    if (!cfg.flrcSyncOn) Serial.println(F("OFF"));
    else { printHexBytes(cfg.flrcSync, 4); Serial.println(); }
    serialOK();
    return true;
  }

  // Mode and extended parameter setters
  if (u.startsWith("AT+MODE=")) {
    uint8_t mode;
    if (!parseModemMode(line.substring(8), mode)) { serialERR(); return true; }
    cfg.modemMode = mode;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u == "AT+HEADER=EXPLICIT") {
    cfg.implicitHdr = false;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+HEADER=IMPLICIT")) {
    int comma = line.indexOf(',');
    if (comma < 0) { serialERR(); return true; }
    long len;
    if (!parseInt(line.substring(comma + 1), len) || len < 1 || len > 255) { serialERR(); return true; }
    cfg.implicitHdr = true;
    cfg.implicitLen = (uint8_t)len;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+IQ=")) {
    bool v; if (!parseBoolOnOff(line.substring(6), v)) { serialERR(); return true; }
    cfg.iqInverted = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+BR=")) {
    long v; if (!parseInt(line.substring(6), v)) { serialERR(); return true; }
    if (!(v == 125 || v == 250 || v == 400 || v == 500 || v == 800 || v == 1000 || v == 1600 || v == 2000)) {
      serialERR();
      return true;
    }
    cfg.bitRateKbps = (uint16_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+DEV=")) {
    float v; if (!parseFloat(line.substring(7), v) || v < 62.5f || v > 1000.0f) { serialERR(); return true; }
    cfg.freqDevKHz = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+FLRCBR=")) {
    long v; if (!parseInt(line.substring(10), v)) { serialERR(); return true; }
    if (!(v == 260 || v == 325 || v == 520 || v == 650 || v == 1000 || v == 1300)) {
      serialERR();
      return true;
    }
    cfg.flrcBitRateKbps = (uint16_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+FLRCCR=")) {
    long v; if (!parseInt(line.substring(10), v) || v < 2 || v > 4) { serialERR(); return true; }
    cfg.flrcCr = (uint8_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+SHAPE=")) {
    uint8_t v; if (!parseShaping(line.substring(9), v)) { serialERR(); return true; }
    cfg.dataShaping = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+HIGHSENS=")) {
    bool v; if (!parseBoolOnOff(line.substring(12), v)) { serialERR(); return true; }
    cfg.highSensitivity = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+GAIN=")) {
    long v; if (!parseInt(line.substring(8), v) || v < 0 || v > 13) { serialERR(); return true; }
    cfg.gainControl = (uint8_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+WHITE=")) {
    bool v; if (!parseBoolOnOff(line.substring(9), v)) { serialERR(); return true; }
    cfg.whitening = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+ACCESS=")) {
    uint32_t v; if (!parseHex32(line.substring(10), v)) { serialERR(); return true; }
    cfg.accessAddress = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+PKT=")) {
    String p = line.substring(7);
    int comma = p.indexOf(',');
    if (comma < 0) { serialERR(); return true; }
    String mode = p.substring(0, comma);
    mode.trim();
    mode.toUpperCase();
    long len;
    if (!parseInt(p.substring(comma + 1), len) || len < 1 || len > 255) { serialERR(); return true; }
    if (mode == "VARIABLE") cfg.fixedPacketLen = false;
    else if (mode == "FIXED") cfg.fixedPacketLen = true;
    else { serialERR(); return true; }
    cfg.packetLen = (uint8_t)len;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+GFSKSYNC=")) {
    String p = line.substring(12);
    p.trim();
    p.toUpperCase();
    if (p == "OFF") {
      serialERR();
      return true;
    } else {
      uint8_t len = 0;
      uint8_t bytes[5] = {0};
      if (!parseHexBytes(p, bytes, 5, len) || len < 1) { serialERR(); return true; }
      cfg.gfskSyncLen = len;
      for (uint8_t i = 0; i < 5; i++) cfg.gfskSync[i] = (i < len) ? bytes[i] : 0;
    }
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  if (u.startsWith("AT+FLRCSYNC=")) {
    String p = line.substring(12);
    p.trim();
    p.toUpperCase();
    if (p == "OFF") {
      cfg.flrcSyncOn = false;
    } else {
      uint8_t len = 0;
      uint8_t bytes[4] = {0};
      if (!parseHexBytes(p, bytes, 4, len) || len != 4) { serialERR(); return true; }
      cfg.flrcSyncOn = true;
      for (uint8_t i = 0; i < 4; i++) cfg.flrcSync[i] = bytes[i];
    }
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  // CRC setters (warn if forced OFF)
  if (u == "AT+CRC=ON")  {
    cfg.crcOn = true;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) {
      Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    }
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u == "AT+CRC=OFF") {
    cfg.crcOn = false;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }

  // Setters
  if (u.startsWith("AT+FREQ=")) {
    float v; if (!parseFloat(line.substring(8), v) || v < 2400.0f || v > 2500.0f) { serialERR(); return true; }
    cfg.freqMHz = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+BW=")) {
    float v; if (!parseFloat(line.substring(6), v) || !isValidLoRaBandwidth(v)) { serialERR(); return true; }
    cfg.bwkHz = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+SF=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 5 || v > 12) { serialERR(); return true; }
    cfg.sf = (uint8_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+CR=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 4 || v > 8) { serialERR(); return true; }
    cfg.cr = (uint8_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+SYNC=")) {
    uint8_t v; if (!parseHexByte(line.substring(8), v)) { serialERR(); return true; }
    cfg.syncWord = v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+PWR=")) {
    long v; if (!parseInt(line.substring(7), v) || v < -18 || v > 13) { serialERR(); return true; }
    cfg.pwrDbm = (int8_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }
  if (u.startsWith("AT+PREAMBLE=")) {
    long v; if (!parseInt(line.substring(12), v) || !isValidPreambleForMode(cfg.modemMode, v)) { serialERR(); return true; }
    cfg.preamble = (uint16_t)v;
    radioReady = persistAndReapply();
    return printApplyResult();
  }

  // Batch set: AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<PRE>,<CRC>
  if (u.startsWith("AT+SET=")) {
    String p = line.substring(7);

    String parts[8];
    for (int i = 0; i < 8; i++) parts[i] = "";

    int idx = 0;
    while (idx < 8) {
      int c = p.indexOf(',');
      if (c < 0) { parts[idx++] = p; break; }
      parts[idx++] = p.substring(0, c);
      p = p.substring(c + 1);
    }
    if (idx != 8) { serialERR(); return true; }

    for (int i = 0; i < 8; i++) parts[i].trim();

    float f, bw;
    long sf, cr, pwr, pre;
    uint8_t sync;
    bool crcOn;

    if (!parseFloat(parts[0], f) || f < 2400.0f || f > 2500.0f) { serialERR(); return true; }
    if (!parseFloat(parts[1], bw) || !isValidLoRaBandwidth(bw)) { serialERR(); return true; }
    if (!parseInt(parts[2], sf) || sf < 5 || sf > 12) { serialERR(); return true; }
    if (!parseInt(parts[3], cr) || cr < 4 || cr > 8) { serialERR(); return true; }
    if (!parseHexByte(parts[4], sync)) { serialERR(); return true; }
    if (!parseInt(parts[5], pwr) || pwr < -18 || pwr > 13) { serialERR(); return true; }
    if (!parseInt(parts[6], pre) || !isValidPreambleForMode(0, pre)) { serialERR(); return true; }
    if (!parseBoolOnOff(parts[7], crcOn)) { serialERR(); return true; }

    cfg.modemMode = 0;
    cfg.freqMHz   = f;
    cfg.bwkHz     = bw;
    cfg.sf        = (uint8_t)sf;
    cfg.cr        = (uint8_t)cr;
    cfg.syncWord  = sync;
    cfg.pwrDbm    = (int8_t)pwr;
    cfg.preamble  = (uint16_t)pre;
    cfg.crcOn     = crcOn;

    // Apply + persist (CRC may be forced OFF)
    radioReady = persistAndReapply();

    if (radioReady && crcForcedOff) {
      Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    }

    radioReady ? serialOK() : serialERR();
    return true;
  }

  // Unknown AT command
  if (u.startsWith("AT")) return false;
  return false;
}

// ============================================================================
// SETUP/LOOP
// ============================================================================
void setup() {
  oled_setup();
  Serial.begin(9600);
  delay(150);

  beginRadioSpiBus();

  Serial.println();
  Serial.println(F("[BOOT] Starting SX1280 AT firmware"));

  pinMode(LED_GPIO, OUTPUT);
  digitalWrite(LED_GPIO, LOW);

  // EEPROM init
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin() failed! Using RAM defaults only."));
  }

  // Load last valid cfg from EEPROM, otherwise defaults
  bool loaded = eepromLoadConfig(cfg);
  if (!loaded) {
    cfg = cfgDefault;
    (void)eepromSaveConfig(cfg);
  }

  rxEnabled = true;
  debugEnabled = debug_default_state;

  Serial.print(F("[BOOT] DEBUG default = "));
  Serial.println(debugEnabled ? F("ON") : F("OFF"));

  Serial.print(F("[EEPROM] Loaded config = "));
  Serial.println(loaded ? F("YES") : F("NO (using defaults)"));

  Serial.print(F("[SX1280] Applying config... "));
  radioReady = resetRadioByPinAndReinitAndApply();
  Serial.println(radioReady ? F("OK") : F("FAILED"));

  if (!radioReady) {
    Serial.println(F("[HINT] Verify NSS/DIO1/NRST/BUSY wiring and pins."));
    Serial.println(F("[HINT] You can still use AT commands and run AT+APPLY after setting params."));
  }

  Serial.println(F("[READY] Type AT+HELP"));
}

void loop() {
  // LED blink 1 Hz (toggle every 500 ms)
  static unsigned long lastLed = 0;
  static bool ledState = false;
  unsigned long now = millis();
  if (now - lastLed >= 500) {
    lastLed = now;
    ledState = !ledState;
    digitalWrite(LED_GPIO, ledState ? HIGH : LOW);
  }

  // Serial line -> AT or TX payload
  String line = readSerialLineNonBlocking();
  if (line.length() > 0) {
    if (line.startsWith("AT") || line.startsWith("at")) {
      if (!handleAT(line)) serialERR();
    } else {
      // non-AT line = radio TX payload
      if (radioSleeping) {
        serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
      } else if (!radioReady) {
        serialError(F("RADIO_NOT_READY (set config and run AT+APPLY)"));
      } else {
        radio.clearPacketReceivedAction();

        if (debugEnabled) {
          Serial.print(F("[SX1280] TX -> "));
          Serial.println(line);
        }

        int tx = radio.transmit(line);

        if (debugEnabled) {
          if (tx == RADIOLIB_ERR_NONE) Serial.println(F("[SX1280] TX OK"));
          else { Serial.print(F("[SX1280] TX failed, code ")); Serial.println(tx); }
        }

        // Restore RX if enabled
        if (rxEnabled) {
          radio.setPacketReceivedAction(onRxDone);
          radio.startReceive();
        }
      }
    }
  }

  // Radio RX -> Serial
  if (receivedFlag && !radioSleeping) {
    receivedFlag = false;

    String str;
    int rx = radio.readData(str);

    if (rx == RADIOLIB_ERR_NONE) {
      lastPacketRSSI = radio.getRSSI();
      if (cfg.modemMode == 0) {
        lastPacketSNR = radio.getSNR();
        lastFrequencyError = radio.getFrequencyError();
      } else {
        lastPacketSNR = NAN;
        lastFrequencyError = NAN;
      }

      if (debugEnabled) {
        Serial.print(F("[SX1280] RX DATA: "));
        Serial.println(str);

        Serial.print(F("[SX1280] RSSI: "));
        Serial.print(lastPacketRSSI, 2);
        Serial.println(F(" dBm"));

        if (cfg.modemMode == 0) {
          Serial.print(F("[SX1280] SNR:  "));
          Serial.print(lastPacketSNR, 2);
          Serial.println(F(" dB"));

          Serial.print(F("[SX1280] FERR: "));
          Serial.print(lastFrequencyError, 2);
          Serial.println(F(" Hz"));
        }

        Serial.println(F("[SX1280] Packet received!"));
      } else {
        // DEBUG OFF: print ONLY the payload
        Serial.println(str);
      }

    } else if (rx == RADIOLIB_ERR_CRC_MISMATCH) {
      if (debugEnabled) Serial.println(F("[SX1280] CRC error!"));
    } else {
      if (debugEnabled) {
        Serial.print(F("[SX1280] RX failed, code "));
        Serial.println(rx);
      }
    }

    if (rxEnabled) {
      radio.startReceive();
    }
  }
}
