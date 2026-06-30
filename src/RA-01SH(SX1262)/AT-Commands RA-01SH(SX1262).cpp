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
  drawCentered("SX1262", 63, u8g2_font_logisoso18_tr);
  u8g2.sendBuffer();
}

// ------------------ PINOUT (SX1262) ------------------
#define NSS     7
#define DIO1    1
#define RESET   10
#define BUSY    3

// SPI pins (as you used before)
#define SPI_SCK   4
#define SPI_MISO  5
#define SPI_MOSI  6
#define SPI_SS    7

#define LED_GPIO 8

SX1262 radio = new Module(NSS, DIO1, RESET, BUSY);

// ------------------ USER TUNABLE DEFAULTS ------------------
static constexpr bool debug_defoult_state = false;

// ------------------ RX IRQ FLAG ------------------
volatile bool receivedFlag = false;

// ------------------ CONFIG (DEFAULTS MUST REMAIN AS REQUESTED) ------------------
struct RadioConfig {
  float    freqMHz     = 433.0;   // MHz
  float    bwkHz       = 250.0;   // kHz
  uint8_t  sf          = 10;      // 7..12
  uint8_t  cr          = 6;       // 5..8 (RadioLib)
  uint8_t  syncWord    = 0x14;    // e.g. 0x14
  int8_t   pwrDbm      = 10;      // dBm
  float    currLimitMA = 0;       // 0 = do not set / keep default
  uint16_t preamble    = 15;
  uint8_t  gain        = 1;       // 0=AGC, 1..6 manual (SX1262: kept for compatibility, NO-OP)
  bool     crcOn       = true;    // LoRa CRC enable/disable
};

RadioConfig cfg;
const RadioConfig cfgDefault;     // compile-time defaults (as above)

// RX is always ON by default (can be put to standby with AT+RX=OFF)
bool rxEnabled = true;
bool radioSleeping = false;
bool rxEnabledBeforeSleep = true;

// DEBUG state
bool debugEnabled = debug_defoult_state;

// Last RSSI for AT+RSSI?
float lastPacketRSSI = NAN;

// ------------------ EEPROM PERSISTENCE ------------------
static const uint32_t EEPROM_MAGIC   = 0x534C4F52UL; // 'SLOR'
static const uint16_t EEPROM_VERSION = 0x0001;
static const size_t   EEPROM_SIZE    = 512;

// Simple CRC32 (software) over cfg bytes
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
  Serial.println(F("CFG:"));
  Serial.print(F("  FREQ="));     Serial.print(cfg.freqMHz, 3); Serial.println(F(" MHz"));
  Serial.print(F("  BW="));       Serial.print(cfg.bwkHz, 1);   Serial.println(F(" kHz"));
  Serial.print(F("  SF="));       Serial.println(cfg.sf);
  Serial.print(F("  CR="));       Serial.println(cfg.cr);
  Serial.print(F("  SYNC=0x"));   Serial.println(cfg.syncWord, HEX);
  Serial.print(F("  PWR="));      Serial.print(cfg.pwrDbm);     Serial.println(F(" dBm"));
  Serial.print(F("  CURR="));     Serial.print(cfg.currLimitMA, 1); Serial.println(F(" mA (0=skip)"));
  Serial.print(F("  PREAMBLE=")); Serial.println(cfg.preamble);
  Serial.print(F("  GAIN="));     Serial.println(cfg.gain);
  Serial.print(F("  RX="));       Serial.println(rxEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  SLEEP="));    Serial.println(radioSleeping ? F("YES") : F("NO"));
  Serial.print(F("  CRC="));      Serial.println(cfg.crcOn ? F("ON") : F("OFF"));
  Serial.print(F("  DEBUG="));    Serial.println(debugEnabled ? F("ON") : F("OFF"));
}

static void printHelp() {
  Serial.println(F("AT commands for SX1262 (RadioLib) - compatible with SX1278 bridge"));
  Serial.println(F("Core:"));
  Serial.println(F("  AT                  -> OK"));
  Serial.println(F("  AT? / AT+HELP       -> list commands"));
  Serial.println(F("  AT+CFG?             -> print current config"));
  Serial.println(F("  AT+APPLY            -> HW reset + apply current config"));
  Serial.println(F("  AT+DEFAULT          -> load defaults + auto save + auto apply"));
  Serial.println(F("  AT+RESET            -> hardware reset radio + reinit + apply"));
  Serial.println(F("Parameters (set/query) - each setter auto save + auto reset/apply:"));
  Serial.println(F("  AT+FREQ=<MHz>       / AT+FREQ?"));
  Serial.println(F("  AT+BW=<kHz>         / AT+BW?"));
  Serial.println(F("  AT+SF=<7..12>       / AT+SF?"));
  Serial.println(F("  AT+CR=<5..8>        / AT+CR?"));
  Serial.println(F("  AT+SYNC=<hex>       / AT+SYNC?     (e.g. 0x14)"));
  Serial.println(F("  AT+PWR=<dBm>        / AT+PWR?"));
  Serial.println(F("  AT+CURR=<mA|0>      / AT+CURR?"));
  Serial.println(F("  AT+PREAMBLE=<n>     / AT+PREAMBLE?"));
  Serial.println(F("  AT+GAIN=<0..6>      / AT+GAIN?     (SX1262: stored for compatibility, NO-OP)"));
  Serial.println(F("  AT+CRC=ON|OFF       / AT+CRC?"));
  Serial.println(F("Batch set (auto save + auto reset/apply):"));
  Serial.println(F("  AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<CURR>,<PRE>,<GAIN>,<CRC>"));
  Serial.println(F("    Example: AT+SET=433.5,125,11,8,0x14,10,0,8,0,ON"));
  Serial.println(F("Quick:"));
  Serial.println(F("  AT+RX=OFF           -> standby"));
  Serial.println(F("  AT+RX=ON            -> start receive"));
  Serial.println(F("  AT+SLEEP            -> sleep (low power)"));
  Serial.println(F("  AT+WAKE             -> wake + restore RX"));
  Serial.println(F("  AT+RSSI?            -> last RSSI"));
  Serial.println(F("Debug:"));
  Serial.println(F("  AT+DEBUG / AT+DEBUG=ON/OFF / AT+DEBUG?"));
}

