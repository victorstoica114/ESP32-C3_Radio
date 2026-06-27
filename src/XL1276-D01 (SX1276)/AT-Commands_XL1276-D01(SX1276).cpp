#include <Arduino.h>
#include <RadioLib.h>
#include <EEPROM.h>
#include <math.h>
#include <U8g2lib.h>

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

// ============================================================================
// SX1276 connections (as requested)
// ============================================================================
#define NSS     7
#define DIO0    3
#define RESET   10
#define DIO1    1

#define LED_GPIO 8

SX1276 radio = new Module(NSS, DIO0, RESET, DIO1);

// ============================================================================
// USER TUNABLE DEFAULTS
// ============================================================================
static constexpr bool debug_default_state = false;

// RX IRQ flag (set from ISR)
volatile bool receivedFlag = false;

// RX enabled by default
static bool rxEnabled = true;

// DEBUG runtime switch
static bool debugEnabled = debug_default_state;

// Last RSSI for AT+RSSI?
static float lastPacketRSSI = NAN;

// Radio ready state (for TX/RX operations)
static bool radioReady = false;

// ============================================================================
// CONFIG (SX1276)
// Keep these defaults as your "factory defaults" for AT+DEFAULT
// ============================================================================
struct RadioConfig {
  float    freqMHz     = 434.0;   // MHz
  float    bwkHz       = 125.0;   // kHz
  uint8_t  sf          = 9;       // 7..12
  uint8_t  cr          = 5;       // 5..8 (RadioLib)
  uint8_t  syncWord    = 0x12;    // private network typical
  int8_t   pwrDbm      = 10;      // dBm (-3..17, 20 allowed with duty-cycle constraints)
  float    currLimitMA = 80.0;    // mA (0 disables OCP)
  uint16_t preamble    = 8;       // 6..65535 (SX127x)
  uint8_t  gain        = 1;       // 0=AGC, 1..6 manual (1=max gain)
  bool     crcOn       = true;    // LoRa CRC enable/disable
};

RadioConfig cfg;
const RadioConfig cfgDefault;   // compile-time defaults above

// ============================================================================
// EEPROM PERSISTENCE
// ============================================================================
static const uint32_t EEPROM_MAGIC   = 0x53313236UL; // "S126"
static const uint16_t EEPROM_VERSION = 0x0003;       // bump if you change struct/layout
static const size_t   EEPROM_SIZE    = 256;

static void oled_setup() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setBusClock(400000);

  u8g2.clearBuffer();

  // Safe sizes for 2 lines on 128x64 without clipping
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);   // baseline ~26
  drawCentered("SX1276", 63, u8g2_font_logisoso18_tr);  // baseline ~56

  u8g2.sendBuffer();
}

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
// RX CALLBACK (DIO0)
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
static inline void serialERR() { Serial.println(F("ERROR")); }

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
  if (t == "ON"  || t == "1" || t == "TRUE")  { out = true;  return true; }
  if (t == "OFF" || t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

// ============================================================================
// PRINT CONFIG/HELP
// ============================================================================
static void printConfig() {
  Serial.println(F("CFG:"));
  Serial.print(F("  FREQ="));     Serial.print(cfg.freqMHz, 3); Serial.println(F(" MHz"));
  Serial.print(F("  BW="));       Serial.print(cfg.bwkHz, 1);   Serial.println(F(" kHz"));
  Serial.print(F("  SF="));       Serial.println(cfg.sf);
  Serial.print(F("  CR="));       Serial.println(cfg.cr);
  Serial.print(F("  SYNC=0x"));   Serial.println(cfg.syncWord, HEX);
  Serial.print(F("  PWR="));      Serial.print(cfg.pwrDbm);     Serial.println(F(" dBm"));
  Serial.print(F("  CURR="));     Serial.print(cfg.currLimitMA, 1); Serial.println(F(" mA (0=disable OCP)"));
  Serial.print(F("  PREAMBLE=")); Serial.println(cfg.preamble);
  Serial.print(F("  GAIN="));     Serial.println(cfg.gain);
  Serial.print(F("  CRC="));      Serial.println(cfg.crcOn ? F("ON") : F("OFF"));
  Serial.print(F("  RX="));       Serial.println(rxEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  DEBUG="));    Serial.println(debugEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  READY="));    Serial.println(radioReady ? F("YES") : F("NO"));
}

