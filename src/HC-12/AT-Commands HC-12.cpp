// HC-12 AT Shell + Bridge (EEPROM + OLED) — safe BAUD change + defaults recovery
// Pini pentru ESP32 (adapteaza la placa ta):
//   MCU RX  <- HC-12 TX : 20
//   MCU TX  -> HC-12 RX : 21
//   SET (LOW=AT, HIGH=normal) : 1
//   LED status : 8

#include <Arduino.h>
#include <EEPROM.h>
#include <U8g2lib.h>

#define OLED_RESET   U8X8_PIN_NONE
#define OLED_SDA     5
#define OLED_SCL     6
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, OLED_RESET, OLED_SCL, OLED_SDA);

static void drawCentered(const char* text, int baselineY, const uint8_t* font) {
  u8g2.setFont(font);
  int w = u8g2.getStrWidth(text);
  int x = (128 - w) / 2; if (x < 0) x = 0;
  u8g2.drawStr(x, baselineY, text);
}
static void oled_setup() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setBusClock(400000);
  u8g2.clearBuffer();
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("HC-12", 63, u8g2_font_logisoso18_tr);
  u8g2.sendBuffer();
}

// ========= PINOUT =========
#if defined(ESP32)
  static const int HC12_RX_PIN  = 20; // MCU RX  <- HC-12 TX
  static const int HC12_TX_PIN  = 21; // MCU TX  -> HC-12 RX
  static const int HC12_SET_PIN = 1;  // LOW=AT, HIGH=normal
  static const int LED_GPIO     = 8;
  #define HC12_SERIAL  Serial1
#else
  #include <SoftwareSerial.h>
  static const int HC12_RX_PIN  = 10;
  static const int HC12_TX_PIN  = 11;
  static const int HC12_SET_PIN = 4;
  static const int LED_GPIO     = 13;
  SoftwareSerial HC12_SERIAL(HC12_RX_PIN, HC12_TX_PIN);
#endif

// ========= DEFAULTS & STATE =========
static constexpr bool debug_default_state = false;

struct HC12Config {
  uint32_t usbBaud     = 115200;  // consola USB
  uint32_t hcBaud      = 9600;    // baud HC-12
  uint8_t  fuMode      = 3;       // AT+FU1..4
  uint8_t  powerLevel  = 8;       // AT+P1..P8
  uint16_t channel     = 10;      // AT+Cnnn (0..127) -> 433.4 + 0.4*nnn MHz
  uint8_t  uartFormat  = 0;       // 0=8N1, 1=8O1, 2=8E1
  bool     bridgeOn    = true;    // USB<->HC12
};
HC12Config cfg;
const HC12Config cfgDefault;
static bool debugEnabled = debug_default_state;
static bool hc12Sleeping = false;

// ========= EEPROM =========
static const uint32_t EEPROM_MAGIC   = 0x48433132UL; // 'HC12'
static const uint16_t EEPROM_VERSION = 0x0002;
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
struct EepromRecord {
  uint32_t magic;
  uint16_t version;
  uint16_t length;
  HC12Config cfg;
  uint32_t crc;
};
static bool eepromLoad(HC12Config& out) {
  EepromRecord rec; EEPROM.get(0, rec);
  if (rec.magic != EEPROM_MAGIC) return false;
  if (rec.version != EEPROM_VERSION) return false;
  if (rec.length != (uint16_t)sizeof(HC12Config)) return false;
  uint32_t c = crc32_calc((const uint8_t*)&rec.cfg, sizeof(HC12Config));
  if (c != rec.crc) return false;
  out = rec.cfg; return true;
}
static bool eepromSave(const HC12Config& in) {
  EepromRecord rec;
  rec.magic = EEPROM_MAGIC; rec.version = EEPROM_VERSION;
  rec.length = (uint16_t)sizeof(HC12Config); rec.cfg = in;
  rec.crc = crc32_calc((const uint8_t*)&rec.cfg, sizeof(HC12Config));
  EEPROM.put(0, rec);
  return EEPROM.commit();
}

