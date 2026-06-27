#include <Arduino.h>
#include <RadioLib.h>
#include <EEPROM.h>
#include <math.h>
#include <U8g2lib.h>

// ============================================================================
// OLED (SSD1306 128x64) - HW I2C
// ============================================================================
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

static void oled_setup() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setBusClock(400000);

  u8g2.clearBuffer();

  // Safe sizes for 2 lines on 128x64 without clipping
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("SX1280", 63, u8g2_font_logisoso18_tr);

  u8g2.sendBuffer();
}

// ============================================================================
// SX1280 PINOUT (as requested)
// ============================================================================
#define NSS     7
#define DIO1    1
#define NRST    10
#define BUSY    3

#define LED_GPIO 8

SX1280 radio = new Module(NSS, DIO1, NRST, BUSY);

// ============================================================================
// USER TUNABLE DEFAULTS
// ============================================================================
static constexpr bool debug_default_state = false;

// RX IRQ flag
volatile bool receivedFlag = false;

// RX enabled by default
static bool rxEnabled = true;

// DEBUG runtime switch
static bool debugEnabled = debug_default_state;

// Last RSSI for AT+RSSI?
static float lastPacketRSSI = NAN;

// Radio ready state
static bool radioReady = false;

// CRC graceful handling
static bool   crcForcedOff = false;           // true when CRC ON was requested but not supported
static int16_t lastCrcSetStatus = 0;          // last status returned by setCRC()

// ============================================================================
// CONFIG (SX1280 ONLY) - defaults are valid for SX1280
// ============================================================================
struct RadioConfig {
  float    freqMHz   = 2410.5;     // MHz
  float    bwkHz     = 203.125;    // kHz
  uint8_t  sf        = 10;         // spreading factor
  uint8_t  cr        = 6;          // coding rate (RadioLib: 5..8)
  uint8_t  syncWord  = 0x12;       // private network example
  int8_t   pwrDbm    = -2;         // dBm
  uint16_t preamble  = 16;         // symbols
  bool     crcOn     = false;      // CRC OFF to match your working test
};

RadioConfig cfg;
const RadioConfig cfgDefault;   // compile-time defaults (above)