// ------------------ RADIO APPLY/RESET (SX1262) ------------------
static bool waitBusyLow(uint32_t timeoutMs) {
  pinMode(BUSY, INPUT);
  uint32_t t0 = millis();
  while (digitalRead(BUSY) == HIGH) {
    if (millis() - t0 > timeoutMs) return false;
    delay(1);
  }
  return true;
}

static bool resetRadioHardware() {
  // SX1262 reset: pulse LOW on RESET and wait BUSY goes low
  pinMode(RESET, OUTPUT);
  digitalWrite(RESET, HIGH);
  delay(5);
  digitalWrite(RESET, LOW);
  delay(20);
  digitalWrite(RESET, HIGH);
  delay(10);
  // wait BUSY low (module ready)
  return waitBusyLow(1000);
}

static bool applyConfigToRadioNoReset() {
  // Applies cfg WITHOUT hardware reset (after begin)
  radio.standby();
  radioSleeping = false;
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

  st = radio.setPreambleLength(cfg.preamble);
  if (st != RADIOLIB_ERR_NONE) return false;

  radio.setCRC(cfg.crcOn);

  if (cfg.currLimitMA > 0.0f) {
    st = radio.setCurrentLimit((uint16_t)lroundf(cfg.currLimitMA));
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  // NOTE: SX1262 has no SX127x-style gain control. Kept for AT compatibility, NO-OP.

  if (rxEnabled) {
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  return true;
}

static bool resetRadioByPinAndReinitAndApply() {
  // Full sequence: HW reset -> begin(...) -> attach IRQ -> apply cfg -> RX if enabled
  if (!resetRadioHardware()) return false;

  // Re-init LoRa modem with the current cfg. For SX1262, begin() can take parameters.
  // If your board uses TCXO at 1.8 V, keep it here. If not, set last arg to 0.0.
  const float tcxoV = 1.8f;

  int st = radio.begin(cfg.freqMHz, cfg.bwkHz, cfg.sf, cfg.cr, cfg.syncWord,
                       cfg.pwrDbm, cfg.preamble, 0 /*LDO*/, tcxoV);
  if (st != RADIOLIB_ERR_NONE) return false;

  radio.setPacketReceivedAction(onRxDone);
  return applyConfigToRadioNoReset();
}

static bool persistAndReapply() {
  if (!eepromSaveConfig(cfg)) return false;
  return resetRadioByPinAndReinitAndApply();
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

// ------------------ AT HANDLER (case-insensitive) ------------------
static bool handleAT(String lineRaw) {
  String line = lineRaw;
  line.trim();

  String u = line;
  u.toUpperCase();

  // Core
  if (u == "AT") { serialOK(); return true; }
  if (u == "AT?" || u == "AT+HELP") { printHelp(); serialOK(); return true; }
  if (u == "AT+CFG?") { printConfig(); serialOK(); return true; }

  // Apply (HW reset + apply)
  if (u == "AT+APPLY") {
    bool ok = resetRadioByPinAndReinitAndApply();
    ok ? serialOK() : serialERR();
    return true;
  }

  // Defaults
  if (u == "AT+DEFAULT") {
    cfg = cfgDefault;
    bool ok = persistAndReapply();
    ok ? serialOK() : serialERR();
    return true;
  }

  // Hardware reset + apply current cfg
  if (u == "AT+RESET") {
    bool ok = resetRadioByPinAndReinitAndApply();
    ok ? serialOK() : serialERR();
    return true;
  }

  // RX OFF/ON
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

  // RSSI query
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
  if (u == "AT+DEBUG") {  // toggle
    debugEnabled = !debugEnabled;
    Serial.print(F("DEBUG="));
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }

  // Parameter queries
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
  if (u == "AT+CRC=ON")  { cfg.crcOn = true;  (persistAndReapply() ? serialOK() : serialERR()); return true; }
  if (u == "AT+CRC=OFF") { cfg.crcOn = false; (persistAndReapply() ? serialOK() : serialERR()); return true; }

  // Parameter setters (auto save + HW reset/apply)
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
    long v; if (!parseInt(line.substring(6), v) || v < 7 || v > 12) { serialERR(); return true; }
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
    cfg.gain = (uint8_t)v; // stored for compatibility, NO-OP on SX1262
    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }

  // Batch set
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
    cfg.gain        = (uint8_t)gain; // stored only
    cfg.crcOn       = crcOn;

    (persistAndReapply() ? serialOK() : serialERR());
    return true;
  }

  // Unknown AT command
  if (u.startsWith("AT")) return false;
  return false;
}

// ------------------ SETUP/LOOP ------------------
void setup() {
  Serial.begin(9600);
  delay(1000);

  pinMode(LED_GPIO, OUTPUT);
  digitalWrite(LED_GPIO, LOW);

  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SPI_SS);

  // EEPROM init
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin() failed! Using RAM defaults only."));
  }

  // Load last valid cfg from EEPROM, otherwise use defaults
  bool loaded = eepromLoadConfig(cfg);
  if (!loaded) {
    cfg = cfgDefault;
    eepromSaveConfig(cfg);
  }

  rxEnabled = true;
  debugEnabled = debug_defoult_state;

  Serial.print(F("[BOOT] DEBUG default = "));
  Serial.println(debugEnabled ? F("ON") : F("OFF"));

  Serial.print(F("[EEPROM] Loaded config = "));
  Serial.println(loaded ? F("YES") : F("NO (using defaults)"));

  Serial.print(F("[SX1262] Initializing + applying last valid config ... "));

  bool ok = resetRadioByPinAndReinitAndApply();

  if (ok) {
    Serial.println(F("success!"));
  } else {
    Serial.println(F("failed!"));
    Serial.println(F("[SX1262] Fallback to defaults..."));
    cfg = cfgDefault;
    eepromSaveConfig(cfg);
    ok = resetRadioByPinAndReinitAndApply();
    if (!ok) {
      Serial.println(F("[SX1262] Fallback failed. Halting."));
      while (true) delay(10);
    }
    Serial.println(F("[SX1262] Defaults applied successfully."));
  }

  oled_setup();

  // Keep your original "triple apply" behavior (some boards like it)
  ok = resetRadioByPinAndReinitAndApply();
  delay(150);
  ok = resetRadioByPinAndReinitAndApply();
}

