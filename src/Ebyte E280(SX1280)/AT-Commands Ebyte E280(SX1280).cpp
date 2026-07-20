#include <Arduino.h>
#include <EEPROM.h>
#include <U8g2lib.h>
#include <Wire.h>

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
  Wire.end();
  delay(5);
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(400000);
  delay(10);

  u8g2.setBusClock(400000);
  u8g2.begin();
  u8g2.setPowerSave(0);
  u8g2.setContrast(255);

  u8g2.clearBuffer();
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("E280", 63, u8g2_font_logisoso18_tr);
  u8g2.sendBuffer();
}

// ------------------ PINOUT (Ebyte E280-2G4T12S, UART/TTL) ------------------
static const int UART1_RX_PIN = 20;  // ESP32 RX  <- E280 TXD
static const int UART1_TX_PIN = 21;  // ESP32 TX  -> E280 RXD

static const int E280_M0_PIN  = 10;
static const int E280_M1_PIN  = 3;
static const int E280_M2_PIN  = 2;
static const int E280_AUX_PIN = 1;

static const int LED_PIN = 8;

// ------------------ UART BAUDS ------------------
static const uint32_t USB_BAUD               = 115200;
static const uint32_t E280_CONFIG_BAUD       = 9600;  // fixed in configuration mode
static const uint32_t DEFAULT_E280_UART_BAUD = 9600;  // factory default

// ------------------ E280 RAW PROTOCOL ------------------
static const uint8_t E280_CMD_SAVE       = 0xC0;
static const uint8_t E280_CMD_READ       = 0xC1;
static const uint8_t E280_CMD_TEMP       = 0xC2;
static const uint8_t E280_CMD_VERSION    = 0xC3;
static const uint8_t E280_CMD_RESET      = 0xC4;
static const uint8_t E280_CMD_LOCAL_WIN  = 0xE2;
static const uint8_t E280_CMD_REMOTE_WIN = 0xE3;

struct E280Config {
  uint8_t head;
  uint8_t addh;
  uint8_t addl;
  uint8_t sped;
  uint8_t chan;
  uint8_t option;
};

struct E280Version {
  uint8_t raw[8];
  uint8_t length;
};

static E280Config cfgDefault;
static E280Config cfgCurrent;

// Factory default from the E280-2G4T12S manual:
// C0 00 00 13 18 04 -> addr 0x0000, CHAN=0x18, 9600 8N1, 10 kbps, 12 dBm, push-pull.
static E280Config makeDefaultConfig() {
  E280Config c;
  c.head   = E280_CMD_SAVE;
  c.addh   = 0x00;
  c.addl   = 0x00;
  c.sped   = 0x13;
  c.chan   = 0x18;
  c.option = 0x04;
  return c;
}

// ------------------ EEPROM PERSISTENCE ------------------
static const uint32_t EEPROM_MAGIC   = 0x45323830UL; // "E280"
static const uint16_t EEPROM_VERSION = 0x0001;
static const size_t   EEPROM_SIZE    = 128;

struct EepromBlob {
  uint32_t magic;
  uint16_t version;
  uint16_t length;
  E280Config cfg;
  uint32_t crc;
};

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

static bool eepromLoad(E280Config& out) {
  EepromBlob b;
  EEPROM.get(0, b);
  if (b.magic != EEPROM_MAGIC) return false;
  if (b.version != EEPROM_VERSION) return false;
  if (b.length != (uint16_t)sizeof(E280Config)) return false;
  uint32_t c = crc32_calc((const uint8_t*)&b.cfg, sizeof(E280Config));
  if (c != b.crc) return false;
  out = b.cfg;
  return true;
}

static bool eepromSave(const E280Config& in) {
  EepromBlob b;
  b.magic   = EEPROM_MAGIC;
  b.version = EEPROM_VERSION;
  b.length  = (uint16_t)sizeof(E280Config);
  b.cfg     = in;
  b.crc     = crc32_calc((const uint8_t*)&b.cfg, sizeof(E280Config));
  EEPROM.put(0, b);
  return EEPROM.commit();
}

// ------------------ RUNTIME STATE ------------------
enum E280RuntimeMode {
  E280_MODE_TRANSMISSION,
  E280_MODE_RSSI,
  E280_MODE_RANGING,
  E280_MODE_CONFIGURATION,
  E280_MODE_LOW_POWER
};

static E280RuntimeMode currentMode = E280_MODE_TRANSMISSION;
static E280RuntimeMode modeBeforeSleep = E280_MODE_TRANSMISSION;
static bool bridgeEnabled = true;
static bool bridgeBeforeSleep = true;
static bool debugEnabled = false;
static bool moduleSleeping = false;

static uint32_t ledTickMs = 0;
static bool ledState = false;

// ------------------ SERIAL HELPERS ------------------
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("#ERROR")); }
static inline void serialError(const __FlashStringHelper* msg) {
  Serial.print(F("#ERROR: "));
  Serial.println(msg);
}

static void serial1Begin(uint32_t baud) {
  Serial1.end();
  delay(10);
  Serial1.begin(baud, SERIAL_8N1, UART1_RX_PIN, UART1_TX_PIN);
  Serial1.setTimeout(250);
}

static void flushSerial1Input() {
  while (Serial1.available()) (void)Serial1.read();
}

static bool waitAUXHigh(uint32_t timeoutMs) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (digitalRead(E280_AUX_PIN) == HIGH) return true;
    delay(2);
  }
  return false;
}

static size_t readBytesWithTimeout(uint8_t* out, size_t wanted, uint32_t timeoutMs) {
  size_t n = 0;
  uint32_t t0 = millis();
  while (n < wanted && millis() - t0 < timeoutMs) {
    if (Serial1.available()) {
      out[n++] = (uint8_t)Serial1.read();
      t0 = millis();
    } else {
      delay(1);
    }
  }
  return n;
}

static const char* modeName(E280RuntimeMode mode) {
  switch (mode) {
    case E280_MODE_RSSI:          return "RSSI";
    case E280_MODE_RANGING:       return "RANGING";
    case E280_MODE_CONFIGURATION: return "CONFIGURATION";
    case E280_MODE_LOW_POWER:     return "LOW_POWER";
    default:                      return "TRANSMISSION";
  }
}