// ============================================================================
// EEPROM PERSISTENCE
// ============================================================================
static const uint32_t EEPROM_MAGIC   = 0x53313238UL; // "S128"
static const uint16_t EEPROM_VERSION = 0x0002;       // bump to invalidate old layouts
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
  if (t == "ON" || t == "1" || t == "TRUE")   { out = true;  return true; }
  if (t == "OFF" || t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

// ============================================================================
// PRINT CONFIG/HELP
// ============================================================================
static void printConfig() {
  Serial.println(F("CFG:"));
  Serial.print(F("  FREQ="));     Serial.print(cfg.freqMHz, 3); Serial.println(F(" MHz"));
  Serial.print(F("  BW="));       Serial.print(cfg.bwkHz, 3);   Serial.println(F(" kHz"));
  Serial.print(F("  SF="));       Serial.println(cfg.sf);
  Serial.print(F("  CR="));       Serial.println(cfg.cr);
  Serial.print(F("  SYNC=0x"));   Serial.println(cfg.syncWord, HEX);
  Serial.print(F("  PWR="));      Serial.print(cfg.pwrDbm);     Serial.println(F(" dBm"));
  Serial.print(F("  PREAMBLE=")); Serial.println(cfg.preamble);
  Serial.print(F("  CRC="));      Serial.println(cfg.crcOn ? F("ON") : F("OFF"));
  Serial.print(F("  RX="));       Serial.println(rxEnabled ? F("ON") : F("OFF"));
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
  Serial.println(F("  AT+FREQ=<MHz>       / AT+FREQ?"));
  Serial.println(F("  AT+BW=<kHz>         / AT+BW?"));
  Serial.println(F("  AT+SF=<num>         / AT+SF?"));
  Serial.println(F("  AT+CR=<5..8>        / AT+CR?"));
  Serial.println(F("  AT+SYNC=<hex>       / AT+SYNC?   (e.g. 0x12)"));
  Serial.println(F("  AT+PWR=<dBm>        / AT+PWR?    (can be negative)"));
  Serial.println(F("  AT+PREAMBLE=<n>     / AT+PREAMBLE?"));
  Serial.println(F("  AT+CRC=ON|OFF       / AT+CRC?"));
  Serial.println(F(""));
  Serial.println(F("Batch set (auto save + auto apply):"));
  Serial.println(F("  AT+SET=<FREQ>,<BW>,<SF>,<CR>,<SYNC>,<PWR>,<PRE>,<CRC>"));
  Serial.println(F("    Example: AT+SET=2410.5,203.125,10,6,0x12,-2,16,OFF"));
  Serial.println(F(""));
  Serial.println(F("RX control:"));
  Serial.println(F("  AT+RX=ON            -> start RX"));
  Serial.println(F("  AT+RX=OFF           -> standby (stop RX)"));
  Serial.println(F(""));
  Serial.println(F("Diagnostics:"));
  Serial.println(F("  AT+RSSI?            -> last packet RSSI"));
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

  // For SX1280 the most reliable path is re-init with full LoRa params
  int st = radio.begin(cfg.freqMHz, cfg.bwkHz, cfg.sf, cfg.cr, cfg.syncWord, cfg.pwrDbm, cfg.preamble);
  if (st != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[SX1280] begin(cfg...) failed, code "));
      Serial.println(st);
    }
    return false;
  }

  // Apply CRC (GRACEFUL)
  st = radio.setCRC(cfg.crcOn);
  lastCrcSetStatus = st;

  if (st != RADIOLIB_ERR_NONE) {
    // If CRC ON was requested but not supported, force OFF and continue.
    if (cfg.crcOn) {
      crcForcedOff = true;
      cfg.crcOn = false;  // keep runtime cfg consistent

      // Try to explicitly disable CRC (best effort)
      (void)radio.setCRC(false);

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
  if (u == "AT+BW?")       { Serial.print(F("BW=")); Serial.println(cfg.bwkHz, 3); serialOK(); return true; }
  if (u == "AT+SF?")       { Serial.print(F("SF=")); Serial.println(cfg.sf); serialOK(); return true; }
  if (u == "AT+CR?")       { Serial.print(F("CR=")); Serial.println(cfg.cr); serialOK(); return true; }
  if (u == "AT+SYNC?")     { Serial.print(F("SYNC=0x")); Serial.println(cfg.syncWord, HEX); serialOK(); return true; }
  if (u == "AT+PWR?")      { Serial.print(F("PWR=")); Serial.println(cfg.pwrDbm); serialOK(); return true; }
  if (u == "AT+PREAMBLE?") { Serial.print(F("PREAMBLE=")); Serial.println(cfg.preamble); serialOK(); return true; }
  if (u == "AT+CRC?")      { Serial.print(F("CRC="));  Serial.println(cfg.crcOn ? F("ON") : F("OFF")); serialOK(); return true; }

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
    float v; if (!parseFloat(line.substring(8), v)) { serialERR(); return true; }
    cfg.freqMHz = v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+BW=")) {
    float v; if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    cfg.bwkHz = v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+SF=")) {
    long v; if (!parseInt(line.substring(6), v)) { serialERR(); return true; }
    cfg.sf = (uint8_t)v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+CR=")) {
    long v; if (!parseInt(line.substring(6), v) || v < 5 || v > 8) { serialERR(); return true; }
    cfg.cr = (uint8_t)v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+SYNC=")) {
    uint8_t v; if (!parseHexByte(line.substring(8), v)) { serialERR(); return true; }
    cfg.syncWord = v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+PWR=")) {
    long v; if (!parseInt(line.substring(7), v)) { serialERR(); return true; }
    cfg.pwrDbm = (int8_t)v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
  }
  if (u.startsWith("AT+PREAMBLE=")) {
    long v; if (!parseInt(line.substring(12), v) || v < 2 || v > 65535) { serialERR(); return true; }
    cfg.preamble = (uint16_t)v;
    radioReady = persistAndReapply();
    if (radioReady && crcForcedOff) Serial.println(F("WARN: CRC=ON not supported with current settings -> forced CRC=OFF"));
    radioReady ? serialOK() : serialERR();
    return true;
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

    if (!parseFloat(parts[0], f)) { serialERR(); return true; }
    if (!parseFloat(parts[1], bw)) { serialERR(); return true; }
    if (!parseInt(parts[2], sf)) { serialERR(); return true; }
    if (!parseInt(parts[3], cr) || cr < 5 || cr > 8) { serialERR(); return true; }
    if (!parseHexByte(parts[4], sync)) { serialERR(); return true; }
    if (!parseInt(parts[5], pwr)) { serialERR(); return true; }
    if (!parseInt(parts[6], pre) || pre < 2 || pre > 65535) { serialERR(); return true; }
    if (!parseBoolOnOff(parts[7], crcOn)) { serialERR(); return true; }

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
      if (!radioReady) {
        Serial.println(F("ERROR: RADIO_NOT_READY (set config and run AT+APPLY)"));
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
  if (receivedFlag) {
    receivedFlag = false;

    String str;
    int rx = radio.readData(str);

    if (rx == RADIOLIB_ERR_NONE) {
      lastPacketRSSI = radio.getRSSI();

      if (debugEnabled) {
        Serial.print(F("[SX1280] RX DATA: "));
        Serial.println(str);

        Serial.print(F("[SX1280] RSSI: "));
        Serial.print(radio.getRSSI(), 2);
        Serial.println(F(" dBm"));

        Serial.print(F("[SX1280] SNR:  "));
        Serial.print(radio.getSNR(), 2);
        Serial.println(F(" dB"));

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
