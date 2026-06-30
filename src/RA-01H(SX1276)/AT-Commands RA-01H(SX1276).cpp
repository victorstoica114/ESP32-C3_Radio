#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <EEPROM.h>
#include <math.h>
#include <U8g2lib.h>

// ------------------ OLED ------------------
#define OLED_RESET U8X8_PIN_NONE
#define OLED_SDA   5
#define OLED_SCL   6

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, OLED_RESET, OLED_SCL, OLED_SDA);

static void drawCentered(const char* text, int baselineY, const uint8_t* font) {
  u8g2.setFont(font);
  int w = u8g2.getStrWidth(text);
  int x = (128 - w) / 2;
  if (x < 0) x = 0;
  u8g2.drawStr(x, baselineY, text);
}

static void oled_setup() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setBusClock(400000);

  u8g2.clearBuffer();
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("SX1276", 63, u8g2_font_logisoso18_tr);
  u8g2.sendBuffer();
}

// ------------------ PINOUT (SX1276 / RA-01) ------------------
#define NSS     7
#define DIO0    3     // SX1276 uses DIO0 for RX/TX done (not DIO1)
#define RESET   10
#define DIO1    1     // Optional, used for some modes

// SPI pins
#define SPI_SCK   4
#define SPI_MISO  5
#define SPI_MOSI  6
#define SPI_SS    7

#define LED_GPIO 8

// SX1276 instead of SX1262
SX1276 radio = new Module(NSS, DIO0, RESET, DIO1);

// ------------------ USER TUNABLE DEFAULTS ------------------
static constexpr bool debug_default_state = false;

// ------------------ RX IRQ FLAG ------------------
volatile bool receivedFlag = false;

// ------------------ CONFIG ------------------
struct RadioConfig {
  float    freqMHz     = 433.0;   // MHz (RA-01 is 433MHz)
  float    bwkHz       = 125.0;   // kHz
  uint8_t  sf          = 10;      // 6..12
  uint8_t  cr          = 6;       // 5..8
  uint8_t  syncWord    = 0x14;    // LoRa sync word
  int8_t   pwrDbm      = 10;      // dBm (-4 to +20 for SX1276)
  float    currLimitMA = 100.0;   // mA (0 = skip)
  uint16_t preamble    = 15;
  uint8_t  gain        = 0;       // 0=AGC, 1..6 manual LNA gain
  bool     crcOn       = true;
};

RadioConfig cfg;
const RadioConfig cfgDefault;

bool rxEnabled = true;
bool radioSleeping = false;
bool rxEnabledBeforeSleep = true;
bool debugEnabled = debug_default_state;
float lastPacketRSSI = NAN;
float lastPacketSNR = NAN;

// ------------------ EEPROM PERSISTENCE ------------------
static const uint32_t EEPROM_MAGIC   = 0x53583736UL; // 'SX76'
static const uint16_t EEPROM_VERSION = 0x0001;
static const size_t   EEPROM_SIZE    = 512;

static uint32_t crc32_update(uint32_t crc, uint8_t data) {
  crc ^= data;
  for (int i = 0; i < 8; i++) {
    uint32_t mask = -(crc & 1u);
    crc = (crc >> 1) ^ (0xEDB88320u & mask);
  }
  return crc;
}

static uint32_t crc32_calc(const uint8_t* data, size_t len) {
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; i++) crc = crc32_update(crc, data[i]);
  return ~crc;
}

struct __attribute__((packed)) EepromRecord {
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

// ------------------ RX CALLBACK ------------------
#if defined(ESP8266)
  ICACHE_RAM_ATTR
#elif defined(ESP32)
  IRAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

// ------------------ SERIAL HELPERS ------------------
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("ERROR")); }

