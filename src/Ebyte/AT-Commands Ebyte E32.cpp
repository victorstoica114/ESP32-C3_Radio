#include <Arduino.h>
#include <LoRa_E32.h>
#include <EEPROM.h>
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

// =============================================================================
// HW (ESP32-C3) PINS
// =============================================================================
static const int UART1_RX_PIN = 20;   // ESP32 RX  <- E32 TX
static const int UART1_TX_PIN = 21;   // ESP32 TX  -> E32 RX

static const int E32_M0_PIN   = 10;
static const int E32_M1_PIN   = 3;
static const int E32_AUX_PIN  = 1;    // AUX connected

static const int LED_PIN      = 8;

// =============================================================================
// UART BAUDS
// =============================================================================
static const uint32_t USB_BAUD              = 115200;
static const uint32_t DEFAULT_E32_UART_BAUD = 115200;  // keep EXACT as requested
static const uint32_t E32_PROG_BAUD         = 9600;    // PROGRAM/config mode

// =============================================================================
// DEFAULTS (firmware defaults)
// =============================================================================
static const uint8_t DEF_ADDH  = 0;
static const uint8_t DEF_ADDL  = 0;
static const uint8_t DEF_CHAN  = 23;   // 433MHz base + 23

// Raw bitfield codes (stable in E32 protocol)
static const uint8_t DEF_UART_BAUD_CODE   = 7; // 0..7 -> 1200..115200 (7 = 115200)
static const uint8_t DEF_UART_PARITY_CODE = 0; // 0=8N1, 1=8O1, 2=8E1
static const uint8_t DEF_AIR_RATE_CODE    = 5; // 0=0.3,1=1.2,2=2.4,3=4.8,4=9.6,5=19.2 kbps

static const uint8_t DEF_FIXED_CODE   = 0; // 0=transparent, 1=fixed
static const uint8_t DEF_FEC_CODE     = 1; // 0=OFF, 1=ON
static const uint8_t DEF_POWER_CODE   = 0; // 0..3 (0 is typically max power)
static const uint8_t DEF_WOR_CODE     = 0; // 0..7 -> 250..2000ms
static const uint8_t DEF_IODRIVE_CODE = 1; // 0=open-drain, 1=push-pull

// =============================================================================
// POWER mapping (display only). Actual dBm depends on the exact E32 module.
// For E32-xxxT20 modules this is typically 20/17/14/10 dBm.
// =============================================================================
static const int8_t POWER_DBM_BY_CODE[4] = { 20, 17, 14, 10 };

// =============================================================================
// EEPROM persistence
// =============================================================================
static const uint32_t EEPROM_MAGIC   = 0x45333241UL; // "E32A"
static const uint16_t EEPROM_VERSION = 0x0001;
static const size_t   EEPROM_SIZE    = 512;

struct EepromBlob {
  uint32_t magic;
  uint16_t version;
  uint16_t length;
  Configuration cfg;
  uint32_t crc;
};

static void oled_setup() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setBusClock(400000);

  u8g2.clearBuffer();

  // Safe sizes for 2 lines on 128x64 without clipping
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("E32", 63, u8g2_font_logisoso18_tr);

  u8g2.sendBuffer();
}

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

static bool eepromLoad(Configuration& out) {
  EepromBlob b;
  EEPROM.get(0, b);
  if (b.magic != EEPROM_MAGIC) return false;
  if (b.version != EEPROM_VERSION) return false;
  if (b.length != (uint16_t)sizeof(Configuration)) return false;
  uint32_t c = crc32_calc((const uint8_t*)&b.cfg, sizeof(Configuration));
  if (c != b.crc) return false;
  out = b.cfg;
  return true;
}

static bool eepromSave(const Configuration& in) {
  EepromBlob b;
  b.magic   = EEPROM_MAGIC;
  b.version = EEPROM_VERSION;
  b.length  = (uint16_t)sizeof(Configuration);
  b.cfg     = in;
  b.crc     = crc32_calc((const uint8_t*)&b.cfg, sizeof(Configuration));
  EEPROM.put(0, b);
  return EEPROM.commit();
}

// =============================================================================
// E32 instance
// NOTE: library wants an enum; we keep 9600 for config ops.
// We manually set Serial1 baud for NORMAL/bridge.
// =============================================================================
LoRa_E32 e32(&Serial1, (byte)E32_AUX_PIN, (byte)E32_M0_PIN, (byte)E32_M1_PIN, UART_BPS_RATE_9600);

// Shadow configs
static Configuration cfgDefault;
static Configuration cfgCurrent;

// Bridge / debug
static bool bridgeEnabled = true;
static bool debugEnabled  = false;
static bool moduleSleeping = false;
static bool bridgeBeforeSleep = true;