// ========= UTILS =========
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("#ERROR")); }
static inline void serialError(const __FlashStringHelper* msg) {
  Serial.print(F("#ERROR: "));
  Serial.println(msg);
}

static bool parseUInt(const String& s, uint32_t& out) {
  char* e=nullptr; unsigned long v=strtoul(s.c_str(), &e, 10);
  if (!(e && *e=='\0')) return false; out=(uint32_t)v; return true;
}
static bool parseU8(const String& s, uint8_t& out, uint8_t minv, uint8_t maxv) {
  char* e=nullptr; long v=strtol(s.c_str(), &e, 10);
  if (!(e && *e=='\0')) return false; if (v<minv||v>maxv) return false; out=(uint8_t)v; return true;
}
static bool parseU16(const String& s, uint16_t& out, uint16_t minv, uint16_t maxv) {
  char* e=nullptr; long v=strtol(s.c_str(), &e, 10);
  if (!(e && *e=='\0')) return false; if (v<minv||v>maxv) return false; out=(uint16_t)v; return true;
}
static bool parseOnOff(const String& s, bool& out) {
  String t=s; t.trim(); t.toUpperCase();
  if (t=="ON"||t=="1"||t=="TRUE"){out=true; return true;}
  if (t=="OFF"||t=="0"||t=="FALSE"){out=false; return true;}
  return false;
}
static const char* uartFormatName(uint8_t fmt) {
  switch (fmt) {
    case 1: return "8O1";
    case 2: return "8E1";
    default: return "8N1";
  }
}
static uint32_t uartSerialConfig(uint8_t fmt) {
  switch (fmt) {
    case 1: return SERIAL_8O1;
    case 2: return SERIAL_8E1;
    default: return SERIAL_8N1;
  }
}
static bool parseUartFormat(String s, uint8_t& out) {
  s.trim();
  s.toUpperCase();
  if (s=="8N1" || s=="N" || s=="0") { out=0; return true; }
  if (s=="8O1" || s=="O" || s=="1") { out=1; return true; }
  if (s=="8E1" || s=="E" || s=="2") { out=2; return true; }
  return false;
}
static void hc12Begin(uint32_t baud, uint8_t fmt) {
#if defined(ESP32)
  HC12_SERIAL.end();
  delay(20);
  HC12_SERIAL.begin(baud, uartSerialConfig(fmt), HC12_RX_PIN, HC12_TX_PIN);
#else
  (void)fmt;
  HC12_SERIAL.end();
  delay(20);
  HC12_SERIAL.begin(baud);
#endif
}
static String readSerialLineNonBlocking() {
  static String buf;
  while (Serial.available()) {
    char c=(char)Serial.read();
    if (c=='\r'||c=='\n') { if (buf.length()==0) continue; String line=buf; buf=""; line.trim(); return line; }
    else { if (buf.length()<256) buf+=c; }
  }
  return "";
}

// ========= HC-12 low-level =========
static void enterAT()    { digitalWrite(HC12_SET_PIN, LOW);  delay(60); }
static void exitAT()     { digitalWrite(HC12_SET_PIN, HIGH); delay(120); }

static void hc12WriteLine(const char* s) {
  HC12_SERIAL.write((const uint8_t*)s, strlen(s));
  HC12_SERIAL.write('\r'); HC12_SERIAL.write('\n');
}
static size_t readUntilTimeout(String& out, uint32_t timeoutMs=200) {
  out=""; uint32_t t0=millis();
  while (millis()-t0<timeoutMs) {
    while (HC12_SERIAL.available()) {
      char c=(char)HC12_SERIAL.read();
      out+=c;
      if (c=='\n') return out.length();
    }
    delay(2);
  }
  return out.length();
}
static bool atCmd(const char* cmd, String* resp=nullptr, uint32_t tout=200) {
  hc12WriteLine(cmd);
  String r; readUntilTimeout(r, tout);
  if (resp) *resp = r;
  return true;
}

