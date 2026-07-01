#include <Arduino.h>
#include <U8g2lib.h>

// E79-400DM2005S uses a TI CC1352P wireless MCU. This file is an ESP32-side
// helper shell for the CC1352P UART modem firmware; it is not a direct radio driver.

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
  drawCentered("EBYTE", 42, u8g2_font_logisoso18_tr);
  drawCentered("E79", 63, u8g2_font_logisoso18_tr);
  u8g2.sendBuffer();
}

// ------------------ PINOUT ------------------
// These are ESP32-side UART pins connected to the CC1352P modem firmware.
// The CC1352P firmware must map its own UART pins to match the board wiring.
static const int UART1_RX_PIN = 20;  // ESP32 RX  <- E79/CC1352P modem TX
static const int UART1_TX_PIN = 21;  // ESP32 TX  -> E79/CC1352P modem RX

static const int LED_PIN = 8;

// ------------------ UART ------------------
static const uint32_t USB_BAUD = 115200;
static const uint32_t DEFAULT_E79_UART_BAUD = 115200;
static uint32_t e79UartBaud = DEFAULT_E79_UART_BAUD;

// ------------------ RUNTIME STATE ------------------
static bool bridgeEnabled = false;
static bool debugEnabled = false;
static bool moduleSleeping = false;

static uint32_t ledTickMs = 0;
static bool ledState = false;
static String usbLine;

// ------------------ SERIAL HELPERS ------------------
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("#ERROR")); }
static void serialError(const __FlashStringHelper* msg) {
  Serial.print(F("#ERROR: "));
  Serial.println(msg);
}

static void serialWarn(const __FlashStringHelper* msg) {
  Serial.print(F("#WARN: "));
  Serial.println(msg);
}

static void serial1Begin(uint32_t baud) {
  Serial1.end();
  delay(10);
  Serial1.begin(baud, SERIAL_8N1, UART1_RX_PIN, UART1_TX_PIN);
  Serial1.setTimeout(250);
}

static bool isSupportedBaud(uint32_t baud) {
  switch (baud) {
    case 1200:
    case 2400:
    case 4800:
    case 9600:
    case 19200:
    case 38400:
    case 57600:
    case 115200:
    case 230400:
    case 460800:
    case 921600:
      return true;
    default:
      return false;
  }
}

static void relayModemResponse(uint32_t timeoutMs) {
  bool gotAny = false;
  uint32_t t0 = millis();

  while (millis() - t0 < timeoutMs) {
    while (Serial1.available()) {
      Serial.write((uint8_t)Serial1.read());
      gotAny = true;
      t0 = millis();
    }
    delay(1);
  }

  if (!gotAny) serialWarn(F("NO_E79_MODEM_RESPONSE"));
}

static bool forwardModemCommand(const String& command, bool readResponse = true) {
  if (command.length() == 0) {
    serialError(F("EMPTY_MODEM_COMMAND"));
    return false;
  }

  if (moduleSleeping && command != F("AT+WAKE")) {
    serialError(F("E79_MODEM_SLEEPING (send AT+WAKE)"));
    return false;
  }

  Serial1.print(command);
  Serial1.print("\r\n");

  if (debugEnabled) {
    Serial.print(F("#FORWARDED: "));
    Serial.println(command);
  }

  if (readResponse) relayModemResponse(350);
  return true;
}

static void printHelp() {
  Serial.println(F("Ebyte E79 CC1352P ESP32-side helper"));
  Serial.println(F("This sketch expects the CC1352P UART AT modem firmware."));
  Serial.println(F(""));
  Serial.println(F("Local commands:"));
  Serial.println(F("  AT"));
  Serial.println(F("  AT? / AT+HELP"));
  Serial.println(F("  AT+CFG?"));
  Serial.println(F("  AT+DEFAULT"));
  Serial.println(F("  AT+DEBUG=ON|OFF / AT+DEBUG?"));
  Serial.println(F("  AT+BRIDGE=ON|OFF / AT+BRIDGE?"));
  Serial.println(F("  AT+BAUD? / AT+BAUD=<1200..921600>"));
  Serial.println(F("  AT+RAW=<command>"));
  Serial.println(F("  AT+PING"));
  Serial.println(F(""));
  Serial.println(F("Forwarded CC1352P modem commands:"));
  Serial.println(F("  AT+CFG? AT+DEFAULT AT+FREQ? AT+FREQ=<Hz> AT+CHAN? AT+CHAN=<n>"));
  Serial.println(F("  AT+PWR? AT+PWR=<dBm> AT+RX=ON AT+RX=OFF AT+SEND=<data>"));
  Serial.println(F("  AT+SLEEP AT+WAKE"));
}