enum E32RuntimeMode {
  E32_MODE_NORMAL,
  E32_MODE_WAKE,
  E32_MODE_POWER_SAVE,
  E32_MODE_SLEEP
};
static E32RuntimeMode currentMode = E32_MODE_NORMAL;

// =============================================================================
// LED 1Hz (non-blocking)
// =============================================================================
static uint32_t ledTickMs = 0;
static bool ledState = false;

static void led1HzService() {
  uint32_t now = millis();
  if (now - ledTickMs >= 1000) { // toggle every 500ms => 1Hz blink
    ledTickMs = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState ? HIGH : LOW);
  }
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

static void serial1Begin(uint32_t baud) {
  Serial1.end();
  delay(10);
  Serial1.begin(baud, SERIAL_8N1, UART1_RX_PIN, UART1_TX_PIN);
  Serial1.setTimeout(200); // more robust for config ops
}

static void serial1Drain(uint32_t timeoutMs = 80) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    while (Serial1.available()) {
      Serial1.read();
      t0 = millis();
    }
    delay(2);
  }
}

static bool waitAUXHigh(uint32_t timeoutMs) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (digitalRead(E32_AUX_PIN) == HIGH) return true;
    delay(2);
  }
  return false;
}

static const char* e32ModeName(E32RuntimeMode mode) {
  switch (mode) {
    case E32_MODE_WAKE: return "WAKE";
    case E32_MODE_POWER_SAVE: return "POWER_SAVE";
    case E32_MODE_SLEEP: return "SLEEP";
    default: return "NORMAL";
  }
}

static uint32_t baudFromCode(uint8_t code);

static void e32SetModeProgram() {
  pinMode(E32_M0_PIN, OUTPUT);
  pinMode(E32_M1_PIN, OUTPUT);
  digitalWrite(E32_M0_PIN, HIGH);
  digitalWrite(E32_M1_PIN, HIGH);
  delay(120);
  waitAUXHigh(800);
  currentMode = E32_MODE_SLEEP;
  moduleSleeping = true;
}

static void e32SetModeNormal() {
  pinMode(E32_M0_PIN, OUTPUT);
  pinMode(E32_M1_PIN, OUTPUT);
  digitalWrite(E32_M0_PIN, LOW);
  digitalWrite(E32_M1_PIN, LOW);
  delay(120);
  waitAUXHigh(800);
  currentMode = E32_MODE_NORMAL;
  moduleSleeping = false;
}

static void e32SetModeWake() {
  pinMode(E32_M0_PIN, OUTPUT);
  pinMode(E32_M1_PIN, OUTPUT);
  digitalWrite(E32_M0_PIN, HIGH);
  digitalWrite(E32_M1_PIN, LOW);
  delay(120);
  waitAUXHigh(800);
  currentMode = E32_MODE_WAKE;
  moduleSleeping = false;
}

static void e32SetModePowerSave() {
  pinMode(E32_M0_PIN, OUTPUT);
  pinMode(E32_M1_PIN, OUTPUT);
  digitalWrite(E32_M0_PIN, LOW);
  digitalWrite(E32_M1_PIN, HIGH);
  delay(120);
  waitAUXHigh(800);
  currentMode = E32_MODE_POWER_SAVE;
  moduleSleeping = true;
}

static void e32SetModeSleep() {
  pinMode(E32_M0_PIN, OUTPUT);
  pinMode(E32_M1_PIN, OUTPUT);
  digitalWrite(E32_M0_PIN, HIGH);
  digitalWrite(E32_M1_PIN, HIGH);
  delay(120);
  waitAUXHigh(800);
  currentMode = E32_MODE_SLEEP;
  moduleSleeping = true;
}

static bool setRuntimeMode(E32RuntimeMode mode) {
  bool restoreBridge = moduleSleeping || currentMode == E32_MODE_POWER_SAVE || currentMode == E32_MODE_SLEEP;
  switch (mode) {
    case E32_MODE_NORMAL:
      e32SetModeNormal();
      serial1Begin(baudFromCode(cfgCurrent.SPED.uartBaudRate));
      if (restoreBridge) bridgeEnabled = bridgeBeforeSleep;
      return true;
    case E32_MODE_WAKE:
      e32SetModeWake();
      serial1Begin(baudFromCode(cfgCurrent.SPED.uartBaudRate));
      if (restoreBridge) bridgeEnabled = bridgeBeforeSleep;
      return true;
    case E32_MODE_POWER_SAVE:
      bridgeBeforeSleep = bridgeEnabled;
      Serial1.flush();
      e32SetModePowerSave();
      return true;
    case E32_MODE_SLEEP:
      bridgeBeforeSleep = bridgeEnabled;
      Serial1.flush();
      e32SetModeSleep();
      return true;
  }
  return false;
}