void loop() {
  // LED 1 Hz blink (toggle every 500 ms)
  static unsigned long lastLed = 0;
  static bool ledState = false;
  unsigned long now = millis();
  if (now - lastLed >= 1000) {
    lastLed = now;
    ledState = !ledState;
    digitalWrite(LED_GPIO, ledState ? HIGH : LOW);
  }

  // Serial line -> AT or radio TX
  String line = readSerialLineNonBlocking();
  if (line.length() > 0) {
    if (line.startsWith("AT") || line.startsWith("at")) {
      if (!handleAT(line)) {
        serialERR();
      }
    } else {
      if (radioSleeping) {
        Serial.println(F("ERROR: RADIO_SLEEPING (send AT+WAKE)"));
        return;
      }

      // Transmit non-AT text as-is (same behavior)
      radio.clearPacketReceivedAction();

      if (debugEnabled) {
        Serial.print(F("[SX1262] TX -> "));
        Serial.println(line);
      }

      // Ensure not in RX while transmitting
      radio.standby();
      delay(2);

      int tx = radio.transmit(line);

      if (debugEnabled) {
        if (tx == RADIOLIB_ERR_NONE) {
          Serial.println(F("[SX1262] TX OK"));
        } else {
          Serial.print(F("[SX1262] TX failed, code "));
          Serial.println(tx);
        }
      }

      // Restore RX mode if enabled
      if (rxEnabled) {
        radio.setPacketReceivedAction(onRxDone);
        radio.startReceive();
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

      if (debugEnabled) {
        Serial.print(F("[SX1262] Data:\t\t  "));
        Serial.println(str);

        Serial.print(F("[SX1262] RSSI:\t\t  "));
        Serial.print(radio.getRSSI(), 2);
        Serial.println(F(" dBm"));

        Serial.print(F("[SX1262] SNR:\t\t  "));
        Serial.print(radio.getSNR(), 2);
        Serial.println(F(" dB"));

        Serial.print(F("[SX1262] Frequency Error:\t  "));
        Serial.print(radio.getFrequencyError(), 2);
        Serial.println(F(" Hz"));

        Serial.println(F("[SX1262] Packet received!"));
      } else {
        // DEBUG OFF: print ONLY the payload
        Serial.println(str);
      }

    } else if (rx == RADIOLIB_ERR_CRC_MISMATCH) {
      if (debugEnabled) Serial.println(F("[SX1262] CRC error!"));
    } else {
      if (debugEnabled) {
        Serial.print(F("[SX1262] RX failed, code "));
        Serial.println(rx);
      }
    }

    if (rxEnabled) {
      radio.startReceive();
    }
  }
}