static void printHelp() {
  Serial.println(F("AT commands for SX1276 (RadioLib)"));
  Serial.println();
  Serial.println(F("Core:"));
  Serial.println(F("  AT                  -> OK"));
  Serial.println(F("  AT? / AT+HELP       -> show this help"));
  Serial.println(F("  AT+CFG?             -> print current config + status"));
  Serial.println(F("  AT+APPLY            -> HW reset + apply current config + start RX (if RX=ON)"));
  Serial.println(F("  AT+RESET            -> HW reset + re-apply current config"));
  Serial.println(F("  AT+DEFAULT          -> load defaults + auto save + auto apply"));
  Serial.println();
  Serial.println(F("Parameters (set/query) - setters auto save + auto apply:"));
  Serial.println(F("  AT+FREQ=<MHz>       / AT+FREQ?"));
  Serial.println(F("  AT+BW=<kHz>         / AT+BW?"));
  Serial.println(F("  AT+SF=<7..12>       / AT+SF?"));
  Serial.println(F("  AT+CR=<5..8>        / AT+CR?"));
  Serial.println(F("  AT+SYNC=<hex>       / AT+SYNC?   (e.g. 0x12, 0x14)"));
  Serial.println(F("  AT+PWR=<dBm>        / AT+PWR?"));
  Serial.println(F("  AT+CURR=<mA|0>      / AT+CURR?   (OCP, 0 disables)"));
  Serial.println(F("  AT+PREAMBLE=<n>     / AT+PREAMBLE?"));
  Serial.println(F("  AT+GAIN=<0..6>      / AT+GAIN?   (0=AGC, 1=max gain)"));
  Serial.println(F("  AT+CRC=ON|OFF       / AT+CRC?"));
  Serial.println();
  Serial.println(F("Batch set (auto save + auto apply):"));
  Serial.println(F("  AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>"));
  Serial.println(F("    Example: AT+SET=434.0,125,9,5,0x12,10,80,8,1,ON"));
  Serial.println();
  Serial.println(F("RX control:"));
  Serial.println(F("  AT+RX=ON            -> start RX"));
  Serial.println(F("  AT+RX=OFF           -> standby (stop RX)"));
  Serial.println();
  Serial.println(F("Diagnostics:"));
  Serial.println(F("  AT+RSSI?            -> last packet RSSI"));
  Serial.println(F("  AT+DEBUG            -> toggle debug"));
  Serial.println(F("  AT+DEBUG=ON/OFF      / AT+DEBUG?"));
  Serial.println();
  Serial.println(F("TX (manual):"));
  Serial.println(F("  Any non-AT line sent over Serial is transmitted as LoRa payload."));
}

// ============================================================================
// RADIO APPLY/RESET
// ============================================================================
static bool resetRadioHardware() {
  // SX1276 reset: pulse LOW on RESET
  pinMode(RESET, OUTPUT);
  digitalWrite(RESET, HIGH);
  delay(2);
  digitalWrite(RESET, LOW);
  delay(50);
  digitalWrite(RESET, HIGH);
  delay(20);
  return true;
}

static bool applyConfigToRadioNoReset() {
  // Apply cfg to radio WITHOUT HW reset (used after reset+begin)
  radio.standby();

  int st;

  st = radio.setFrequency(cfg.freqMHz);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setBandwidth(cfg.bwkHz);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setSpreadingFactor(cfg.sf);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setCodingRate(cfg.cr);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setSyncWord(cfg.syncWord);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setOutputPower(cfg.pwrDbm);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setCurrentLimit(cfg.currLimitMA);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setPreambleLength(cfg.preamble);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setGain(cfg.gain);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setCRC(cfg.crcOn);
  if (st != RADIOLIB_ERR_NONE) return false;

  radio.setPacketReceivedAction(onRxDone);

  if (rxEnabled) {
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  return true;
}

static bool resetRadioByPinAndReinitAndApply() {
  // Full sequence: HW reset -> begin() -> attach IRQ -> apply cfg -> RX if enabled
  resetRadioHardware();

  int st = radio.begin();
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[SX1276] begin() failed, code "));
      Serial.println(st);
    }
    return false;
  }

  return applyConfigToRadioNoReset();
}