// Convert our baud code -> actual baud rate
static uint32_t baudFromCode(uint8_t code) {
  switch (code & 0x07) {
    case 0: return 1200;
    case 1: return 2400;
    case 2: return 4800;
    case 3: return 9600;
    case 4: return 19200;
    case 5: return 38400;
    case 6: return 57600;
    case 7: return 115200;
    default: return 115200;
  }
}

static const char* parityFromCode(uint8_t code) {
  switch (code) {
    case 0: return "8N1";
    case 1: return "8O1";
    case 2: return "8E1";
    default: return "8N1";
  }
}

static const char* airRateFromCode(uint8_t code) {
  switch (code) {
    case 0: return "0.3kbps";
    case 1: return "1.2kbps";
    case 2: return "2.4kbps";
    case 3: return "4.8kbps";
    case 4: return "9.6kbps";
    case 5: return "19.2kbps";
    default: return "UNKNOWN";
  }
}

static uint16_t worMsFromCode(uint8_t code) {
  return (uint16_t)((code & 0x07) * 250 + 250);
}

static int8_t powerDbmFromCode(uint8_t code) {
  code &= 0x03;
  return POWER_DBM_BY_CODE[code];
}

// =============================================================================
// Printing
// =============================================================================
static void printConfigPretty(Configuration c) {
  Serial.println(F("====== E32 CONFIGURATION ======"));
  Serial.print(F("ADDH: ")); Serial.println(c.ADDH);
  Serial.print(F("ADDL: ")); Serial.println(c.ADDL);
  Serial.print(F("CHAN: ")); Serial.println(c.CHAN);

  Serial.println(F("\n--- SPEED ---"));
  Serial.print(F("UART Baud: "));
  Serial.print(baudFromCode(c.SPED.uartBaudRate));
  Serial.println(F("bps"));
  Serial.print(F("UART Parity: "));
  Serial.println(parityFromCode(c.SPED.uartParity));
  Serial.print(F("Air Data Rate: "));
  Serial.println(airRateFromCode(c.SPED.airDataRate));

  Serial.println(F("\n--- OPTION ---"));
  Serial.print(F("Fixed Transmission: "));
  Serial.println(c.OPTION.fixedTransmission ? F("Fixed") : F("Transparent"));
  Serial.print(F("FEC: "));
  Serial.println(c.OPTION.fec ? F("Enable") : F("Disable"));
  Serial.print(F("TX Power: code "));
  Serial.print((int)c.OPTION.transmissionPower);
  Serial.print(F(" ("));
  Serial.print(powerDbmFromCode(c.OPTION.transmissionPower));
  Serial.println(F(" dBm)"));
  Serial.print(F("WOR timing: "));
  Serial.print(worMsFromCode(c.OPTION.wirelessWakeupTime));
  Serial.println(F("ms"));
  Serial.print(F("IO mode: "));
  Serial.println(c.OPTION.ioDriveMode ? F("PushPull") : F("OpenDrain"));
  Serial.print(F("Runtime mode: "));
  Serial.println(e32ModeName(currentMode));
  Serial.print(F("Bridge: "));
  Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
  Serial.print(F("AUX: "));
  Serial.println(digitalRead(E32_AUX_PIN) == HIGH ? F("HIGH") : F("LOW"));

  Serial.println(F("================================"));
}

static void printModuleInfo(ModuleInformation mi) {
  Serial.println(F("====== E32 MODULE INFO ======"));
  Serial.print(F("HEAD: ")); Serial.println(mi.HEAD, HEX);
  Serial.print(F("Freq: ")); Serial.println(mi.frequency, HEX);
  Serial.print(F("Vers: ")); Serial.println(mi.version, HEX);
  Serial.print(F("Feat: ")); Serial.println(mi.features, HEX);
  Serial.println(F("============================="));
}

// =============================================================================
// Default config generator
// =============================================================================
static Configuration makeDefaultConfig() {
  Configuration c;
  c.HEAD = 0xC0;
  c.ADDH = DEF_ADDH;
  c.ADDL = DEF_ADDL;
  c.CHAN = DEF_CHAN;

  c.SPED.uartBaudRate = DEF_UART_BAUD_CODE;
  c.SPED.uartParity   = DEF_UART_PARITY_CODE;
  c.SPED.airDataRate  = DEF_AIR_RATE_CODE;

  c.OPTION.fixedTransmission  = DEF_FIXED_CODE;
  c.OPTION.fec                = DEF_FEC_CODE;
  c.OPTION.transmissionPower  = DEF_POWER_CODE;
  c.OPTION.wirelessWakeupTime = DEF_WOR_CODE;
  c.OPTION.ioDriveMode        = DEF_IODRIVE_CODE;

  return c;
}

