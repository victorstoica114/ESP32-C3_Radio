#include <Arduino.h>
#include <Wire.h>
#include <RadioLib.h>
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

// ================== nRF24L01(+) PINOUT ==================
#define NRF_CS   7
#define NRF_IRQ  3
#define NRF_CE   10
#define NRF_SCK  SCK
#define NRF_MISO MISO
#define NRF_MOSI MOSI

nRF24 radio = new Module(NRF_CS, NRF_IRQ, NRF_CE);

#define LED_GPIO 8

// ------------------ RX IRQ FLAG ------------------
volatile bool receivedFlag = false;

// ------------------ USER DEFAULTS ------------------
static constexpr bool debug_default_state = false;

// ------------------ RUNTIME STATE ------------------
bool rxEnabled     = true;
bool debugEnabled  = debug_default_state;

// ------------------ CONFIG ------------------
struct RadioConfig {
  // 5-byte address shared by TX + RX pipe0 (like your proven-working sketch)
  uint8_t addr[5] = { 0x01, 0x23, 0x45, 0x67, 0x89 };
};

RadioConfig cfg;
const RadioConfig cfgDefault;

// ------------------ RX CALLBACK ------------------
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

// ------------------ SERIAL HELPERS ------------------
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("ERROR")); }

static void beginRadioSpiBus() {
  SPI.end();
  delay(5);
  SPI.begin(NRF_SCK, NRF_MISO, NRF_MOSI, NRF_CS);
  SPI.setFrequency(1000000);
  delay(5);
}

static void releaseOledI2CBus() {
  delay(10);
  Wire.end();

  digitalWrite(OLED_SDA, LOW);
  digitalWrite(OLED_SCL, LOW);
  pinMode(OLED_SDA, INPUT);
  pinMode(OLED_SCL, INPUT);
  delay(5);
}

static void oled_setup() {
  u8g2.setBusClock(400000);
  u8g2.begin();
  u8g2.setPowerSave(0);
  u8g2.setContrast(255);

  u8g2.clearBuffer();

  // Safe sizes for 2 lines on 128x64 without clipping
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
  drawCentered("NRF24", 63, u8g2_font_logisoso18_tr);

  u8g2.sendBuffer();
  releaseOledI2CBus();
}

// ------------------ SERIAL LINE READER (CR/LF) ------------------
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

// ------------------ HEX PARSERS ------------------
static int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  return -1;
}

// Parses exactly 5 bytes from hex: "0123456789" (optional 0x prefix, optional spaces)
static bool parseHex5Bytes(String s, uint8_t out[5]) {
  s.trim();
  s.replace(" ", "");
  if (s.startsWith("0x") || s.startsWith("0X")) s = s.substring(2);
  if (s.length() != 10) return false;

  for (int i = 0; i < 5; i++) {
    int hi = hexNibble(s[2 * i]);
    int lo = hexNibble(s[2 * i + 1]);
    if (hi < 0 || lo < 0) return false;
    out[i] = (uint8_t)((hi << 4) | lo);
  }
  return true;
}

// ------------------ PRINT HELP/CFG ------------------
static void printAddrLine(const __FlashStringHelper* label, const uint8_t a[5]) {
  Serial.print(label);
  for (int i = 0; i < 5; i++) {
    if (a[i] < 16) Serial.print('0');
    Serial.print(a[i], HEX);
  }
  Serial.println();
}

static void printConfig() {
  Serial.println(F("CFG:"));
  printAddrLine(F("  ADDR=0x"), cfg.addr);
  Serial.print(F("  RX="));
  Serial.println(rxEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  DEBUG="));
  Serial.println(debugEnabled ? F("ON") : F("OFF"));
}

static void printHelp() {
  Serial.println(F("AT bridge for nRF24L01(+) (RadioLib)"));
  Serial.println(F("Core:"));
  Serial.println(F("  AT                  -> OK"));
  Serial.println(F("  AT? / AT+HELP       -> help"));
  Serial.println(F("  AT+CFG?             -> print config"));
  Serial.println(F("  AT+APPLY            -> apply pipes + (re)start RX"));
  Serial.println(F("  AT+RESET            -> radio.begin() + apply"));
  Serial.println(F("Address:"));
  Serial.println(F("  AT+ADDR=<10hex>     -> set TX/RX0 address (5 bytes)"));
  Serial.println(F("  AT+ADDR?            -> print address"));
  Serial.println(F("RX:"));
  Serial.println(F("  AT+RX=ON|OFF"));
  Serial.println(F("Debug:"));
  Serial.println(F("  AT+DEBUG=ON|OFF / AT+DEBUG?"));
  Serial.println(F("Data:"));
  Serial.println(F("  any non-AT line -> transmit as text payload"));
  Serial.println(F("Example: AT+ADDR=0123456789"));
}

// ------------------ RADIO APPLY/RESET ------------------
static bool applyConfigToRadio() {
  int st;

  // Pipes (same approach as your known-good code)
  st = radio.setTransmitPipe(cfg.addr);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setReceivePipe(0, cfg.addr);
  if (st != RADIOLIB_ERR_NONE) return false;

  // RX callback
  radio.setPacketReceivedAction(onRxDone);

  // RX state
  if (rxEnabled) {
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) return false;
  } else {
    radio.standby();
  }

  return true;
}