static bool persistAndReapply() {
  // Apply first, then save only if apply succeeded (so EEPROM keeps "last valid")
  bool ok = resetRadioByPinAndReinitAndApply();
  if (!ok) return false;
  if (!eepromSaveConfig(cfg)) return false;
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

  // Apply / Reset / Default
  if (u == "AT+APPLY") {
    radioReady = persistAndReapply();
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
    radioReady ? serialOK() : serialERR();
    return true;
  }

  // RX control
  if (u == "AT+RX=OFF") {
    rxEnabled = false;
    radio.standby();
    serialOK();
    return true;
  }
  if (u == "AT+RX=ON") {
    rxEnabled = true;
    radioReady = resetRadioByPinAndReinitAndApply();
    radioReady ? serialOK() : serialERR();
    return true;
  }

  // RSSI
  if (u == "AT+RSSI?") {
    if (isnan(lastPacketRSSI)) Serial.println(F("RSSI=N/A"));
    else { Serial.print(F("RSSI=")); Serial.println(lastPacketRSSI, 2); }
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
  if (u == "AT+FREQ?")     { Serial.print(F("FREQ=")); Serial.println(cfg.freqMHz, 3); serialOK(); return true; }
  if (u == "AT+BW?")       { Serial.print(F("BW=")); Serial.println(cfg.bwkHz, 1); serialOK(); return true; }
  if (u == "AT+SF?")       { Serial.print(F("SF=")); Serial.println(cfg.sf); serialOK(); return true; }
  if (u == "AT+CR?")       { Serial.print(F("CR=")); Serial.println(cfg.cr); serialOK(); return true; }
  if (u == "AT+SYNC?")     { Serial.print(F("SYNC=0x")); Serial.println(cfg.syncWord, HEX); serialOK(); return true; }
  if (u == "AT+PWR?")      { Serial.print(F("PWR=")); Serial.println(cfg.pwrDbm); serialOK(); return true; }
  if (u == "AT+CURR?")     { Serial.print(F("CURR=")); Serial.println(cfg.currLimitMA, 1); serialOK(); return true; }
  if (u == "AT+PREAMBLE?") { Serial.print(F("PREAMBLE=")); Serial.println(cfg.preamble); serialOK(); return true; }
  if (u == "AT+GAIN?")     { Serial.print(F("GAIN=")); Serial.println(cfg.gain); serialOK(); return true; }
  if (u == "AT+CRC?")      { Serial.print(F("CRC="));  Serial.println(cfg.crcOn ? F("ON") : F("OFF")); serialOK(); return true; }

  // CRC setters
  if (u == "AT+CRC=ON")  { cfg.crcOn = true;  radioReady = persistAndReapply(); radioReady ? serialOK() : serialERR(); return true; }
  if (u == "AT+CRC=OFF") { cfg.crcOn = false; radioReady = persistAndReapply(); radioReady ? serialOK() : serialERR(); return true; }

  // Setters
  if (u.startsWith("AT+FREQ=")) {
    float v; if (!parseFloat(line.substring(8), v)) { serialERR(); return true; }
    cfg.freqMHz = v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+BW=")) {
    float v; if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    cfg.bwkHz = v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+SF=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 7 || v > 12) { serialERR(); return true; }
    cfg.sf = (uint8_t)v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+CR=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 5 || v > 8) { serialERR(); return true; }
    cfg.cr = (uint8_t)v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+SYNC=")) {
    uint8_t v; if (!parseHexByte(line.substring(8), v)) { serialERR(); return true; }
    cfg.syncWord = v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+PWR=")) {
    long v; if (!parseInt(line.substring(7), v)) { serialERR(); return true; }
    cfg.pwrDbm = (int8_t)v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+CURR=")) {
    float v; if (!parseFloat(line.substring(8), v) || v < 0.0f) { serialERR(); return true; }
    cfg.currLimitMA = v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+PREAMBLE=")) {
    long v; if (!parseInt(line.substring(12), v) || v < 6 || v > 65535) { serialERR(); return true; }
    cfg.preamble = (uint16_t)v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+GAIN=")) {
    long v; if (!parseInt(line.substring(8), v) || v < 0 || v > 6) { serialERR(); return true; }
    cfg.gain = (uint8_t)v;
    radioReady = persistAndReapply();
    radioReady ? serialOK() : serialERR();
    return true;
  }

  // Batch set (exact format preserved):
  // AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>
  if (u.startsWith("AT+SET=")) {
    String p = line.substring(7);

    String parts[10];
    for (int i = 0; i < 10; i++) parts[i] = "";

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
    if (!parseInt(parts[2], sf) || sf < 7 || sf > 12) { serialERR(); return true; }
    if (!parseInt(parts[3], cr) || cr < 5 || cr > 8) { serialERR(); return true; }
    if (!parseHexByte(parts[4], sync)) { serialERR(); return true; }
    if (!parseInt(parts[5], pwr)) { serialERR(); return true; }
    if (!parseFloat(parts[6], curr) || curr < 0.0f) { serialERR(); return true; }
    if (!parseInt(parts[7], pre) || pre < 6 || pre > 65535) { serialERR(); return true; }
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

    radioReady = persistAndReapply();
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
  Serial.begin(9600);
  delay(150);

  pinMode(LED_GPIO, OUTPUT);
  digitalWrite(LED_GPIO, LOW);

  Serial.println();
  Serial.println(F("[BOOT] Starting SX1276 AT firmware"));

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

  Serial.print(F("[SX1276] Applying config... "));
  radioReady = resetRadioByPinAndReinitAndApply();
  Serial.println(radioReady ? F("OK") : F("FAILED"));

  if (!radioReady) {
    Serial.println(F("[HINT] Verify NSS/DIO0/RESET/DIO1 wiring + correct pins."));
    Serial.println(F("[HINT] You can still type AT commands and run AT+APPLY after setting params."));
  }

  Serial.println(F("[READY] Type AT+HELP"));
  oled_setup();
  radioReady = resetRadioByPinAndReinitAndApply();
  delay(150);
  radioReady = resetRadioByPinAndReinitAndApply();
}