// ------------------ PARSERS ------------------
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
  if (t == "ON" || t == "1" || t == "TRUE")  { out = true;  return true; }
  if (t == "OFF" || t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

// ------------------ PRINT CONFIG/HELP ------------------
static void printConfig() {
  Serial.println(F("====== SX1276 CONFIGURATION ======"));
  Serial.print(F("Frequency:    ")); Serial.print(cfg.freqMHz, 3); Serial.println(F(" MHz"));
  Serial.print(F("Bandwidth:    ")); Serial.print(cfg.bwkHz, 1); Serial.println(F(" kHz"));
  Serial.print(F("SF:           ")); Serial.println(cfg.sf);
  Serial.print(F("CR:           ")); Serial.println(cfg.cr);
  Serial.print(F("Sync Word:    0x")); Serial.println(cfg.syncWord, HEX);
  Serial.print(F("TX Power:     ")); Serial.print(cfg.pwrDbm); Serial.println(F(" dBm"));
  Serial.print(F("Current Lim:  ")); Serial.print(cfg.currLimitMA, 1); Serial.println(F(" mA"));
  Serial.print(F("Preamble:     ")); Serial.println(cfg.preamble);
  Serial.print(F("Gain:         ")); Serial.print(cfg.gain); Serial.println(F(" (0=AGC)"));
  Serial.print(F("CRC:          ")); Serial.println(cfg.crcOn ? F("ON") : F("OFF"));
  Serial.print(F("RX Enabled:   ")); Serial.println(rxEnabled ? F("ON") : F("OFF"));
  Serial.print(F("Sleep:        ")); Serial.println(radioSleeping ? F("YES") : F("NO"));
  Serial.print(F("Debug:        ")); Serial.println(debugEnabled ? F("ON") : F("OFF"));
  Serial.println(F("=================================="));
}

static void printHelp() {
  Serial.println(F(""));
  Serial.println(F("AT commands for SX1276 / RA-01 (RadioLib)"));
  Serial.println(F(""));
  Serial.println(F("Core:"));
  Serial.println(F("  AT                  -> OK"));
  Serial.println(F("  AT? / AT+HELP       -> This help"));
  Serial.println(F("  AT+CFG?             -> Show config"));
  Serial.println(F("  AT+APPLY            -> HW reset + apply config"));
  Serial.println(F("  AT+DEFAULT          -> Restore defaults + save + apply"));
  Serial.println(F("  AT+RESET            -> Hardware reset + reinit"));
  Serial.println(F(""));
  Serial.println(F("Parameters (auto save + apply):"));
  Serial.println(F("  AT+FREQ=<MHz>       / AT+FREQ?"));
  Serial.println(F("  AT+BW=<kHz>         / AT+BW?"));
  Serial.println(F("  AT+SF=<6..12>       / AT+SF?"));
  Serial.println(F("  AT+CR=<5..8>        / AT+CR?"));
  Serial.println(F("  AT+SYNC=<hex>       / AT+SYNC?"));
  Serial.println(F("  AT+PWR=<dBm>        / AT+PWR?      (-4 to +20)"));
  Serial.println(F("  AT+CURR=<mA>        / AT+CURR?"));
  Serial.println(F("  AT+PREAMBLE=<n>     / AT+PREAMBLE?"));
  Serial.println(F("  AT+GAIN=<0..6>      / AT+GAIN?     (0=AGC)"));
  Serial.println(F("  AT+CRC=ON|OFF       / AT+CRC?"));
  Serial.println(F(""));
  Serial.println(F("Batch set:"));
  Serial.println(F("  AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>"));
  Serial.println(F(""));
  Serial.println(F("Control:"));
  Serial.println(F("  AT+RX=ON            -> start RX"));
  Serial.println(F("  AT+RX=OFF           -> standby"));
  Serial.println(F("  AT+SLEEP            -> sleep (low power)"));
  Serial.println(F("  AT+WAKE             -> wake + restore RX"));
  Serial.println(F("  AT+RSSI?"));
  Serial.println(F("  AT+SNR?"));
  Serial.println(F("  AT+DEBUG=ON|OFF"));
  Serial.println(F(""));
}

// ------------------ RADIO RESET/APPLY (SX1276) ------------------
static bool resetRadioHardware() {
  pinMode(RESET, OUTPUT);
  digitalWrite(RESET, HIGH);
  delay(10);
  digitalWrite(RESET, LOW);
  delay(10);
  digitalWrite(RESET, HIGH);
  delay(10);
  return true;
}

static bool applyConfigToRadio() {
  radio.standby();
  radioSleeping = false;
  int st;

  st = radio.setFrequency(cfg.freqMHz);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setFrequency: ")); Serial.println(st); }
    return false;
  }

  st = radio.setBandwidth(cfg.bwkHz);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setBandwidth: ")); Serial.println(st); }
    return false;
  }

  st = radio.setSpreadingFactor(cfg.sf);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setSpreadingFactor: ")); Serial.println(st); }
    return false;
  }

  st = radio.setCodingRate(cfg.cr);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setCodingRate: ")); Serial.println(st); }
    return false;
  }

  st = radio.setSyncWord(cfg.syncWord);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setSyncWord: ")); Serial.println(st); }
    return false;
  }

  st = radio.setOutputPower(cfg.pwrDbm);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setOutputPower: ")); Serial.println(st); }
    return false;
  }

  st = radio.setPreambleLength(cfg.preamble);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] setPreambleLength: ")); Serial.println(st); }
    return false;
  }

  // CRC - SX1276 uses bool
  radio.setCRC(cfg.crcOn);

  // Current limit
  if (cfg.currLimitMA > 0.0f) {
    st = radio.setCurrentLimit(cfg.currLimitMA);
    if (st != RADIOLIB_ERR_NONE && debugEnabled) {
      Serial.print(F("[DEBUG] setCurrentLimit: ")); Serial.println(st);
    }
  }

  // Gain - SX1276 supports manual LNA gain
  st = radio.setGain(cfg.gain);
  if (st != RADIOLIB_ERR_NONE && debugEnabled) {
    Serial.print(F("[DEBUG] setGain: ")); Serial.println(st);
  }

  // Start RX if enabled
  if (rxEnabled) {
    radio.setPacketReceivedAction(onRxDone);
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) {
      if (debugEnabled) { Serial.print(F("[DEBUG] startReceive: ")); Serial.println(st); }
      return false;
    }
  }

  return true;
}