// ========= Safe BAUD change (sequence: AT enter -> AT+Bxxxx -> EXIT AT -> retune UART) =========
static bool hc12_set_baud_safe(uint32_t newBaud) {
  switch (newBaud) {
    case 1200: case 2400: case 4800: case 9600:
    case 19200: case 38400: case 57600: case 115200: break;
    default: Serial.println(F("[BAUD] Unsupported value")); return false;
  }

  // 1) AT mode at current baud
  enterAT();

  // (optional) sanity ping
  HC12_SERIAL.print("AT\r\n");
  delay(60); while (HC12_SERIAL.available()) HC12_SERIAL.read();

  // 2) Send AT+Bxxxx — reply still at OLD baud!
  char cmd[20];
  snprintf(cmd, sizeof(cmd), "AT+B%lu", (unsigned long)newBaud);
  atCmd(cmd, nullptr, 120);

  // 3) Exit AT to APPLY
  exitAT();

  // 4) Switch MCU UART to NEW baud
  hc12Begin(newBaud, cfg.uartFormat);

  // 5) Verify via AT+RB
  enterAT();
  HC12_SERIAL.print("AT+RB\r\n");
  String r; readUntilTimeout(r, 200);
  exitAT();
  r.trim();
  if (r.indexOf(String("OK+B") + String(newBaud)) >= 0) {
    Serial.print(F("[BAUD] OK ")); Serial.println(newBaud);
    return true;
  }

  // Fallback for unele clone: AT+BAUDx (1..8)
  enterAT();
  uint8_t idx = 8; // default for 115200
  switch (newBaud) {
    case 1200: idx=1; break; case 2400: idx=2; break; case 4800: idx=3; break;
    case 9600: idx=4; break; case 19200: idx=5; break; case 38400: idx=6; break;
    case 57600: idx=7; break; case 115200: idx=8; break;
  }
  snprintf(cmd, sizeof(cmd), "AT+BAUD%u", (unsigned)idx);
  atCmd(cmd, nullptr, 120);
  exitAT();

  hc12Begin(newBaud, cfg.uartFormat);

  // Re-verify
  enterAT();
  HC12_SERIAL.print("AT+RB\r\n");
  r=""; readUntilTimeout(r, 200);
  exitAT();
  r.trim();
  if (r.indexOf(String("OK+B") + String(newBaud)) >= 0) {
    Serial.print(F("[BAUD] OK ")); Serial.println(newBaud);
    return true;
  }

  Serial.println(F("[BAUD] Verify failed (check SET wiring / clone FW)"));
  return false;
}

// ========= Force defaults (9600/FU3/CH001). Use best with power-on while SET=LOW. =========
static bool hc12_force_defaults() {
  // Enter AT
  digitalWrite(HC12_SET_PIN, LOW);
  delay(60);

  // Talk at 9600 (power-on-with-SET-low path guarantees 9600 AT; if not, we still try)
  hc12Begin(9600, 0);

  // Send DEFAULT
  HC12_SERIAL.print("AT+DEFAULT\r\n");
  delay(150);

  // Exit AT to apply
  digitalWrite(HC12_SET_PIN, HIGH);
  delay(120);

  // Keep UART at 9600 (module now on defaults)
  Serial.println(F("[DEFAULT] Restored (9600/8N1/FU3/CH001)."));
  return true;
}