static void printConfig() {
  Serial.println(F("MODULE=Ebyte E79-400DM2005S"));
  Serial.println(F("CHIPSET=TI CC1352P"));
  Serial.println(F("ROLE=ESP32_UART_MODEM_HELPER"));
  Serial.println(F("DIRECT_RADIO_DRIVER=NO"));
  Serial.println(F("CC1352P_FIRMWARE=REQUIRED"));
  Serial.print(F("UART_RX_PIN=")); Serial.println(UART1_RX_PIN);
  Serial.print(F("UART_TX_PIN=")); Serial.println(UART1_TX_PIN);
  Serial.print(F("UART_BAUD=")); Serial.println(e79UartBaud);
  Serial.print(F("BRIDGE=")); Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
  Serial.print(F("DEBUG=")); Serial.println(debugEnabled ? F("ON") : F("OFF"));
  Serial.print(F("SLEEP=")); Serial.println(moduleSleeping ? F("YES") : F("NO"));
  Serial.println(F("PROGRAMMING=flash CC1352P separately via JTAG/cJTAG"));
}

static void restoreDefaults() {
  bridgeEnabled = false;
  debugEnabled = false;
  moduleSleeping = false;
  e79UartBaud = DEFAULT_E79_UART_BAUD;
  serial1Begin(e79UartBaud);
}

static bool parseOnOff(const String& value, bool& out) {
  if (value == F("ON") || value == F("1")) {
    out = true;
    return true;
  }
  if (value == F("OFF") || value == F("0")) {
    out = false;
    return true;
  }
  return false;
}

static void handleAT(String input) {
  String rawLine = input;
  rawLine.trim();

  String line = rawLine;
  line.toUpperCase();

  if (line.length() == 0) return;

  if (line == F("AT")) {
    serialOK();
  } else if (line == F("AT?") || line == F("AT+HELP")) {
    printHelp();
  } else if (line == F("AT+CFG?")) {
    printConfig();
  } else if (line == F("AT+DEFAULT")) {
    restoreDefaults();
    serialOK();
  } else if (line == F("AT+DEBUG?")) {
    Serial.println(debugEnabled ? F("ON") : F("OFF"));
  } else if (line.startsWith(F("AT+DEBUG="))) {
    bool value;
    if (!parseOnOff(line.substring(9), value)) {
      serialError(F("BAD_DEBUG_VALUE"));
      return;
    }
    debugEnabled = value;
    serialOK();
  } else if (line == F("AT+BRIDGE?")) {
    Serial.println(bridgeEnabled ? F("ON") : F("OFF"));
  } else if (line.startsWith(F("AT+BRIDGE="))) {
    bool value;
    if (!parseOnOff(line.substring(10), value)) {
      serialError(F("BAD_BRIDGE_VALUE"));
      return;
    }
    bridgeEnabled = value;
    serialOK();
  } else if (line == F("AT+BAUD?")) {
    Serial.println(e79UartBaud);
  } else if (line.startsWith(F("AT+BAUD="))) {
    uint32_t baud = (uint32_t)line.substring(8).toInt();
    if (!isSupportedBaud(baud)) {
      serialError(F("BAD_BAUD_RANGE"));
      return;
    }
    e79UartBaud = baud;
    serial1Begin(e79UartBaud);
    serialOK();
  } else if (line.startsWith(F("AT+RAW="))) {
    String raw = rawLine.substring(7);
    raw.trim();
    forwardModemCommand(raw);
  } else if (line == F("AT+PING")) {
    forwardModemCommand(String(F("AT")));
  } else if (line == F("AT+SLEEP")) {
    if (forwardModemCommand(line)) {
      moduleSleeping = true;
    }
  } else if (line == F("AT+WAKE")) {
    moduleSleeping = false;
    forwardModemCommand(line);
  } else if (line.startsWith(F("AT+"))) {
    forwardModemCommand(rawLine);
  } else if (bridgeEnabled) {
    if (moduleSleeping) {
      serialError(F("E79_MODEM_SLEEPING (send AT+WAKE)"));
      return;
    }
    Serial1.println(rawLine);
  } else {
    serialError(F("UNKNOWN_COMMAND"));
  }
}

static void ledService() {
  uint32_t now = millis();
  if (now - ledTickMs >= 500) {
    ledTickMs = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState ? HIGH : LOW);
  }
}

static void usbCommandService() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (usbLine.length() > 0) {
        handleAT(usbLine);
        usbLine = "";
      }
    } else {
      if (usbLine.length() < 160) {
        usbLine += c;
      } else {
        usbLine = "";
        serialError(F("LINE_TOO_LONG"));
      }
    }
  }
}

static void modemRxService() {
  while (Serial1.available()) {
    Serial.write((uint8_t)Serial1.read());
  }
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(USB_BAUD);
  delay(300);

  oled_setup();
  restoreDefaults();

  Serial.println(F("ESP32-C3 Radio - Ebyte E79 CC1352P helper"));
  Serial.println(F("#INFO: CC1352P firmware must be built and flashed separately."));
  printHelp();
}

void loop() {
  ledService();
  usbCommandService();
  modemRxService();
}