static uint8_t parityCode(const E280Config& c) { return (c.sped >> 6) & 0x03; }
static uint8_t baudCode(const E280Config& c)   { return (c.sped >> 3) & 0x07; }
static uint8_t airCode(const E280Config& c)    { return c.sped & 0x07; }

static bool fixedPointEnabled(const E280Config& c) { return (c.option & 0x80) != 0; }
static bool longRangeMode(const E280Config& c)     { return (c.option & 0x40) != 0; }
static bool freqHopEnabled(const E280Config& c)    { return (c.option & 0x20) != 0; }
static bool hostRole(const E280Config& c)          { return (c.option & 0x10) != 0; }
static bool lbtEnabled(const E280Config& c)        { return (c.option & 0x08) != 0; }
static bool ioPushPull(const E280Config& c)        { return (c.option & 0x04) != 0; }
static uint8_t powerCode(const E280Config& c)      { return c.option & 0x03; }

static void setParityCode(E280Config& c, uint8_t code) {
  c.sped = (uint8_t)((c.sped & 0x3F) | ((code & 0x03) << 6));
}

static void setBaudCode(E280Config& c, uint8_t code) {
  c.sped = (uint8_t)((c.sped & 0xC7) | ((code & 0x07) << 3));
}

static void setAirCode(E280Config& c, uint8_t code) {
  c.sped = (uint8_t)((c.sped & 0xF8) | (code & 0x07));
}

static void setOptionBit(E280Config& c, uint8_t mask, bool on) {
  if (on) c.option |= mask;
  else c.option &= (uint8_t)~mask;
}

static void setPowerCode(E280Config& c, uint8_t code) {
  c.option = (uint8_t)((c.option & 0xFC) | (code & 0x03));
}

static uint32_t baudFromCode(uint8_t code) {
  switch (code & 0x07) {
    case 0: return 1200;
    case 1: return 4800;
    case 2: return 9600;
    case 3: return 19200;
    case 4: return 57600;
    case 5: return 115200;
    case 6: return 460800;
    case 7: return 921600;
    default: return DEFAULT_E280_UART_BAUD;
  }
}

static const char* parityName(uint8_t code) {
  switch (code & 0x03) {
    case 1: return "8O1";
    case 2: return "8E1";
    default: return "8N1";
  }
}

static const char* airRateName(uint8_t code) {
  switch (code & 0x07) {
    case 0: return "ADAPTIVE";
    case 1: return "1K";
    case 2: return "5K";
    case 3: return "10K";
    case 4: return "50K";
    case 5: return "100K";
    case 6: return "1M_FLRC";
    case 7: return "2M_FSK";
    default: return "UNKNOWN";
  }
}

static int8_t powerDbmFromCode(uint8_t code) {
  switch (code & 0x03) {
    case 1: return 10;
    case 2: return 7;
    case 3: return 4;
    default: return 12;
  }
}

static bool validChannel(long chan) {
  return chan >= 0 && chan <= 39;
}

static uint8_t maxChannelForConfig(const E280Config& c) {
  if (freqHopEnabled(c)) return 39;        // 2402 + CHAN * 2 MHz -> 2402..2480
  if (airCode(c) == 6) return 33;          // 2400 + CHAN * 3 MHz -> up to 2499
  if (airCode(c) == 7) return 20;          // 2400 + CHAN * 5 MHz -> up to 2500
  return 39;
}

static bool validChannelForConfig(const E280Config& c) {
  return c.chan <= maxChannelForConfig(c);
}

static void setModePins(bool m2, bool m1, bool m0) {
  digitalWrite(E280_M2_PIN, m2 ? HIGH : LOW);
  digitalWrite(E280_M1_PIN, m1 ? HIGH : LOW);
  digitalWrite(E280_M0_PIN, m0 ? HIGH : LOW);
}

static bool setRuntimeMode(E280RuntimeMode mode) {
  pinMode(E280_M0_PIN, OUTPUT);
  pinMode(E280_M1_PIN, OUTPUT);
  pinMode(E280_M2_PIN, OUTPUT);

  switch (mode) {
    case E280_MODE_RSSI:
      setModePins(true, false, true);
      moduleSleeping = false;
      break;
    case E280_MODE_RANGING:
      setModePins(true, true, false);
      moduleSleeping = false;
      break;
    case E280_MODE_CONFIGURATION:
      setModePins(true, true, true);
      moduleSleeping = true;
      break;
    case E280_MODE_LOW_POWER:
      setModePins(false, false, false);
      moduleSleeping = true;
      break;
    default:
      setModePins(true, false, false);
      moduleSleeping = false;
      break;
  }

  delay(120);
  waitAUXHigh(1200);

  currentMode = mode;
  if (mode == E280_MODE_CONFIGURATION) {
    serial1Begin(E280_CONFIG_BAUD);
    delay(250);
  } else {
    serial1Begin(baudFromCode(baudCode(cfgCurrent)));
  }
  return true;
}

static void led1HzService() {
  uint32_t now = millis();
  if (now - ledTickMs >= 1000) {
    ledTickMs = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState ? HIGH : LOW);
  }
}

// ------------------ PARSERS ------------------
static String upperTrimmed(String s) {
  s.trim();
  s.toUpperCase();
  return s;
}