static bool resetAndReinit() {
  resetRadioHardware();

  // SX1276 begin() - simple, no TCXO/BUSY like SX1262
  int st = radio.begin();
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) { Serial.print(F("[DEBUG] begin: ")); Serial.println(st); }
    return false;
  }

  return applyConfigToRadio();
}

static bool persistAndReapply() {
  if (!eepromSaveConfig(cfg)) return false;
  return resetAndReinit();
}

static bool putRadioToSleep() {
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
  rxEnabled = rxEnabledBeforeSleep;

  if (rxEnabled) {
    receivedFlag = false;
    radio.setPacketReceivedAction(onRxDone);
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  return true;
}

// ------------------ SERIAL LINE READER ------------------
static String readSerialLine() {
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

// ------------------ AT HANDLER ------------------
static bool handleAT(String lineRaw) {
  String line = lineRaw;
  line.trim();
  String u = line;
  u.toUpperCase();

  // Core
  if (u == "AT") { serialOK(); return true; }
  if (u == "AT?" || u == "AT+HELP") { printHelp(); serialOK(); return true; }
  if (u == "AT+CFG?") { printConfig(); serialOK(); return true; }

  if (u == "AT+APPLY") {
    bool ok = resetAndReinit();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+DEFAULT") {
    cfg = cfgDefault;
    bool ok = persistAndReapply();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RESET") {
    bool ok = resetAndReinit();
    ok ? serialOK() : serialERR();
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
    receivedFlag = false;
    radio.setPacketReceivedAction(onRxDone);
    int st = radio.startReceive();
    (st == RADIOLIB_ERR_NONE) ? serialOK() : serialERR();
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

  // Queries
  if (u == "AT+RSSI?") {
    if (isnan(lastPacketRSSI)) Serial.println(F("RSSI=N/A"));
    else { Serial.print(F("RSSI=")); Serial.print(lastPacketRSSI, 2); Serial.println(F(" dBm")); }
    serialOK();
    return true;
  }
  if (u == "AT+SNR?") {
    if (isnan(lastPacketSNR)) Serial.println(F("SNR=N/A"));
    else { Serial.print(F("SNR=")); Serial.print(lastPacketSNR, 2); Serial.println(F(" dB")); }
    serialOK();
    return true;
  }

  // DEBUG
  if (u == "AT+DEBUG?") {
    Serial.print(F("DEBUG=")); Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG") {
    debugEnabled = !debugEnabled;
    Serial.print(F("DEBUG=")); Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }

  // Parameter queries
  if (u == "AT+FREQ?")     { Serial.print(F("FREQ=")); Serial.print(cfg.freqMHz, 3); Serial.println(F(" MHz")); serialOK(); return true; }
  if (u == "AT+BW?")       { Serial.print(F("BW=")); Serial.print(cfg.bwkHz, 1); Serial.println(F(" kHz")); serialOK(); return true; }
  if (u == "AT+SF?")       { Serial.print(F("SF=")); Serial.println(cfg.sf); serialOK(); return true; }
  if (u == "AT+CR?")       { Serial.print(F("CR=")); Serial.println(cfg.cr); serialOK(); return true; }
  if (u == "AT+SYNC?")     { Serial.print(F("SYNC=0x")); Serial.println(cfg.syncWord, HEX); serialOK(); return true; }
  if (u == "AT+PWR?")      { Serial.print(F("PWR=")); Serial.print(cfg.pwrDbm); Serial.println(F(" dBm")); serialOK(); return true; }
  if (u == "AT+CURR?")     { Serial.print(F("CURR=")); Serial.print(cfg.currLimitMA, 1); Serial.println(F(" mA")); serialOK(); return true; }
  if (u == "AT+PREAMBLE?") { Serial.print(F("PREAMBLE=")); Serial.println(cfg.preamble); serialOK(); return true; }
  if (u == "AT+GAIN?")     { Serial.print(F("GAIN=")); Serial.println(cfg.gain); serialOK(); return true; }
  if (u == "AT+CRC?")      { Serial.print(F("CRC=")); Serial.println(cfg.crcOn ? F("ON") : F("OFF")); serialOK(); return true; }

  // Boolean setters
  if (u == "AT+CRC=ON")  { cfg.crcOn = true;  (persistAndReapply() ? serialOK() : serialERR()); return true; }
  if (u == "AT+CRC=OFF") { cfg.crcOn = false; (persistAndReapply() ? serialOK() : serialERR()); return true; }

  // Numeric setters
  if (u.startsWith("AT+FREQ=")) {
    float v; if (!parseFloat(line.substring(8), v)) { serialERR(); return true; }
    cfg.freqMHz = v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+BW=")) {
    float v; if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    cfg.bwkHz = v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+SF=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 6 || v > 12) { serialERR(); return true; }
    cfg.sf = (uint8_t)v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+CR=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 5 || v > 8) { serialERR(); return true; }
    cfg.cr = (uint8_t)v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+SYNC=")) {
    uint8_t v; if (!parseHexByte(line.substring(8), v)) { serialERR(); return true; }
    cfg.syncWord = v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+PWR=")) {
    long v; if (!parseInt(line.substring(7), v)) { serialERR(); return true; }
    if (v < -4 || v > 20) { serialERR(); return true; }
    cfg.pwrDbm = (int8_t)v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+CURR=")) {
    float v; if (!parseFloat(line.substring(8), v) || v < 0.0f) { serialERR(); return true; }
    cfg.currLimitMA = v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+PREAMBLE=")) {
    long v; if (!parseInt(line.substring(12), v) || v < 1 || v > 65535) { serialERR(); return true; }
    cfg.preamble = (uint16_t)v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }
  if (u.startsWith("AT+GAIN=")) {
    long v; if (!parseInt(line.substring(8), v) || v < 0 || v > 6) { serialERR(); return true; }
    cfg.gain = (uint8_t)v;
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }

  // Batch set
  if (u.startsWith("AT+SET=")) {
    String p = line.substring(7);
    String parts[10];
    int idx = 0;

    while (idx < 10) {
      int c = p.indexOf(',');
      if (c < 0) { parts[idx++] = p; break; }
      parts[idx++] = p.substring(0, c);
      p = p.substring(c + 1);
    }
    if (idx != 10) { serialERR(); return true; }

    for (int i = 0; i < 10; i++) parts[i].trim();

    float f, bw, curr;
    long sf, cr, pwr, pre, gain;
    uint8_t sync;
    bool crcOn;

    if (!parseFloat(parts[0], f)) { serialERR(); return true; }
    if (!parseFloat(parts[1], bw)) { serialERR(); return true; }
    if (!parseInt(parts[2], sf) || sf < 6 || sf > 12) { serialERR(); return true; }
    if (!parseInt(parts[3], cr) || cr < 5 || cr > 8) { serialERR(); return true; }
    if (!parseHexByte(parts[4], sync)) { serialERR(); return true; }
    if (!parseInt(parts[5], pwr) || pwr < -4 || pwr > 20) { serialERR(); return true; }
    if (!parseFloat(parts[6], curr) || curr < 0.0f) { serialERR(); return true; }
    if (!parseInt(parts[7], pre) || pre < 1 || pre > 65535) { serialERR(); return true; }
    if (!parseInt(parts[8], gain) || gain < 0 || gain > 6) { serialERR(); return true; }
    if (!parseBoolOnOff(parts[9], crcOn)) { serialERR(); return true; }

    cfg.freqMHz     = f;
    cfg.bwkHz       = bw;
    cfg.sf          = (uint8_t)sf;
    cfg.cr          = (uint8_t)cr;
    cfg.syncWord    = sync;
    cfg.pwrDbm      = (int8_t)pwr;
    cfg.currLimitMA = curr;
    cfg.preamble    = (uint16_t)pre;
    cfg.gain        = (uint8_t)gain;
    cfg.crcOn       = crcOn;

    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }

  if (u.startsWith("AT")) return false;
  return false;
}

// ------------------ SETUP ------------------
void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(LED_GPIO, OUTPUT);
  digitalWrite(LED_GPIO, LOW);

  // SPI init
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SPI_SS);

  Serial.println();
  Serial.println(F("=========================================="));
  Serial.println(F("   SX1276 / RA-01 AT Bridge"));
  Serial.println(F("   115200 8N1 <-> LoRa 433 MHz"));
  Serial.println(F("=========================================="));
  Serial.println();

  // EEPROM
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin() failed!"));
  }

  bool loaded = eepromLoadConfig(cfg);
  if (!loaded) {
    cfg = cfgDefault;
    eepromSaveConfig(cfg);
  }

  Serial.print(F("[EEPROM] Config: "));
  Serial.println(loaded ? F("loaded") : F("defaults"));

  rxEnabled = true;
  debugEnabled = debug_default_state;

  // Init radio
  Serial.print(F("[SX1276] Initializing... "));
  bool ok = resetAndReinit();

  if (ok) {
    Serial.println(F("OK"));
  } else {
    Serial.println(F("FAILED, trying defaults..."));
    cfg = cfgDefault;
    eepromSaveConfig(cfg);
    ok = resetAndReinit();
    if (!ok) {
      Serial.println(F("[SX1276] Init failed! Check wiring."));
      while (true) delay(1000);
    }
    Serial.println(F("[SX1276] Defaults applied."));
  }

  printConfig();

  // OLED setup (after radio, to avoid SPI conflicts)
  oled_setup();

  // Re-init after OLED
  delay(100);
  resetAndReinit();

  Serial.println(F("[READY] Type AT+HELP for commands."));
  Serial.println(F("------------------------------------------"));
}