void loop() {
  // LED blink 1 Hz (toggle every 500 ms)
  static unsigned long lastLed = 0;
  static bool ledState = false;
  unsigned long now = millis();
  if (now - lastLed >= 1000) {
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
      if (!radioReady) {
        Serial.println(F("ERROR: RADIO_NOT_READY (set config and run AT+APPLY)"));
      } else {
        // Avoid false RX triggers during TX
        radio.clearPacketReceivedAction();

        if (debugEnabled) {
          Serial.print(F("[SX1276] TX -> "));
          Serial.println(line);
        }

        int tx = radio.transmit(line);

        if (debugEnabled) {
          if (tx == RADIOLIB_ERR_NONE) Serial.println(F("[SX1276] TX OK"));
          else { Serial.print(F("[SX1276] TX failed, code ")); Serial.println(tx); }
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
  if (receivedFlag) {
    receivedFlag = false;

    String str;
    int rx = radio.readData(str);

    if (rx == RADIOLIB_ERR_NONE) {
      lastPacketRSSI = radio.getRSSI();

      if (debugEnabled) {
        Serial.print(F("[SX1276] RX DATA: "));
        Serial.println(str);

        Serial.print(F("[SX1276] RSSI: "));
        Serial.print(radio.getRSSI(), 2);
        Serial.println(F(" dBm"));

        Serial.print(F("[SX1276] SNR:  "));
        Serial.print(radio.getSNR(), 2);
        Serial.println(F(" dB"));

        Serial.print(F("[SX1276] FERR: "));
        Serial.print(radio.getFrequencyError(), 2);
        Serial.println(F(" Hz"));

        Serial.println(F("[SX1276] Packet received!"));
      } else {
        // DEBUG OFF: print ONLY the payload
        Serial.println(str);
      }

    } else if (rx == RADIOLIB_ERR_CRC_MISMATCH) {
      if (debugEnabled) Serial.println(F("[SX1276] CRC error!"));
    } else {
      if (debugEnabled) {
        Serial.print(F("[SX1276] RX failed, code "));
        Serial.println(rx);
      }
    }

    if (rxEnabled) {
      radio.startReceive();
    }
  }
}