// ========= Apply/Reset helpers =========
static bool applyConfigToHC12() {
  enterAT();

  char bcmd[20]; snprintf(bcmd, sizeof(bcmd), "AT+B%lu", (unsigned long)cfg.hcBaud);
  atCmd(bcmd, nullptr, 150);

  char ccmd[16]; snprintf(ccmd, sizeof(ccmd), "AT+C%03u", (unsigned)cfg.channel);
  atCmd(ccmd, nullptr, 150);

  char pcmd[12]; snprintf(pcmd, sizeof(pcmd), "AT+P%u", (unsigned)cfg.powerLevel);
  atCmd(pcmd, nullptr, 150);

  char fcmd[12]; snprintf(fcmd, sizeof(fcmd), "AT+FU%u", (unsigned)cfg.fuMode);
  atCmd(fcmd, nullptr, 150);

  char ucmd[12]; snprintf(ucmd, sizeof(ucmd), "AT+U%s", uartFormatName(cfg.uartFormat));
  atCmd(ucmd, nullptr, 150);

  exitAT();

  // Retune MCU UART la baudul curent HC-12
  hc12Begin(cfg.hcBaud, cfg.uartFormat);
  hc12Sleeping = false;
  return true;
}

static bool resetAndApply() {
  hc12Begin(cfg.hcBaud, cfg.uartFormat);
  return applyConfigToHC12();
}

static bool persistAndApply() {
  if (!eepromSave(cfg)) return false;
  return resetAndApply();
}

// ========= Printouts =========
static void printConfig() {
  Serial.println(F("CFG:"));
  Serial.print(F("  USB_BAUD="));  Serial.println(cfg.usbBaud);
  Serial.print(F("  HC_BAUD="));   Serial.println(cfg.hcBaud);
  Serial.print(F("  CHANNEL="));    Serial.println(cfg.channel);
  Serial.print(F("  POWER="));      Serial.println(cfg.powerLevel);
  Serial.print(F("  FU="));         Serial.println(cfg.fuMode);
  Serial.print(F("  UART="));       Serial.println(uartFormatName(cfg.uartFormat));
  Serial.print(F("  BRIDGE="));     Serial.println(cfg.bridgeOn ? F("ON") : F("OFF"));
  Serial.print(F("  SLEEP="));      Serial.println(hc12Sleeping ? F("YES") : F("NO"));
  float fMHz = 433.4f + 0.4f * (float)cfg.channel;
  Serial.print(F("  FREQ≈ ")); Serial.print(fMHz, 1); Serial.println(F(" MHz"));
}
static void printHelp() {
  Serial.println(F("AT commands for HC-12 (UART 433MHz) — safe BAUD / defaults"));
  Serial.println(F("Core:"));
  Serial.println(F("  AT / AT? / AT+HELP"));
  Serial.println(F("  AT+CFG?"));
  Serial.println(F("  AT+APPLY"));
  Serial.println(F("  AT+DEFAULT"));
  Serial.println(F("  AT+RESET"));
  Serial.println(F(""));
  Serial.println(F("Params (setter = save + reset/apply):"));
  Serial.println(F("  AT+BAUD=<1200..115200> / AT+BAUD?"));
  Serial.println(F("  AT+CHAN=<0..127>       / AT+CHAN?"));
  Serial.println(F("  AT+POWER=<1..8>        / AT+POWER?"));
  Serial.println(F("  AT+FU=<1..4>           / AT+FU?"));
  Serial.println(F("  AT+UART=8N1|8O1|8E1    / AT+UART?"));
  Serial.println(F("  AT+BRIDGE=ON|OFF       / AT+BRIDGE?"));
  Serial.println(F(""));
  Serial.println(F("Extras:"));
  Serial.println(F("  AT+V           (version)"));
  Serial.println(F("  AT+INFO?       (raw HC-12 AT+RX dump)"));
  Serial.println(F("  AT+RAW=<cmd>   (send raw HC-12 command, e.g. AT+RAW=AT+RB)"));
  Serial.println(F("  AT+SLEEP"));
  Serial.println(F("  AT+WAKE"));
  Serial.println(F(""));
  Serial.println(F("Note: orice linie non-AT se TRIMITE imediat prin HC-12 (CRLF)."));
}