static bool parseUInt8(const String& s, uint8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseUInt16Auto(String s, uint16_t& out) {
  s.trim();
  int base = 10;
  if (s.startsWith("0x") || s.startsWith("0X")) {
    s = s.substring(2);
    base = 16;
  }
  char* endp = nullptr;
  unsigned long v = strtoul(s.c_str(), &endp, base);
  if (!(endp && *endp == '\0')) return false;
  if (v > 0xFFFF) return false;
  out = (uint16_t)v;
  return true;
}

static bool parseChannel(const String& s, uint8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (!validChannel(v)) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseOnOff(const String& s, bool& out) {
  String t = upperTrimmed(s);
  if (t == "ON" || t == "1" || t == "TRUE")  { out = true;  return true; }
  if (t == "OFF" || t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

static bool parseBaudCode(const String& s, uint8_t& code) {
  String t = upperTrimmed(s);
  long v = strtol(t.c_str(), nullptr, 10);
  switch (v) {
    case 1:
    case 1200: code = 0; return true;
    case 2:
    case 4800: code = 1; return true;
    case 3:
    case 9600: code = 2; return true;
    case 4:
    case 19200: code = 3; return true;
    case 5:
    case 57600: code = 4; return true;
    case 6:
    case 115200: code = 5; return true;
    case 7:
    case 460800: code = 6; return true;
    case 8:
    case 921600: code = 7; return true;
    default: return false;
  }
}

static bool parseParityCode(const String& s, uint8_t& code) {
  String t = upperTrimmed(s);
  if (t == "1" || t == "8N1" || t == "N" || t == "NONE") { code = 0; return true; }
  if (t == "2" || t == "8O1" || t == "O" || t == "ODD")  { code = 1; return true; }
  if (t == "3" || t == "8E1" || t == "E" || t == "EVEN") { code = 2; return true; }
  return false;
}

static bool parseAirCode(const String& s, uint8_t& code) {
  String t = upperTrimmed(s);
  if (t == "0" || t == "ADAPTIVE" || t == "AUTO" || t == "CONT" || t == "CONTINUOUS") { code = 0; return true; }
  if (t == "1" || t == "1K" || t == "1KBPS")       { code = 1; return true; }
  if (t == "2" || t == "5K" || t == "5KBPS")       { code = 2; return true; }
  if (t == "3" || t == "10K" || t == "10KBPS")     { code = 3; return true; }
  if (t == "4" || t == "50K" || t == "50KBPS")     { code = 4; return true; }
  if (t == "5" || t == "100K" || t == "100KBPS")   { code = 5; return true; }
  if (t == "6" || t == "1M" || t == "1M_FLRC")     { code = 6; return true; }
  if (t == "7" || t == "2M" || t == "2M_FSK")      { code = 7; return true; }
  return false;
}

static bool parsePowerCode(const String& s, uint8_t& code) {
  String t = upperTrimmed(s);
  long v = strtol(t.c_str(), nullptr, 10);
  if (v == 12) { code = 0; return true; }
  if (v == 10) { code = 1; return true; }
  if (v == 7)  { code = 2; return true; }
  if (v == 4)  { code = 3; return true; }
  if (v >= 1 && v <= 4) { code = (uint8_t)(v - 1); return true; }
  return false;
}

static bool parseRoleHost(const String& s, bool& host) {
  String t = upperTrimmed(s);
  if (t == "HOST" || t == "MASTER" || t == "TX" || t == "1") { host = true; return true; }
  if (t == "SLAVE" || t == "REMOTE" || t == "RX" || t == "0") { host = false; return true; }
  return false;
}

static bool parseRangeLong(const String& s, bool& longRange) {
  String t = upperTrimmed(s);
  if (t == "LONG" || t == "L" || t == "1") { longRange = true; return true; }
  if (t == "HP" || t == "HIGH" || t == "HIGH_PRECISION" || t == "A" || t == "0") {
    longRange = false;
    return true;
  }
  return false;
}

static bool parseIoPushPull(const String& s, bool& pushPull) {
  String t = upperTrimmed(s);
  if (t == "PP" || t == "PUSHPULL" || t == "PUSH_PULL" || t == "1") { pushPull = true; return true; }
  if (t == "OD" || t == "OPENDRAIN" || t == "OPEN_DRAIN" || t == "0") { pushPull = false; return true; }
  return false;
}

static int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static bool parseHexBytes(String text, uint8_t* out, size_t maxLen, size_t& outLen) {
  outLen = 0;
  text.trim();

  int high = -1;
  for (uint16_t i = 0; i < text.length(); i++) {
    char c = text.charAt(i);
    if (c == ' ' || c == ',' || c == ':' || c == '-') continue;

    int nibble = hexNibble(c);
    if (nibble < 0) return false;

    if (high < 0) {
      high = nibble;
    } else {
      if (outLen >= maxLen) return false;
      out[outLen++] = (uint8_t)((high << 4) | nibble);
      high = -1;
    }
  }

  return high < 0 && outLen > 0;
}

static bool startsWithAT(const String& s) {
  if (s.length() < 2) return false;
  char a = s[0], t = s[1];
  return (a == 'A' || a == 'a') && (t == 'T' || t == 't');
}

// ------------------ PRINTING ------------------
static float approximateFrequencyMHz(const E280Config& c) {
  uint8_t air = airCode(c);
  if (freqHopEnabled(c)) return 2402.0f + (float)c.chan * 2.0f;
  if (air == 1 || air == 2 || air == 3) return 2400.0f + (float)c.chan * 1.0f;
  if (air == 4 || air == 5) return 2400.0f + (float)c.chan * 2.0f;
  if (air == 6) return 2400.0f + (float)c.chan * 3.0f;
  if (air == 7) return 2400.0f + (float)c.chan * 5.0f;
  return NAN;
}

static void printHex2(uint8_t b) {
  if (b < 16) Serial.print('0');
  Serial.print(b, HEX);
}

static void printConfigPretty(const E280Config& c) {
  Serial.println(F("====== E280 CONFIGURATION ======"));
  Serial.print(F("RAW="));
  printHex2(c.head); Serial.print(' ');
  printHex2(c.addh); Serial.print(' ');
  printHex2(c.addl); Serial.print(' ');
  printHex2(c.sped); Serial.print(' ');
  printHex2(c.chan); Serial.print(' ');
  printHex2(c.option); Serial.println();

  Serial.print(F("ADDR=0x"));
  printHex2(c.addh);
  printHex2(c.addl);
  Serial.println();
  Serial.print(F("ADDH=")); Serial.println(c.addh);
  Serial.print(F("ADDL=")); Serial.println(c.addl);
  Serial.print(F("CHAN=")); Serial.println(c.chan);
  float freq = approximateFrequencyMHz(c);
  Serial.print(F("FREQ_APPROX="));
  if (isnan(freq)) Serial.println(F("ADAPTIVE"));
  else { Serial.print(freq, 3); Serial.println(F(" MHz")); }

  Serial.print(F("BAUD=")); Serial.println(baudFromCode(baudCode(c)));
  Serial.print(F("PARITY=")); Serial.println(parityName(parityCode(c)));
  Serial.print(F("AIR=")); Serial.println(airRateName(airCode(c)));
  Serial.print(F("POWER=")); Serial.print(powerDbmFromCode(powerCode(c))); Serial.println(F(" dBm"));

  Serial.print(F("FIXED=")); Serial.println(fixedPointEnabled(c) ? F("ON") : F("OFF"));
  Serial.print(F("RANGE=")); Serial.println(longRangeMode(c) ? F("LONG") : F("HIGH_PRECISION"));
  Serial.print(F("FHSS=")); Serial.println(freqHopEnabled(c) ? F("ON") : F("OFF"));
  Serial.print(F("ROLE=")); Serial.println(hostRole(c) ? F("HOST") : F("SLAVE"));
  Serial.print(F("LBT=")); Serial.println(lbtEnabled(c) ? F("ON") : F("OFF"));
  Serial.print(F("IOMODE=")); Serial.println(ioPushPull(c) ? F("PP") : F("OD"));

  Serial.print(F("MODE=")); Serial.println(modeName(currentMode));
  Serial.print(F("BRIDGE=")); Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
  Serial.print(F("SLEEP=")); Serial.println(moduleSleeping ? F("YES") : F("NO"));
  Serial.print(F("AUX=")); Serial.println(digitalRead(E280_AUX_PIN) == HIGH ? F("HIGH") : F("LOW"));
  Serial.println(F("================================"));
}

static void printVersion(const E280Version& v) {
  Serial.println(F("====== E280 VERSION ======"));
  Serial.print(F("RAW="));
  for (uint8_t i = 0; i < v.length; i++) {
    if (i) Serial.print(' ');
    printHex2(v.raw[i]);
  }
  Serial.println();
  if (v.length >= 4) {
    Serial.print(F("MODEL=0x"));
    printHex2(v.raw[1]);
    printHex2(v.raw[2]);
    Serial.println();
    Serial.print(F("VERSION=0x"));
    printHex2(v.raw[3]);
    Serial.println();
  }
  if (v.length >= 5) {
    Serial.print(F("POWER_CODE=0x"));
    printHex2(v.raw[4]);
    Serial.println();
  }
  Serial.println(F("========================="));
}

static void printHelp() {
  Serial.println(F("AT shell for Ebyte E280-2G4T12S (SX1280 UART/TTL)"));
  Serial.println(F(""));
  Serial.println(F("Core:"));
  Serial.println(F("  AT                      -> OK"));
  Serial.println(F("  AT? / AT+HELP           -> show this help"));
  Serial.println(F("  AT+CFG?                 -> read module config + print status"));
  Serial.println(F("  AT+APPLY                -> write current shadow config, save to module + EEPROM"));
  Serial.println(F("  AT+APPLY=TEMP           -> write current shadow config until module power-cycle"));
  Serial.println(F("  AT+DEFAULT              -> restore factory-safe defaults + save"));
  Serial.println(F("  AT+RESET                -> send C4 C4 C4 reset command"));
  Serial.println(F("  AT+INFO?                -> read C3 version/info bytes"));
  Serial.println(F("  AT+AUX?                 -> read AUX pin"));
  Serial.println(F("  AT+DEBUG=ON|OFF / ?     -> debug prints"));
  Serial.println(F(""));
  Serial.println(F("Bridge/mode:"));
  Serial.println(F("  AT+BRIDGE=ON|OFF / ?"));
  Serial.println(F("  AT+MODE=TRANSMISSION|RSSI|RANGING|CONFIGURATION|LOW_POWER"));
  Serial.println(F("  AT+MODE?"));
  Serial.println(F("  AT+SLEEP                -> LOW_POWER"));
  Serial.println(F("  AT+WAKE                 -> TRANSMISSION"));
  Serial.println(F("  AT+WINDOW=LOCAL|REMOTE  -> send E2/E3 config-window command"));
  Serial.println(F(""));
  Serial.println(F("Address/channel:"));
  Serial.println(F("  AT+ADDR=<0..65535|0x0000..0xFFFF> / AT+ADDR?"));
  Serial.println(F("  AT+ADDH=<0..255> / AT+ADDH?"));
  Serial.println(F("  AT+ADDL=<0..255> / AT+ADDL?"));
  Serial.println(F("  AT+CHAN=<0..39>  / AT+CHAN?"));
  Serial.println(F("  AT+FREQ?         -> approximate channel frequency"));
  Serial.println(F(""));
  Serial.println(F("Radio/UART params (setters auto save + apply):"));
  Serial.println(F("  AT+BAUD=<1200|4800|9600|19200|57600|115200|460800|921600> / AT+BAUD?"));
  Serial.println(F("  AT+BAUD1..8      -> same baud list by index"));
  Serial.println(F("  AT+PARITY=8N1|8O1|8E1 / AT+PARITY?"));
  Serial.println(F("  AT+PARITY1..3"));
  Serial.println(F("  AT+AIR=ADAPTIVE|1K|5K|10K|50K|100K|1M|2M / AT+AIR?"));
  Serial.println(F("  AT+AIR0..7"));
  Serial.println(F("  AT+POWER=<12|10|7|4> / AT+POWER?"));
  Serial.println(F("  AT+POWER1..4"));
  Serial.println(F("  AT+FIXED=ON|OFF / AT+FIXED?"));
  Serial.println(F("  AT+RANGE=HIGH|LONG / AT+RANGE?"));
  Serial.println(F("  AT+FHSS=ON|OFF / AT+FHSS?"));
  Serial.println(F("  AT+ROLE=SLAVE|HOST / AT+ROLE?"));
  Serial.println(F("  AT+LBT=ON|OFF / AT+LBT?"));
  Serial.println(F("  AT+IOMODE=PP|OD / AT+IOMODE?"));
  Serial.println(F(""));
  Serial.println(F("Batch set (auto save + apply):"));
  Serial.println(F("  AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,FIXED,RANGE,FHSS,ROLE,LBT,IOMODE"));
  Serial.println(F("    Example: AT+SETRADIO=0,0,24,9600,8N1,10K,12,OFF,HIGH,OFF,SLAVE,OFF,PP"));
  Serial.println(F(""));
  Serial.println(F("Fixed/broadcast send:"));
  Serial.println(F("  AT+SENDTO=ADDH,ADDL,CHAN,TEXT"));
  Serial.println(F("  AT+BROADCAST=CHAN,TEXT"));
  Serial.println(F(""));
  Serial.println(F("Diagnostics:"));
  Serial.println(F("  AT+RAWHEX=<hex bytes> -> send raw bytes to E280 UART and print response"));
  Serial.println(F(""));
  Serial.println(F("Non-AT USB lines are forwarded to the module when bridge is ON."));
}

// ------------------ MODULE I/O ------------------
static bool readConfigInConfigMode(E280Config& out) {
  flushSerial1Input();
  const uint8_t cmd[3] = { E280_CMD_READ, E280_CMD_READ, E280_CMD_READ };
  Serial1.write(cmd, sizeof(cmd));
  Serial1.flush();

  uint8_t resp[6] = {0};
  size_t n = readBytesWithTimeout(resp, sizeof(resp), 800);
  if (n != sizeof(resp)) return false;
  if (resp[0] != E280_CMD_SAVE && resp[0] != E280_CMD_TEMP) return false;

  out.head   = resp[0];
  out.addh   = resp[1];
  out.addl   = resp[2];
  out.sped   = resp[3];
  out.chan   = resp[4];
  out.option = resp[5];
  return true;
}

static bool sameConfigPayload(const E280Config& a, const E280Config& b) {
  return a.addh == b.addh &&
         a.addl == b.addl &&
         a.sped == b.sped &&
         a.chan == b.chan &&
         a.option == b.option;
}

static bool readConfigFromModule(E280Config& out, bool restoreMode = true) {
  E280RuntimeMode before = currentMode;
  setRuntimeMode(E280_MODE_CONFIGURATION);
  bool ok = readConfigInConfigMode(out);
  if (restoreMode) setRuntimeMode(before);
  return ok;
}

static bool writeConfigToModule(const E280Config& cfg, bool saveToFlash) {
  E280RuntimeMode before = currentMode;
  E280Config toWrite = cfg;
  toWrite.head = saveToFlash ? E280_CMD_SAVE : E280_CMD_TEMP;

  setRuntimeMode(E280_MODE_CONFIGURATION);
  flushSerial1Input();

  const uint8_t frame[6] = {
    toWrite.head, toWrite.addh, toWrite.addl, toWrite.sped, toWrite.chan, toWrite.option
  };
  Serial1.write(frame, sizeof(frame));
  Serial1.flush();
  bool auxOk = waitAUXHigh(1500);

  E280Config verify;
  bool verified = readConfigInConfigMode(verify) && sameConfigPayload(toWrite, verify);

  if (saveToFlash) {
    setRuntimeMode(E280_MODE_TRANSMISSION);
    return auxOk && verified;
  }

  setRuntimeMode(before == E280_MODE_CONFIGURATION ? E280_MODE_TRANSMISSION : before);
  return auxOk && (verified || !saveToFlash);
}

static bool resetModuleCommand() {
  E280RuntimeMode before = currentMode;
  setRuntimeMode(E280_MODE_CONFIGURATION);
  flushSerial1Input();
  const uint8_t cmd[3] = { E280_CMD_RESET, E280_CMD_RESET, E280_CMD_RESET };
  Serial1.write(cmd, sizeof(cmd));
  Serial1.flush();
  bool ok = waitAUXHigh(2500);
  setRuntimeMode(before == E280_MODE_CONFIGURATION ? E280_MODE_TRANSMISSION : before);
  return ok;
}

static bool readVersionFromModule(E280Version& out) {
  E280RuntimeMode before = currentMode;
  setRuntimeMode(E280_MODE_CONFIGURATION);
  flushSerial1Input();
  const uint8_t cmd[3] = { E280_CMD_VERSION, E280_CMD_VERSION, E280_CMD_VERSION };
  Serial1.write(cmd, sizeof(cmd));
  Serial1.flush();

  out.length = 0;
  size_t n = readBytesWithTimeout(out.raw, sizeof(out.raw), 1500);
  out.length = (uint8_t)n;
  bool ok = n >= 4 && out.raw[0] == E280_CMD_VERSION;

  setRuntimeMode(before == E280_MODE_CONFIGURATION ? E280_MODE_TRANSMISSION : before);
  return ok;
}

static bool sendConfigWindowCommand(bool remote) {
  if (moduleSleeping) {
    serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
    return false;
  }
  setRuntimeMode(E280_MODE_TRANSMISSION);
  uint8_t b = remote ? E280_CMD_REMOTE_WIN : E280_CMD_LOCAL_WIN;
  const uint8_t cmd[3] = { b, b, b };
  Serial1.write(cmd, sizeof(cmd));
  Serial1.flush();
  return waitAUXHigh(1500);
}

static bool applyCurrent(bool saveToFlash) {
  bool ok = writeConfigToModule(cfgCurrent, saveToFlash);
  if (ok && saveToFlash) eepromSave(cfgCurrent);
  return ok;
}

static bool applyCandidate(const E280Config& next, bool saveToFlash) {
  E280Config previous = cfgCurrent;
  cfgCurrent = next;
  if (applyCurrent(saveToFlash)) return true;
  cfgCurrent = previous;
  return false;
}

static bool sendFixedText(uint8_t addh, uint8_t addl, uint8_t chan, const String& payload) {
  if (moduleSleeping || currentMode == E280_MODE_CONFIGURATION || currentMode == E280_MODE_LOW_POWER) {
    serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
    return false;
  }
  setRuntimeMode(E280_MODE_TRANSMISSION);
  Serial1.write(addh);
  Serial1.write(addl);
  Serial1.write(chan);
  Serial1.write((const uint8_t*)payload.c_str(), payload.length());
  Serial1.flush();
  return waitAUXHigh(1500);
}

// ------------------ AT LINE READER ------------------
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
    }
    if (buf.length() < 240) buf += c;
  }
  return "";
}

// ------------------ AT HANDLER ------------------
static bool handleAT(const String& lineRaw) {
  String line = lineRaw;
  line.trim();
  String u = line;
  u.toUpperCase();

  if (u == "AT") { serialOK(); return true; }
  if (u == "AT?" || u == "AT+HELP") { printHelp(); serialOK(); return true; }

  if (u == "AT+DEBUG?") {
    Serial.print(F("DEBUG="));
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }

  if (u == "AT+BRIDGE?") {
    Serial.print(F("BRIDGE="));
    Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+BRIDGE=ON")  { bridgeEnabled = true;  serialOK(); return true; }
  if (u == "AT+BRIDGE=OFF") { bridgeEnabled = false; serialOK(); return true; }

  if (u == "AT+AUX?") {
    Serial.print(F("AUX="));
    Serial.println(digitalRead(E280_AUX_PIN) == HIGH ? F("HIGH") : F("LOW"));
    serialOK();
    return true;
  }

  if (u == "AT+MODE?") {
    Serial.print(F("MODE="));
    Serial.println(modeName(currentMode));
    serialOK();
    return true;
  }

  if (u.startsWith("AT+MODE=")) {
    String m = upperTrimmed(line.substring(8));
    bool ok = false;
    if (m == "TRANSMISSION" || m == "TRANSMIT" || m == "NORMAL" || m == "0") {
      ok = setRuntimeMode(E280_MODE_TRANSMISSION);
      bridgeEnabled = bridgeBeforeSleep;
    } else if (m == "RSSI" || m == "1") {
      ok = setRuntimeMode(E280_MODE_RSSI);
    } else if (m == "RANGING" || m == "RANGE_MODE" || m == "2") {
      ok = setRuntimeMode(E280_MODE_RANGING);
    } else if (m == "CONFIGURATION" || m == "CONFIG" || m == "PROGRAM" || m == "3") {
      ok = setRuntimeMode(E280_MODE_CONFIGURATION);
    } else if (m == "LOW_POWER" || m == "LOWPOWER" || m == "SLEEP" || m == "4") {
      modeBeforeSleep = currentMode;
      bridgeBeforeSleep = bridgeEnabled;
      ok = setRuntimeMode(E280_MODE_LOW_POWER);
    } else {
      serialERR();
      return true;
    }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+SLEEP") {
    modeBeforeSleep = currentMode;
    bridgeBeforeSleep = bridgeEnabled;
    setRuntimeMode(E280_MODE_LOW_POWER) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+WAKE") {
    E280RuntimeMode restore = (modeBeforeSleep == E280_MODE_LOW_POWER || modeBeforeSleep == E280_MODE_CONFIGURATION)
                              ? E280_MODE_TRANSMISSION
                              : modeBeforeSleep;
    bool ok = setRuntimeMode(restore);
    bridgeEnabled = bridgeBeforeSleep;
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+CFG?") {
    E280Config c;
    if (readConfigFromModule(c)) {
      cfgCurrent = c;
      eepromSave(cfgCurrent);
      printConfigPretty(cfgCurrent);
      serialOK();
    } else {
      printConfigPretty(cfgCurrent);
      Serial.println(F("#ERROR: MODULE_CONFIG_READ_FAILED (printed shadow config)"));
      serialERR();
    }
    return true;
  }

  if (u == "AT+INFO?") {
    E280Version v;
    if (readVersionFromModule(v)) {
      printVersion(v);
      serialOK();
    } else {
      serialERR();
    }
    return true;
  }

  if (u == "AT+APPLY") {
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+APPLY=TEMP") {
    applyCurrent(false) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+DEFAULT") {
    cfgCurrent = cfgDefault;
    bridgeEnabled = true;
    bridgeBeforeSleep = true;
    modeBeforeSleep = E280_MODE_TRANSMISSION;
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RESET") {
    resetModuleCommand() ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+WINDOW=")) {
    String w = upperTrimmed(line.substring(10));
    if (w == "LOCAL") {
      sendConfigWindowCommand(false) ? serialOK() : serialERR();
    } else if (w == "REMOTE") {
      sendConfigWindowCommand(true) ? serialOK() : serialERR();
    } else {
      serialERR();
    }
    return true;
  }

  // Queries
  if (u == "AT+ADDR?") {
    Serial.print(F("ADDR=0x"));
    printHex2(cfgCurrent.addh);
    printHex2(cfgCurrent.addl);
    Serial.println();
    serialOK();
    return true;
  }
  if (u == "AT+ADDH?") { Serial.print(F("ADDH=")); Serial.println(cfgCurrent.addh); serialOK(); return true; }
  if (u == "AT+ADDL?") { Serial.print(F("ADDL=")); Serial.println(cfgCurrent.addl); serialOK(); return true; }
  if (u == "AT+CHAN?") { Serial.print(F("CHAN=")); Serial.println(cfgCurrent.chan); serialOK(); return true; }
  if (u == "AT+FREQ?") {
    float freq = approximateFrequencyMHz(cfgCurrent);
    Serial.print(F("FREQ="));
    if (isnan(freq)) Serial.println(F("ADAPTIVE"));
    else { Serial.print(freq, 3); Serial.println(F(" MHz")); }
    serialOK();
    return true;
  }
  if (u == "AT+BAUD?") { Serial.print(F("BAUD=")); Serial.println(baudFromCode(baudCode(cfgCurrent))); serialOK(); return true; }
  if (u == "AT+PARITY?") { Serial.print(F("PARITY=")); Serial.println(parityName(parityCode(cfgCurrent))); serialOK(); return true; }
  if (u == "AT+AIR?") { Serial.print(F("AIR=")); Serial.println(airRateName(airCode(cfgCurrent))); serialOK(); return true; }
  if (u == "AT+POWER?" || u == "AT+PWR?") {
    Serial.print(F("POWER="));
    Serial.print(powerDbmFromCode(powerCode(cfgCurrent)));
    Serial.println(F(" dBm"));
    serialOK();
    return true;
  }
  if (u == "AT+FIXED?") { Serial.print(F("FIXED=")); Serial.println(fixedPointEnabled(cfgCurrent) ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+RANGE?") { Serial.print(F("RANGE=")); Serial.println(longRangeMode(cfgCurrent) ? F("LONG") : F("HIGH_PRECISION")); serialOK(); return true; }
  if (u == "AT+FHSS?" || u == "AT+FREQHOP?") { Serial.print(F("FHSS=")); Serial.println(freqHopEnabled(cfgCurrent) ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+ROLE?") { Serial.print(F("ROLE=")); Serial.println(hostRole(cfgCurrent) ? F("HOST") : F("SLAVE")); serialOK(); return true; }
  if (u == "AT+LBT?") { Serial.print(F("LBT=")); Serial.println(lbtEnabled(cfgCurrent) ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+IOMODE?") { Serial.print(F("IOMODE=")); Serial.println(ioPushPull(cfgCurrent) ? F("PP") : F("OD")); serialOK(); return true; }

  // Batch setter
  if (u.startsWith("AT+SETRADIO=")) {
    String p = line.substring(12);
    String parts[13];
    int count = 0;
    while (count < 13) {
      int comma = p.indexOf(',');
      if (comma < 0) {
        parts[count++] = p;
        break;
      }
      parts[count++] = p.substring(0, comma);
      p = p.substring(comma + 1);
    }
    if (count != 13) { serialERR(); return true; }
    for (int i = 0; i < 13; i++) parts[i].trim();

    uint8_t addh, addl, chan, baud, parity, air, pwr;
    bool fixed, rangeLong, fhss, roleHostValue, lbt, pp;
    if (!parseUInt8(parts[0], addh)) { serialERR(); return true; }
    if (!parseUInt8(parts[1], addl)) { serialERR(); return true; }
    if (!parseChannel(parts[2], chan)) { serialERR(); return true; }
    if (!parseBaudCode(parts[3], baud)) { serialERR(); return true; }
    if (!parseParityCode(parts[4], parity)) { serialERR(); return true; }
    if (!parseAirCode(parts[5], air)) { serialERR(); return true; }
    if (!parsePowerCode(parts[6], pwr)) { serialERR(); return true; }
    if (!parseOnOff(parts[7], fixed)) { serialERR(); return true; }
    if (!parseRangeLong(parts[8], rangeLong)) { serialERR(); return true; }
    if (!parseOnOff(parts[9], fhss)) { serialERR(); return true; }
    if (!parseRoleHost(parts[10], roleHostValue)) { serialERR(); return true; }
    if (!parseOnOff(parts[11], lbt)) { serialERR(); return true; }
    if (!parseIoPushPull(parts[12], pp)) { serialERR(); return true; }

    E280Config next = cfgCurrent;
    next.addh = addh;
    next.addl = addl;
    next.chan = chan;
    setBaudCode(next, baud);
    setParityCode(next, parity);
    setAirCode(next, air);
    setPowerCode(next, pwr);
    setOptionBit(next, 0x80, fixed);
    setOptionBit(next, 0x40, rangeLong);
    setOptionBit(next, 0x20, fhss);
    setOptionBit(next, 0x10, roleHostValue);
    setOptionBit(next, 0x08, lbt);
    setOptionBit(next, 0x04, pp);
    if (!validChannelForConfig(next)) { serialERR(); return true; }
    cfgCurrent = next;
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  // Setters
  if (u.startsWith("AT+ADDR=")) {
    uint16_t addr;
    if (!parseUInt16Auto(line.substring(8), addr)) { serialERR(); return true; }
    cfgCurrent.addh = (uint8_t)(addr >> 8);
    cfgCurrent.addl = (uint8_t)(addr & 0xFF);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+ADDH=")) {
    uint8_t v; if (!parseUInt8(line.substring(8), v)) { serialERR(); return true; }
    cfgCurrent.addh = v;
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+ADDL=")) {
    uint8_t v; if (!parseUInt8(line.substring(8), v)) { serialERR(); return true; }
    cfgCurrent.addl = v;
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+CHAN=")) {
    uint8_t v; if (!parseChannel(line.substring(8), v)) { serialERR(); return true; }
    if (cfgCurrent.chan == v) { serialOK(); return true; }
    E280Config next = cfgCurrent;
    next.chan = v;
    if (!validChannelForConfig(next)) { serialERR(); return true; }
    applyCandidate(next, true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+BAUD=")) {
    uint8_t code; if (!parseBaudCode(line.substring(8), code)) { serialERR(); return true; }
    setBaudCode(cfgCurrent, code);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+BAUD")) {
    uint8_t code; if (!parseBaudCode(u.substring(7), code)) { serialERR(); return true; }
    setBaudCode(cfgCurrent, code);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+PARITY=")) {
    uint8_t code; if (!parseParityCode(line.substring(10), code)) { serialERR(); return true; }
    setParityCode(cfgCurrent, code);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+PARITY")) {
    uint8_t code; if (!parseParityCode(u.substring(9), code)) { serialERR(); return true; }
    setParityCode(cfgCurrent, code);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+AIR=")) {
    uint8_t code; if (!parseAirCode(line.substring(7), code)) { serialERR(); return true; }
    if (airCode(cfgCurrent) == code) { serialOK(); return true; }
    E280Config next = cfgCurrent;
    setAirCode(next, code);
    if (!validChannelForConfig(next)) { serialERR(); return true; }
    applyCandidate(next, true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+AIR")) {
    uint8_t code; if (!parseAirCode(u.substring(6), code)) { serialERR(); return true; }
    if (airCode(cfgCurrent) == code) { serialOK(); return true; }
    E280Config next = cfgCurrent;
    setAirCode(next, code);
    if (!validChannelForConfig(next)) { serialERR(); return true; }
    applyCandidate(next, true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+POWER=") || u.startsWith("AT+PWR=")) {
    int eq = line.indexOf('=');
    uint8_t code; if (eq < 0 || !parsePowerCode(line.substring(eq + 1), code)) { serialERR(); return true; }
    if (powerCode(cfgCurrent) == code) { serialOK(); return true; }
    E280Config next = cfgCurrent;
    setPowerCode(next, code);
    applyCandidate(next, true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+POWER")) {
    uint8_t code; if (!parsePowerCode(u.substring(8), code)) { serialERR(); return true; }
    if (powerCode(cfgCurrent) == code) { serialOK(); return true; }
    E280Config next = cfgCurrent;
    setPowerCode(next, code);
    applyCandidate(next, true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+FIXED=")) {
    bool on; if (!parseOnOff(line.substring(9), on)) { serialERR(); return true; }
    if (fixedPointEnabled(cfgCurrent) == on) { serialOK(); return true; }
    E280Config next = cfgCurrent;
    setOptionBit(next, 0x80, on);
    applyCandidate(next, true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+RANGE=")) {
    bool on; if (!parseRangeLong(line.substring(9), on)) { serialERR(); return true; }
    setOptionBit(cfgCurrent, 0x40, on);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+FHSS=") || u.startsWith("AT+FREQHOP=")) {
    int eq = line.indexOf('=');
    bool on; if (eq < 0 || !parseOnOff(line.substring(eq + 1), on)) { serialERR(); return true; }
    E280Config next = cfgCurrent;
    setOptionBit(next, 0x20, on);
    if (!validChannelForConfig(next)) { serialERR(); return true; }
    cfgCurrent = next;
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+ROLE=")) {
    bool on; if (!parseRoleHost(line.substring(8), on)) { serialERR(); return true; }
    setOptionBit(cfgCurrent, 0x10, on);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+LBT=")) {
    bool on; if (!parseOnOff(line.substring(7), on)) { serialERR(); return true; }
    setOptionBit(cfgCurrent, 0x08, on);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+IOMODE=")) {
    bool pp; if (!parseIoPushPull(line.substring(10), pp)) { serialERR(); return true; }
    setOptionBit(cfgCurrent, 0x04, pp);
    applyCurrent(true) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+RAWHEX=")) {
    uint8_t tx[64];
    size_t txLen = 0;
    if (!parseHexBytes(line.substring(10), tx, sizeof(tx), txLen)) {
      serialERR();
      return true;
    }

    flushSerial1Input();
    Serial1.write(tx, txLen);
    Serial1.flush();

    uint8_t rx[64];
    size_t rxLen = readBytesWithTimeout(rx, sizeof(rx), 800);
    Serial.print(F("RAWHEX="));
    for (size_t i = 0; i < rxLen; i++) {
      if (i) Serial.print(' ');
      printHex2(rx[i]);
    }
    Serial.println();
    serialOK();
    return true;
  }

  if (u.startsWith("AT+SENDTO=")) {
    String p = line.substring(10);
    int c1 = p.indexOf(',');
    int c2 = (c1 >= 0) ? p.indexOf(',', c1 + 1) : -1;
    int c3 = (c2 >= 0) ? p.indexOf(',', c2 + 1) : -1;
    if (c1 < 0 || c2 < 0 || c3 < 0) { serialERR(); return true; }

    uint8_t addh, addl, chan;
    if (!parseUInt8(p.substring(0, c1), addh)) { serialERR(); return true; }
    if (!parseUInt8(p.substring(c1 + 1, c2), addl)) { serialERR(); return true; }
    if (!parseChannel(p.substring(c2 + 1, c3), chan)) { serialERR(); return true; }

    String payload = p.substring(c3 + 1);
    if (payload.length() == 0) { serialERR(); return true; }
    sendFixedText(addh, addl, chan, payload) ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+BROADCAST=")) {
    String p = line.substring(13);
    int comma = p.indexOf(',');
    if (comma < 0) { serialERR(); return true; }

    uint8_t chan;
    if (!parseChannel(p.substring(0, comma), chan)) { serialERR(); return true; }

    String payload = p.substring(comma + 1);
    if (payload.length() == 0) { serialERR(); return true; }
    sendFixedText(0xFF, 0xFF, chan, payload) ? serialOK() : serialERR();
    return true;
  }

  if (startsWithAT(line)) return false;
  return false;
}

// ------------------ SETUP / LOOP ------------------
void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  pinMode(E280_AUX_PIN, INPUT_PULLUP);
  pinMode(E280_M0_PIN, OUTPUT);
  pinMode(E280_M1_PIN, OUTPUT);
  pinMode(E280_M2_PIN, OUTPUT);
  setModePins(true, false, false);

  Serial.begin(USB_BAUD);
  delay(250);

  oled_setup();

  cfgDefault = makeDefaultConfig();
  cfgCurrent = cfgDefault;

  Serial.println();
  Serial.println(F("[BOOT] E280-2G4T12S AT Shell + Bridge"));
  Serial.print(F("[INFO] USB ")); Serial.print(USB_BAUD);
  Serial.print(F(" <-> E280 UART ")); Serial.println(DEFAULT_E280_UART_BAUD);

  serial1Begin(DEFAULT_E280_UART_BAUD);
  setRuntimeMode(E280_MODE_TRANSMISSION);

  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin failed (continuing without persistence)."));
  }

  E280Config fromModule;
  if (readConfigFromModule(fromModule)) {
    cfgCurrent = fromModule;
    eepromSave(cfgCurrent);
    Serial.println(F("[E280] Module config read successfully."));
  } else {
    E280Config fromEeprom;
    if (eepromLoad(fromEeprom)) {
      cfgCurrent = fromEeprom;
      Serial.println(F("[EEPROM] Loaded shadow config."));
    } else {
      cfgCurrent = cfgDefault;
      eepromSave(cfgCurrent);
      Serial.println(F("[WARN] Could not read module config; using E280 firmware defaults shadow."));
    }
  }

  setRuntimeMode(E280_MODE_TRANSMISSION);
  serial1Begin(baudFromCode(baudCode(cfgCurrent)));

  Serial.println(F("[READY] Bridge is ON by default. Type AT+HELP for commands."));
  Serial.println(F("--------------------------------------------------"));
  Serial.println(F("USB line starting with AT -> handled locally."));
  Serial.println(F("Other lines -> forwarded to E280 (CRLF)."));
  Serial.println(F("E280->USB is RAW."));
  Serial.println(F("--------------------------------------------------"));
}

void loop() {
  led1HzService();

  String line = readLineUSB();
  if (line.length() > 0) {
    if (startsWithAT(line)) {
      if (!handleAT(line)) serialERR();
    } else {
      if (!bridgeEnabled) {
        serialError(F("BRIDGE_OFF (send AT+BRIDGE=ON)"));
      } else if (moduleSleeping || currentMode == E280_MODE_CONFIGURATION || currentMode == E280_MODE_LOW_POWER) {
        serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
      } else {
        Serial1.write((const uint8_t*)line.c_str(), line.length());
        Serial1.write('\r');
        Serial1.write('\n');
        Serial1.flush();
      }
    }
  }

  while (!moduleSleeping && Serial1.available()) {
    int c = Serial1.read();
    Serial.write((uint8_t)c);
  }
}