// =============================================================================
// Module I/O (PROGRAM mode + 9600) then back to NORMAL + module baud
// =============================================================================
static bool readConfigFromModule(Configuration& outCfg, ModuleInformation* outInfo = nullptr) {
  e32SetModeProgram();
  serial1Begin(E32_PROG_BAUD);
  delay(100);
  waitAUXHigh(1200);

  ResponseStructContainer cc = e32.getConfiguration();
  if (cc.status.code != 1) {
    Serial.print(F("#ERROR: getConfiguration: "));
    Serial.println(cc.status.getResponseDescription());
    cc.close();

    e32SetModeNormal();
    serial1Begin(DEFAULT_E32_UART_BAUD);
    return false;
  }
  outCfg = *(Configuration*)cc.data;
  cc.close();

  if (outInfo) {
    ResponseStructContainer ii = e32.getModuleInformation();
    if (ii.status.code == 1) *outInfo = *(ModuleInformation*)ii.data;
    ii.close();
  }

  e32SetModeNormal();
  serial1Begin(baudFromCode(outCfg.SPED.uartBaudRate));
  delay(30);
  return true;
}

static bool writeConfigToModule(const Configuration& inCfg, PROGRAM_COMMAND saveMode) {
  e32SetModeProgram();
  serial1Begin(E32_PROG_BAUD);
  delay(120);
  waitAUXHigh(1500);

  ResponseStatus rs = e32.setConfiguration(inCfg, saveMode);
  if (rs.code != 1) {
    Serial.print(F("#ERROR: setConfiguration: "));
    Serial.println(rs.getResponseDescription());

    // Recovery: back to NORMAL and try to re-sync baud to current shadow
    e32SetModeNormal();
    serial1Begin(baudFromCode(cfgCurrent.SPED.uartBaudRate));
    return false;
  }

  waitAUXHigh(1500);

  if (saveMode == WRITE_CFG_PWR_DWN_SAVE) {
    ResponseStatus resetRs = e32.resetModule();
    if (resetRs.code != 1) {
      Serial.print(F("#ERROR: resetModule after config: "));
      Serial.println(resetRs.getResponseDescription());
      e32SetModeNormal();
      serial1Begin(baudFromCode(inCfg.SPED.uartBaudRate));
      serial1Drain();
      return false;
    }
    waitAUXHigh(1500);
  }

  e32SetModeNormal();
  serial1Begin(baudFromCode(inCfg.SPED.uartBaudRate));
  delay(200);
  serial1Drain();
  return true;
}

static bool resetModuleCommand() {
  e32SetModeProgram();
  serial1Begin(E32_PROG_BAUD);
  delay(120);
  waitAUXHigh(1500);

  ResponseStatus rs = e32.resetModule();
  bool ok = (rs.code == 1);
  if (!ok) {
    Serial.print(F("#ERROR: resetModule: "));
    Serial.println(rs.getResponseDescription());
  }

  waitAUXHigh(1500);
  e32SetModeNormal();
  serial1Begin(baudFromCode(cfgCurrent.SPED.uartBaudRate));
  return ok;
}

static bool sendFixedText(uint8_t addh, uint8_t addl, uint8_t chan, const String& payload) {
  if (moduleSleeping || currentMode == E32_MODE_POWER_SAVE) {
    serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
    return false;
  }
  e32SetModeNormal();
  serial1Begin(baudFromCode(cfgCurrent.SPED.uartBaudRate));
  ResponseStatus rs = e32.sendFixedMessage(addh, addl, chan, payload);
  if (rs.code != 1) {
    Serial.print(F("#ERROR: sendFixedMessage: "));
    Serial.println(rs.getResponseDescription());
    return false;
  }
  return true;
}

// =============================================================================
// AT line reader (CRLF friendly)
// =============================================================================
static String readLineUSB() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (buf.length() == 0) continue; // swallow CRLF second char
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