// ========= AT handler =========
static bool handleAT(String lineRaw) {
  String line=lineRaw; line.trim();
  String u=line; u.toUpperCase();

  if (u=="AT") { serialOK(); return true; }
  if (u=="AT?" || u=="AT+HELP") { printHelp(); serialOK(); return true; }
  if (u=="AT+CFG?") { printConfig(); serialOK(); return true; }

  if (u=="AT+APPLY")   { bool ok=applyConfigToHC12(); ok?serialOK():serialERR(); return true; }
  if (u=="AT+DEFAULT") {
    if (hc12_force_defaults()) {
      cfg.hcBaud = 9600; cfg.fuMode = 3; cfg.channel = 1; cfg.powerLevel = 8; cfg.uartFormat = 0; hc12Sleeping = false;
      eepromSave(cfg); serialOK();
    } else serialERR();
    return true;
  }
  if (u=="AT+RESET")   { bool ok=resetAndApply(); ok?serialOK():serialERR(); return true; }

  if (u=="AT+DEBUG?")  { Serial.print(F("DEBUG=")); Serial.println(debugEnabled?F("ON"):F("OFF")); serialOK(); return true; }
  if (u=="AT+DEBUG")   { debugEnabled=!debugEnabled; Serial.print(F("DEBUG=")); Serial.println(debugEnabled?F("ON"):F("OFF")); serialOK(); return true; }
  if (u=="AT+DEBUG=ON"){ debugEnabled=true;  serialOK(); return true; }
  if (u=="AT+DEBUG=OFF"){debugEnabled=false; serialOK(); return true; }

  if (u=="AT+BAUD?")   { Serial.print(F("BAUD="));  Serial.println(cfg.hcBaud); serialOK(); return true; }
  if (u=="AT+CHAN?")   { Serial.print(F("CHAN="));  Serial.println(cfg.channel); serialOK(); return true; }
  if (u=="AT+POWER?")  { Serial.print(F("POWER=")); Serial.println(cfg.powerLevel); serialOK(); return true; }
  if (u=="AT+FU?")     { Serial.print(F("FU="));    Serial.println(cfg.fuMode); serialOK(); return true; }
  if (u=="AT+UART?")   { Serial.print(F("UART="));  Serial.println(uartFormatName(cfg.uartFormat)); serialOK(); return true; }
  if (u=="AT+BRIDGE?") { Serial.print(F("BRIDGE="));Serial.println(cfg.bridgeOn?F("ON"):F("OFF")); serialOK(); return true; }

  if (u.startsWith("AT+BAUD=")) {
    uint32_t v; if (!parseUInt(line.substring(8), v)) { serialERR(); return true; }
    if (hc12_set_baud_safe(v)) { cfg.hcBaud=v; eepromSave(cfg); serialOK(); } else serialERR();
    return true;
  }
  if (u.startsWith("AT+CHAN=")) {
    uint16_t ch; if (!parseU16(line.substring(8), ch, 0, 127)) { serialERR(); return true; }
    cfg.channel=ch; (persistAndApply()?serialOK():serialERR()); return true;
  }
  if (u.startsWith("AT+POWER=")) {
    uint8_t p; if (!parseU8(line.substring(9), p, 1, 8)) { serialERR(); return true; }
    cfg.powerLevel=p; (persistAndApply()?serialOK():serialERR()); return true;
  }
  if (u.startsWith("AT+FU=")) {
    uint8_t f; if (!parseU8(line.substring(6), f, 1, 4)) { serialERR(); return true; }
    cfg.fuMode=f; (persistAndApply()?serialOK():serialERR()); return true;
  }
  if (u.startsWith("AT+UART=")) {
    uint8_t fmt; if (!parseUartFormat(line.substring(8), fmt)) { serialERR(); return true; }
    cfg.uartFormat=fmt; (persistAndApply()?serialOK():serialERR()); return true;
  }
  if (u=="AT+BRIDGE=ON")  { cfg.bridgeOn=true;  eepromSave(cfg); serialOK(); return true; }
  if (u=="AT+BRIDGE=OFF") { cfg.bridgeOn=false; eepromSave(cfg); serialOK(); return true; }

  // Version (HC-12: AT+V)
  if (u=="AT+V" || u=="AT+VERSION?") {
    enterAT(); HC12_SERIAL.print("AT+V\r\n");
    String r; readUntilTimeout(r, 250); exitAT(); r.trim();
    if (r.length()) Serial.println(r);
    serialOK(); return true;
  }

  if (u=="AT+INFO?") {
    enterAT(); HC12_SERIAL.print("AT+RX\r\n");
    String r; readUntilTimeout(r, 400); exitAT(); r.trim();
    if (r.length()) Serial.println(r);
    serialOK(); return true;
  }

  if (u.startsWith("AT+RAW=")) {
    String raw = line.substring(7);
    raw.trim();
    if (raw.length() == 0) { serialERR(); return true; }
    enterAT(); hc12WriteLine(raw.c_str());
    String r; readUntilTimeout(r, 400); exitAT(); r.trim();
    if (r.length()) Serial.println(r);
    serialOK(); return true;
  }

  // Passthrough extras
  if (u=="AT+SLEEP") { enterAT(); atCmd("AT+SLEEP", nullptr, 150); exitAT(); hc12Sleeping = true; serialOK(); return true; }
  if (u=="AT+WAKE")  {
    // simplified wake pulse
    digitalWrite(HC12_SET_PIN, HIGH); delay(50);
    digitalWrite(HC12_SET_PIN, LOW);  delay(50);
    digitalWrite(HC12_SET_PIN, HIGH); delay(120);
    hc12Sleeping = false;
    bool ok=applyConfigToHC12(); ok?serialOK():serialERR(); return true;
  }

  if (u.startsWith("AT")) return false;
  return false;
}