// ------------------ LOOP ------------------
void loop() {
  // LED 1Hz blink
  static unsigned long lastLed = 0;
  static bool ledState = false;
  if (millis() - lastLed >= 500) {
    lastLed = millis();
    ledState = !ledState;
    digitalWrite(LED_GPIO, ledState ? HIGH : LOW);
  }

  // Serial -> AT or TX
  String line = readSerialLine();
  if (line.length() > 0) {
    if (line.startsWith("AT") || line.startsWith("at")) {
      if (!handleAT(line)) {
        serialERR();
      }
    } else if (radioSleeping) {
      Serial.println(F("ERROR: RADIO_SLEEPING (send AT+WAKE)"));
    } else if (rxEnabled) {
      // TX with \r\n appended
      radio.clearPacketReceivedAction();
      radio.standby();
      delay(2);

      String dataWithCRLF = line + "\r\n";
      int tx = radio.transmit(dataWithCRLF);

      if (debugEnabled) {
        Serial.print(F("[TX] "));
        Serial.print(dataWithCRLF.length());
        Serial.print(F(" bytes, result: "));
        Serial.println(tx);
      }

      // Restore RX
      if (rxEnabled) {
        receivedFlag = false;
        radio.setPacketReceivedAction(onRxDone);
        radio.startReceive();
      }
    }
  }

  // RX -> Serial
  if (receivedFlag && !radioSleeping) {
    receivedFlag = false;

    String str;
    int rx = radio.readData(str);

    if (rx == RADIOLIB_ERR_NONE) {
      lastPacketRSSI = radio.getRSSI();
      lastPacketSNR = radio.getSNR();

      if (debugEnabled) {
        Serial.print(F("[RX] Data: "));
        Serial.println(str);
        Serial.print(F("[RX] RSSI: "));
        Serial.print(lastPacketRSSI, 2);
        Serial.print(F(" dBm, SNR: "));
        Serial.print(lastPacketSNR, 2);
        Serial.println(F(" dB"));
      } else {
        Serial.print(str);
      }

    } else if (rx == RADIOLIB_ERR_CRC_MISMATCH) {
      if (debugEnabled) Serial.println(F("[RX] CRC error"));
    } else {
      if (debugEnabled) {
        Serial.print(F("[RX] Error: "));
        Serial.println(rx);
      }
    }

    if (rxEnabled) {
      radio.startReceive();
    }
  }
}