static bool parseUInt8(const String& s, uint8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseChannel(const String& s, uint8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 31) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseOnOff(const String& s, bool& out) {
  String t = s; t.trim(); t.toUpperCase();
  if (t == "ON" || t == "1" || t == "TRUE")  { out = true;  return true; }
  if (t == "OFF"|| t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

// =============================================================================
// HELP
// =============================================================================
static void printHelp() {
  Serial.println(F("AT shell for Ebyte E32 (generic, raw-code based)"));
  Serial.println(F(""));
  Serial.println(F("Core:"));
  Serial.println(F("  AT                 -> OK"));
  Serial.println(F("  AT+HELP            -> help"));
  Serial.println(F("  AT+CFG?            -> read+print module config + module info"));
  Serial.println(F("  AT+APPLY           -> apply current shadow config to module (SAVE) + EEPROM"));
  Serial.println(F("  AT+APPLY=TEMP      -> apply shadow config until module power-cycle"));
  Serial.println(F("  AT+DEFAULT         -> restore firmware defaults (SAVE) + EEPROM"));
  Serial.println(F("  AT+RESET           -> reset E32 module, then restore normal mode"));
  Serial.println(F("  AT+INFO?           -> read module information only"));
  Serial.println(F("  AT+AUX?            -> read AUX pin state"));
  Serial.println(F("  AT+BRIDGE=ON/OFF   -> enable/disable UART bridge"));
  Serial.println(F("  AT+BRIDGE?         -> print bridge state"));
  Serial.println(F("  AT+DEBUG=ON/OFF    -> debug prints"));
  Serial.println(F("  AT+DEBUG?          -> print debug state"));
  Serial.println(F("  AT+MODE?           -> print runtime mode"));
  Serial.println(F("  AT+MODE=NORMAL|WAKE|POWER_SAVE|SLEEP"));
  Serial.println(F("  AT+SLEEP           -> alias for AT+MODE=SLEEP"));
  Serial.println(F("  AT+WAKE            -> alias for AT+MODE=NORMAL"));
  Serial.println(F(""));
  Serial.println(F("Set all radio params (one shot):"));
  Serial.println(F("  AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,WOR,FEC,FIXED,IOMODE"));
  Serial.println(F("    - BAUD: 1..8   (1200..115200)"));
  Serial.println(F("    - PARITY: 1..3 (8N1/8O1/8E1)"));
  Serial.println(F("    - AIR: 1..6    (0.3..19.2 kbps)"));
  Serial.println(F("    - POWER: 1..4  (module-dependent TX power levels)"));
  Serial.println(F("    - WOR: 1..8    (250/500/750/1000/1250/1500/1750/2000 ms)"));
  Serial.println(F("    - FEC: 0/1, FIXED: 0/1, IOMODE: PP/OD"));
  Serial.println(F(""));
  Serial.println(F("Address / Channel:"));
  Serial.println(F("  AT+ADDH=<0..255>"));
  Serial.println(F("  AT+ADDH?"));
  Serial.println(F("  AT+ADDL=<0..255>"));
  Serial.println(F("  AT+ADDL?"));
  Serial.println(F("  AT+CHAN=<0..31>"));
  Serial.println(F("  AT+CHAN?"));
  Serial.println(F(""));
  Serial.println(F("Indexed setters:"));
  Serial.println(F("  AT+BAUD1..8      -> 1200,2400,4800,9600,19200,38400,57600,115200"));
  Serial.println(F("  AT+PARITY1..3    -> 8N1,8O1,8E1"));
  Serial.println(F("  AT+AIR1..6       -> 0.3,1.2,2.4,4.8,9.6,19.2 kbps"));
  Serial.println(F("  AT+POWER1..4     -> module-dependent TX power levels"));
  Serial.println(F("  AT+WORT1..8      -> 1=250ms,2=500ms,3=750ms,4=1000ms,5=1250ms,6=1500ms,7=1750ms,8=2000ms"));
  Serial.println(F("  AT+FEC=ON/OFF"));
  Serial.println(F("  AT+FEC?"));
  Serial.println(F("  AT+FIXED=ON/OFF"));
  Serial.println(F("  AT+FIXED?"));
  Serial.println(F("  AT+IOMODE=PP/OD"));
  Serial.println(F("  AT+IOMODE?"));
  Serial.println(F("  AT+SENDTO=ADDH,ADDL,CHAN,TEXT"));
  Serial.println(F("  AT+BROADCAST=CHAN,TEXT"));
}

// =============================================================================
// AT command handler
// =============================================================================
static bool handleAT(const String& lineRaw) {
  String line = lineRaw;
  line.trim();
  String u = line; u.toUpperCase();

  if (u == "AT") { serialOK(); return true; }
  if (u == "AT+HELP" || u == "AT?") { printHelp(); serialOK(); return true; }

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
    Serial.println(digitalRead(E32_AUX_PIN) == HIGH ? F("HIGH") : F("LOW"));
    serialOK();
    return true;
  }

  if (u == "AT+MODE?") {
    Serial.print(F("MODE="));
    Serial.println(e32ModeName(currentMode));
    serialOK();
    return true;
  }

  if (u.startsWith("AT+MODE=")) {
    String m = line.substring(8);
    m.trim(); m.toUpperCase();
    bool ok = false;
    if (m == "NORMAL" || m == "0") ok = setRuntimeMode(E32_MODE_NORMAL);
    else if (m == "WAKE" || m == "WAKE_UP" || m == "1") ok = setRuntimeMode(E32_MODE_WAKE);
    else if (m == "POWER_SAVE" || m == "POWERSAVE" || m == "POWER-SAVE" || m == "2") ok = setRuntimeMode(E32_MODE_POWER_SAVE);
    else if (m == "SLEEP" || m == "PROGRAM" || m == "3") ok = setRuntimeMode(E32_MODE_SLEEP);
    else { serialERR(); return true; }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+SLEEP") {
    setRuntimeMode(E32_MODE_SLEEP) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+WAKE") {
    setRuntimeMode(E32_MODE_NORMAL) ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+CFG?") {
    if (moduleSleeping) {
      printConfigPretty(cfgCurrent);
      Serial.println(F("SLEEP=YES"));
      serialOK();
      return true;
    }

    Configuration c;
    ModuleInformation mi;
    bool ok = readConfigFromModule(c, &mi);
    if (!ok) { serialERR(); return true; }
    printConfigPretty(c);
    printModuleInfo(mi);
    serialOK();
    return true;
  }

  if (u == "AT+APPLY") {
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+APPLY=TEMP") {
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_LOSE);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+DEFAULT") {
    cfgCurrent = cfgDefault;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) {
      eepromSave(cfgCurrent);
      bridgeEnabled = true;
      bridgeBeforeSleep = true;
      setRuntimeMode(E32_MODE_NORMAL);
    }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RESET") {
    bool ok = resetModuleCommand();
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+INFO?") {
    Configuration c;
    ModuleInformation mi;
    bool ok = readConfigFromModule(c, &mi);
    if (!ok) { serialERR(); return true; }
    printModuleInfo(mi);
    serialOK();
    return true;
  }

  // --- set all params in one command ---
  // AT+SETRADIO=ADDH,ADDL,CHAN,BAUD,PARITY,AIR,POWER,WOR,FEC,FIXED,IOMODE
  if (u.startsWith("AT+SETRADIO=")) {
    String p = line.substring(12);
    p.trim();

    int partsCount = 0;
    String parts[11];

    while (true) {
      int comma = p.indexOf(',');
      if (comma < 0) {
        parts[partsCount++] = p;
        break;
      }
      parts[partsCount++] = p.substring(0, comma);
      p = p.substring(comma + 1);
      if (partsCount >= 11) break;
    }

    if (partsCount != 11) { serialERR(); return true; }

    uint8_t addh, addl, chan;
    uint8_t baudIdx, parIdx, airIdx, pwrIdx, worIdx;
    uint8_t fec01, fixed01;
    String iom = parts[10]; iom.trim(); iom.toUpperCase();

    if (!parseUInt8(parts[0], addh)) { serialERR(); return true; }
    if (!parseUInt8(parts[1], addl)) { serialERR(); return true; }
    if (!parseChannel(parts[2], chan)) { serialERR(); return true; }

    if (!parseUInt8(parts[3], baudIdx) || baudIdx < 1 || baudIdx > 8) { serialERR(); return true; }
    if (!parseUInt8(parts[4], parIdx)  || parIdx  < 1 || parIdx  > 3) { serialERR(); return true; }
    if (!parseUInt8(parts[5], airIdx)  || airIdx  < 1 || airIdx  > 6) { serialERR(); return true; }
    if (!parseUInt8(parts[6], pwrIdx)  || pwrIdx  < 1 || pwrIdx  > 4) { serialERR(); return true; }
    if (!parseUInt8(parts[7], worIdx)  || worIdx  < 1 || worIdx  > 8) { serialERR(); return true; }

    if (!parseUInt8(parts[8], fec01)   || (fec01 > 1))  { serialERR(); return true; }
    if (!parseUInt8(parts[9], fixed01) || (fixed01 > 1)){ serialERR(); return true; }

    uint8_t ioDrive;
    if (iom == "PP" || iom == "PUSHPULL") ioDrive = 1;
    else if (iom == "OD" || iom == "OPENDRAIN") ioDrive = 0;
    else { serialERR(); return true; }

    // Map indices -> raw codes
    uint8_t baudCode;
    switch (baudIdx) {
      case 1: baudCode = 0; break;
      case 2: baudCode = 1; break;
      case 3: baudCode = 2; break;
      case 4: baudCode = 3; break;
      case 5: baudCode = 4; break;
      case 6: baudCode = 5; break;
      case 7: baudCode = 6; break;
      case 8: baudCode = 7; break;
      default: serialERR(); return true;
    }

    uint8_t parityCode = (uint8_t)(parIdx - 1); // 1..3 -> 0..2
    uint8_t airCode;
    switch (airIdx) {
      case 1: airCode = 0; break;
      case 2: airCode = 1; break;
      case 3: airCode = 2; break;
      case 4: airCode = 3; break;
      case 5: airCode = 4; break;
      case 6: airCode = 5; break;
      default: serialERR(); return true;
    }

    uint8_t powerCode = (uint8_t)(pwrIdx - 1); // 1..4 -> 0..3
    uint8_t worCode   = (uint8_t)(worIdx - 1); // 1..8 -> 0..7

    cfgCurrent.ADDH = addh;
    cfgCurrent.ADDL = addl;
    cfgCurrent.CHAN = chan;

    cfgCurrent.SPED.uartBaudRate = baudCode;
    cfgCurrent.SPED.uartParity   = parityCode;
    cfgCurrent.SPED.airDataRate  = airCode;

    cfgCurrent.OPTION.transmissionPower  = powerCode;
    cfgCurrent.OPTION.wirelessWakeupTime = worCode;
    cfgCurrent.OPTION.fec                = fec01 ? 1 : 0;
    cfgCurrent.OPTION.fixedTransmission  = fixed01 ? 1 : 0;
    cfgCurrent.OPTION.ioDriveMode        = ioDrive;

    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- direct numeric setters ---
  if (u == "AT+ADDH?") { Serial.print(F("ADDH=")); Serial.println(cfgCurrent.ADDH); serialOK(); return true; }
  if (u == "AT+ADDL?") { Serial.print(F("ADDL=")); Serial.println(cfgCurrent.ADDL); serialOK(); return true; }
  if (u == "AT+CHAN?") { Serial.print(F("CHAN=")); Serial.println(cfgCurrent.CHAN); serialOK(); return true; }
  if (u == "AT+BAUD?") { Serial.print(F("BAUD=")); Serial.println(baudFromCode(cfgCurrent.SPED.uartBaudRate)); serialOK(); return true; }
  if (u == "AT+PARITY?") { Serial.print(F("PARITY=")); Serial.println(parityFromCode(cfgCurrent.SPED.uartParity)); serialOK(); return true; }
  if (u == "AT+AIR?") { Serial.print(F("AIR=")); Serial.println(airRateFromCode(cfgCurrent.SPED.airDataRate)); serialOK(); return true; }
  if (u == "AT+POWER?") {
    Serial.print(F("POWER="));
    Serial.print(powerDbmFromCode(cfgCurrent.OPTION.transmissionPower));
    Serial.println(F(" dBm"));
    serialOK();
    return true;
  }
  if (u == "AT+WORT?") {
    Serial.print(F("WORT="));
    Serial.print(worMsFromCode(cfgCurrent.OPTION.wirelessWakeupTime));
    Serial.println(F(" ms"));
    serialOK();
    return true;
  }
  if (u == "AT+FEC?") { Serial.print(F("FEC=")); Serial.println(cfgCurrent.OPTION.fec ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+FIXED?") { Serial.print(F("FIXED=")); Serial.println(cfgCurrent.OPTION.fixedTransmission ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u == "AT+IOMODE?") { Serial.print(F("IOMODE=")); Serial.println(cfgCurrent.OPTION.ioDriveMode ? F("PP") : F("OD")); serialOK(); return true; }

  if (u.startsWith("AT+ADDH=")) {
    uint8_t v; if (!parseUInt8(line.substring(8), v)) { serialERR(); return true; }
    cfgCurrent.ADDH = v;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+ADDL=")) {
    uint8_t v; if (!parseUInt8(line.substring(8), v)) { serialERR(); return true; }
    cfgCurrent.ADDL = v;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+CHAN=")) {
    uint8_t v; if (!parseChannel(line.substring(8), v)) { serialERR(); return true; }
    cfgCurrent.CHAN = v;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Indexed commands ---
  if (u.startsWith("AT+BAUD")) {
    int idx = u.substring(7).toInt();
    uint8_t code;
    switch (idx) {
      case 1: code = 0; break;
      case 2: code = 1; break;
      case 3: code = 2; break;
      case 4: code = 3; break;
      case 5: code = 4; break;
      case 6: code = 5; break;
      case 7: code = 6; break;
      case 8: code = 7; break;
      default: serialERR(); return true;
    }
    cfgCurrent.SPED.uartBaudRate = code;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+PARITY")) {
    int idx = u.substring(9).toInt();
    uint8_t code;
    switch (idx) {
      case 1: code = 0; break; // 8N1
      case 2: code = 1; break; // 8O1
      case 3: code = 2; break; // 8E1
      default: serialERR(); return true;
    }
    cfgCurrent.SPED.uartParity = code;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+AIR")) {
    int idx = u.substring(6).toInt();
    uint8_t code;
    switch (idx) {
      case 1: code = 0; break;
      case 2: code = 1; break;
      case 3: code = 2; break;
      case 4: code = 3; break;
      case 5: code = 4; break;
      case 6: code = 5; break;
      default: serialERR(); return true;
    }
    cfgCurrent.SPED.airDataRate = code;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+POWER")) {
    int idx = u.substring(8).toInt();
    if (idx < 1 || idx > 4) { serialERR(); return true; }
    cfgCurrent.OPTION.transmissionPower = (uint8_t)(idx - 1);
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+WORT")) {
    int idx = u.substring(7).toInt();
    if (idx < 1 || idx > 8) { serialERR(); return true; }
    cfgCurrent.OPTION.wirelessWakeupTime = (uint8_t)(idx - 1);
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+FEC=")) {
    bool on; if (!parseOnOff(line.substring(7), on)) { serialERR(); return true; }
    cfgCurrent.OPTION.fec = on ? 1 : 0;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+FIXED=")) {
    bool on; if (!parseOnOff(line.substring(9), on)) { serialERR(); return true; }
    cfgCurrent.OPTION.fixedTransmission = on ? 1 : 0;
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u.startsWith("AT+IOMODE=")) {
    String m = line.substring(10);
    m.trim(); m.toUpperCase();
    if (m == "PP" || m == "PUSHPULL") {
      cfgCurrent.OPTION.ioDriveMode = 1;
    } else if (m == "OD" || m == "OPENDRAIN") {
      cfgCurrent.OPTION.ioDriveMode = 0;
    } else {
      serialERR();
      return true;
    }
    bool ok = writeConfigToModule(cfgCurrent, WRITE_CFG_PWR_DWN_SAVE);
    if (ok) eepromSave(cfgCurrent);
    ok ? serialOK() : serialERR();
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
    int c1 = p.indexOf(',');
    if (c1 < 0) { serialERR(); return true; }

    uint8_t chan;
    if (!parseChannel(p.substring(0, c1), chan)) { serialERR(); return true; }

    String payload = p.substring(c1 + 1);
    if (payload.length() == 0) { serialERR(); return true; }
    sendFixedText(0xFF, 0xFF, chan, payload) ? serialOK() : serialERR();
    return true;
  }

  if (startsWithAT(line)) return false;
  return false;
}

// =============================================================================
// Setup / Loop
// =============================================================================
void setup() {
  oled_setup();
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(USB_BAUD);
  delay(200);

  Serial.println();
  Serial.println(F("[BOOT] E32 AT Shell + Bridge (generic)"));
  Serial.print(F("[INFO] USB ")); Serial.print(USB_BAUD);
  Serial.print(F(" <-> E32 UART ")); Serial.println(DEFAULT_E32_UART_BAUD);

  // AUX must be input; pullup helps if line floats during reset
  pinMode(E32_AUX_PIN, INPUT_PULLUP);

  // init Serial1 at default bridge baud
  serial1Begin(DEFAULT_E32_UART_BAUD);

  // mode pins
  pinMode(E32_M0_PIN, OUTPUT);
  pinMode(E32_M1_PIN, OUTPUT);
  e32SetModeNormal();

  // IMPORTANT: initialize library pin handling
  e32.begin();

  // EEPROM
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin failed (continuing without persistence)."));
  }

  cfgDefault = makeDefaultConfig();
  cfgCurrent = cfgDefault;

  Configuration tmp;
  if (eepromLoad(tmp)) {
    cfgCurrent = tmp;
    if (debugEnabled) Serial.println(F("[EEPROM] Loaded shadow config."));
  } else {
    Configuration fromMod;
    ModuleInformation mi;
    if (readConfigFromModule(fromMod, &mi)) {
      cfgCurrent = fromMod;
      eepromSave(cfgCurrent);
      Serial.println(F("[EEPROM] Initialized from module config."));
      printConfigPretty(cfgCurrent);
      printModuleInfo(mi);
    } else {
      Serial.println(F("[WARN] Could not read module config now; using firmware defaults shadow."));
      eepromSave(cfgCurrent);
    }
  }

  // Ensure Serial1 matches current module baud
  serial1Begin(baudFromCode(cfgCurrent.SPED.uartBaudRate));

  Serial.println(F("[READY] Bridge is ON by default. Type AT+HELP for commands."));
  Serial.println(F("--------------------------------------------------"));
  Serial.println(F("USB line starting with AT -> handled locally."));
  Serial.println(F("Other lines -> forwarded to E32 (CRLF)."));
  Serial.println(F("E32->USB is RAW."));
  Serial.println(F("--------------------------------------------------"));
}

void loop() {
  // LED heartbeat 1Hz
  led1HzService();

  // 1) Read ONE line from USB (terminated by CR or LF; CRLF ok)
  String line = readLineUSB();
  if (line.length() > 0) {
    if (startsWithAT(line)) {
      if (!handleAT(line)) serialERR();
    } else {
      // Bridge payload (line-based) - SEND CRLF
      if (!bridgeEnabled) {
        serialError(F("BRIDGE_OFF (send AT+BRIDGE=ON)"));
      } else if (moduleSleeping) {
        serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
      } else {
        Serial1.write((const uint8_t*)line.c_str(), line.length());
        Serial1.write('\r');
        Serial1.write('\n');
      }
    }
  }

  // 2) E32 -> USB raw
  while (!moduleSleeping && Serial1.available()) {
    int c = Serial1.read();
    Serial.write((uint8_t)c);
  }
}