// ========= Setup / Loop =========
void setup() {
  pinMode(LED_GPIO, OUTPUT); digitalWrite(LED_GPIO, LOW);
  pinMode(HC12_SET_PIN, OUTPUT); digitalWrite(HC12_SET_PIN, HIGH); // normal mode by default

  // EEPROM
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.begin(115200); delay(100);
    Serial.println(F("[EEPROM] begin() failed!"));
  }

  // Config
  if (!eepromLoad(cfg)) { cfg = cfgDefault; eepromSave(cfg); }

  // USB
  Serial.begin(cfg.usbBaud);
  delay(300);
  Serial.println();
  Serial.print(F("[BOOT] DEBUG default = ")); Serial.println(debug_default_state?F("ON"):F("OFF"));

  // HC-12 UART
  hc12Begin(cfg.hcBaud, cfg.uartFormat);

  // Aplică setările actuale (asigurare)
  applyConfigToHC12();

  oled_setup();
  Serial.println(F("[READY] AT+HELP pentru comenzi. Orice non-AT -> trimis prin radio."));
}

void loop() {
  // LED heartbeat 1 Hz
  static uint32_t tLed=0; static bool led=0;
  if (millis()-tLed>=1000) { tLed=millis(); led=!led; digitalWrite(LED_GPIO, led?HIGH:LOW); }

  // USB line
  String line = readSerialLineNonBlocking();
  if (line.length()>0) {
    if (line.startsWith("AT") || line.startsWith("at")) {
      if (!handleAT(line)) serialERR();
    } else {
      if (!cfg.bridgeOn) {
        serialError(F("BRIDGE_OFF (send AT+BRIDGE=ON)"));
        return;
      }
      if (hc12Sleeping) {
        serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
        return;
      }
      if (debugEnabled) { Serial.print(F("[HC12] TX: ")); Serial.println(line); }
      hc12WriteLine(line.c_str());
    }
  }

  // HC-12 -> USB bridge
  if (cfg.bridgeOn && !hc12Sleeping) {
    while (HC12_SERIAL.available()) {
      int c = HC12_SERIAL.read();
      Serial.write((uint8_t)c);
    }
  }
}