static bool resetRadioBeginAndApply() {
  // Maximum-robust reset for nRF24:
  // CE + CS gating + SPI reset + re-init + config apply.
  // nRF24 has no RESET pin; this is the closest to a power-cycle.

  // -------------------------------------------------
  // 1) Force CE LOW and CS HIGH (disable radio + deselect SPI)
  // -------------------------------------------------
  pinMode(NRF_CE, OUTPUT);
  pinMode(NRF_CS, OUTPUT);

  digitalWrite(NRF_CE, LOW);   // stop RX/TX FSM
  digitalWrite(NRF_CS, HIGH);  // SPI idle
  delay(5);

  // -------------------------------------------------
  // 2) Stop any ongoing RadioLib operation
  // -------------------------------------------------
  radio.standby();
  delay(5);

  // -------------------------------------------------
  // 3) Reset SPI bus completely
  // -------------------------------------------------
  SPI.end();
  delay(5);

  beginRadioSpiBus();

  // -------------------------------------------------
  // 4) Handle possible stuck IRQ (safe even if unused)
  // -------------------------------------------------
  pinMode(NRF_IRQ, INPUT_PULLUP);
  unsigned long t0 = millis();
  while (digitalRead(NRF_IRQ) == LOW && (millis() - t0) < 20) {
    delay(1);
  }

  // -------------------------------------------------
  // 5) Toggle CS to guarantee clean SPI frame boundary
  // -------------------------------------------------
  digitalWrite(NRF_CS, LOW);
  delay(2);
  digitalWrite(NRF_CS, HIGH);
  delay(2);

  // -------------------------------------------------
  // 6) Re-initialize radio (parameterless begin = proven stable)
  // -------------------------------------------------
  int st = radio.begin();
  if (st != RADIOLIB_ERR_NONE) {
    // Some clones need a second attempt
    delay(20);
    st = radio.begin();
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  // -------------------------------------------------
  // 7) Toggle CE to generate a clean enable edge
  // -------------------------------------------------
  digitalWrite(NRF_CE, LOW);
  delay(2);
  digitalWrite(NRF_CE, HIGH);
  delay(2);
  digitalWrite(NRF_CE, LOW);
  delay(2);

  // -------------------------------------------------
  // 8) Apply config (pipes, callback, RX)
  // -------------------------------------------------
  bool ok = applyConfigToRadio();
  if (!ok) return false;

  // -------------------------------------------------
  // 9) Leave pins in idle state (RadioLib will drive them)
  // -------------------------------------------------
  digitalWrite(NRF_CE, LOW);
  digitalWrite(NRF_CS, HIGH);

  return true;
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

  // Apply: (re)apply pipes + (re)start RX
  if (u == "AT+APPLY") {
    bool ok = applyConfigToRadio();
    ok ? serialOK() : serialERR();
    return true;
  }

  // Reset: radio.begin() + apply
  if (u == "AT+RESET") {
    bool ok = resetRadioBeginAndApply();
    ok ? serialOK() : serialERR();
    return true;
  }

  // Address query
  if (u == "AT+ADDR?") {
    printAddrLine(F("ADDR=0x"), cfg.addr);
    serialOK();
    return true;
  }

  // Address set
  if (u.startsWith("AT+ADDR=")) {
    uint8_t tmp[5];
    if (!parseHex5Bytes(line.substring(8), tmp)) { serialERR(); return true; }
    memcpy(cfg.addr, tmp, 5);
    bool ok = applyConfigToRadio();
    ok ? serialOK() : serialERR();
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
    int st = radio.startReceive();
    (st == RADIOLIB_ERR_NONE) ? serialOK() : serialERR();
    return true;
  }

  // DEBUG
  if (u == "AT+DEBUG?") {
    Serial.print(F("DEBUG="));
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
    serialOK();
    return true;
  }
  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }

  // Unknown AT command
  if (u.startsWith("AT")) return false;
  return false;
}

// ================== SETUP / LOOP ==================
void setup() {

  Serial.begin(9600);
  delay(1000);

  pinMode(LED_GPIO, OUTPUT);
  digitalWrite(LED_GPIO, LOW);

  Serial.print(F("[nRF24] Initializing ... "));
  bool ok = resetRadioBeginAndApply();
  if (ok) {
    Serial.println(F("success!"));
  } else {
    Serial.println(F("failed!"));
    while (true) delay(10);
  }

  oled_setup();
  beginRadioSpiBus();

  printHelp();
}

void loop() {
  // LED 1 Hz blink (toggle every 1000 ms)
  static unsigned long lastLed = 0;
  static bool ledState = false;
  unsigned long now = millis();
  if (now - lastLed >= 1000) {
    lastLed = now;
    ledState = !ledState;
    digitalWrite(LED_GPIO, ledState ? HIGH : LOW);
  }

  // Serial line -> AT or TX
  String line = readSerialLineNonBlocking();
  if (line.length() > 0) {
    if (line.startsWith("AT") || line.startsWith("at")) {
      if (!handleAT(line)) {
        serialERR();
      }
    } else {
      // Transmit non-AT text as-is.
      // Temporarily remove RX action during TX to avoid false triggers.
      radio.clearPacketReceivedAction();

      if (debugEnabled) {
        Serial.print(F("[nRF24] TX -> "));
        Serial.println(line);
      }

      int st = radio.transmit(line);

      if (debugEnabled) {
        if (st == RADIOLIB_ERR_NONE) {
          Serial.println(F("[nRF24] TX OK"));
        } else {
          Serial.print(F("[nRF24] TX failed, code "));
          Serial.println(st);
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
  if (receivedFlag) {
    receivedFlag = false;

    String str;
    int st = radio.readData(str);

    if (st == RADIOLIB_ERR_NONE) {
      if (debugEnabled) {
        Serial.println(F("[nRF24] Packet received!"));
        Serial.print(F("[nRF24] Data:\t\t"));
        Serial.println(str);
      } else {
        // DEBUG OFF: print ONLY the payload
        Serial.println(str);
      }
    } else {
      if (debugEnabled) {
        Serial.print(F("[nRF24] RX failed, code "));
        Serial.println(st);
      }
    }

    if (rxEnabled) {
      radio.startReceive();
    }
  }
}
