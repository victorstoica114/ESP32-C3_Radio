#include <Arduino.h>
#include <RadioLib.h>
#include <EEPROM.h>
#include <U8g2lib.h>

/*
  CC1101 AT Bridge - Comunicatie bidirectionala cu comenzi AT
  
  Serial (115200 8N1) <---> CC1101 Radio
  
  Conexiuni CC1101 -> ESP32-C3:
  - VCC  -> 3.3V
  - GND  -> GND
  - CSN  -> GPIO 7
  - SCK  -> GPIO 4
  - MOSI -> GPIO 6
  - MISO -> GPIO 5
  - GDO0 -> GPIO 10
  - GDO2 -> GPIO 3
*/

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
// HW PINS (ESP32-C3)
// =============================================================================
static const int CC1101_CS_PIN   = 7;
static const int CC1101_GDO0_PIN = 10;
static const int CC1101_GDO2_PIN = 3;
static const int LED_PIN         = 8;

// =============================================================================
// UART
// =============================================================================
static const uint32_t USB_BAUD = 115200;

// =============================================================================
// DEFAULT RADIO CONFIG
// =============================================================================
static const float    DEF_FREQUENCY    = 433.0;    // MHz
static const float    DEF_BITRATE      = 4.8;      // kbps
static const float    DEF_FREQ_DEV     = 5.2;      // kHz
static const float    DEF_RX_BW        = 135.0;    // kHz
static const int8_t   DEF_TX_POWER     = 10;       // dBm
static const uint8_t  DEF_PREAMBLE     = 16;       // bytes
static const uint8_t  DEF_SYNC_WORD_H  = 0xD3;
static const uint8_t  DEF_SYNC_WORD_L  = 0x91;

// Valid bandwidth values for CC1101
static const float VALID_BANDWIDTHS[] = {
  58.03, 67.71, 81.25, 101.56, 116.07, 135.09, 162.50, 203.12,
  232.14, 270.83, 325.00, 406.25, 464.29, 541.67, 650.00, 812.50
};
static const int NUM_BANDWIDTHS = 16;

// Valid bitrates for CC1101
static const float VALID_BITRATES[] = {
  0.6, 1.2, 2.4, 4.8, 9.6, 19.2, 38.4, 76.8, 153.6, 250.0, 500.0
};
static const int NUM_BITRATES = 11;

// TX Power levels (dBm)
static const int8_t VALID_POWERS[] = { -30, -20, -15, -10, -6, 0, 5, 7, 10, 12 };
static const int NUM_POWERS = 10;

// =============================================================================
// EEPROM PERSISTENCE
// =============================================================================
static const uint32_t EEPROM_MAGIC   = 0x43433031UL; // "CC01"
static const uint16_t EEPROM_VERSION = 0x0002;
static const size_t   EEPROM_SIZE    = 512;

struct RadioConfig {
  float    frequency;
  float    bitRate;
  float    freqDev;
  float    rxBandwidth;
  int8_t   txPower;
  uint8_t  preambleLen;
  uint8_t  syncWordH;
  uint8_t  syncWordL;
  bool     crcEnabled;
};

struct EepromBlob {
  uint32_t    magic;
  uint16_t    version;
  uint16_t    length;
  RadioConfig cfg;
  uint32_t    crc;
};

// =============================================================================
// GLOBALS
// =============================================================================
CC1101 radio = new Module(CC1101_CS_PIN, CC1101_GDO0_PIN, RADIOLIB_NC, CC1101_GDO2_PIN);

static RadioConfig cfgDefault;
static RadioConfig cfgCurrent;

static bool bridgeEnabled = true;
static bool debugEnabled  = false;

// Serial buffer
#define SERIAL_BUFFER_SIZE 64
static char serialBuffer[SERIAL_BUFFER_SIZE];
static int  serialBufferIndex = 0;
static unsigned long lastSerialTime = 0;
#define SERIAL_TIMEOUT 50

// Radio RX flag
static volatile bool radioReceived = false;
static bool inReceiveMode = true;

// LED 1Hz
static uint32_t ledTickMs = 0;
static bool ledState = false;

static void oled_setup() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setBusClock(400000);

  u8g2.clearBuffer();

  // Safe sizes for 2 lines on 128x64 without clipping
  drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);   // baseline ~26
  drawCentered("CC1101", 63, u8g2_font_logisoso18_tr);  // baseline ~56

  u8g2.sendBuffer();
}

// =============================================================================
// CRC32
// =============================================================================
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

// =============================================================================
// EEPROM Functions
// =============================================================================
static bool eepromLoad(RadioConfig& out) {
  EepromBlob b;
  EEPROM.get(0, b);
  if (b.magic != EEPROM_MAGIC) return false;
  if (b.version != EEPROM_VERSION) return false;
  if (b.length != (uint16_t)sizeof(RadioConfig)) return false;
  uint32_t c = crc32_calc((const uint8_t*)&b.cfg, sizeof(RadioConfig));
  if (c != b.crc) return false;
  out = b.cfg;
  return true;
}

static bool eepromSave(const RadioConfig& in) {
  EepromBlob b;
  b.magic   = EEPROM_MAGIC;
  b.version = EEPROM_VERSION;
  b.length  = (uint16_t)sizeof(RadioConfig);
  b.cfg     = in;
  b.crc     = crc32_calc((const uint8_t*)&b.cfg, sizeof(RadioConfig));
  EEPROM.put(0, b);
  return EEPROM.commit();
}

// =============================================================================
// LED Heartbeat
// =============================================================================
static void led1HzService() {
  uint32_t now = millis();
  if (now - ledTickMs >= 500) {
    ledTickMs = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState ? HIGH : LOW);
  }
}

// =============================================================================
// Radio Interrupt
// =============================================================================
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void radioInterrupt(void) {
  radioReceived = true;
}

// =============================================================================
// Radio Functions
// =============================================================================
static void startReceive() {
  // Clear orice flag anterior
  radioReceived = false;
  
  // Flush RX FIFO inainte de a incepe receptia
  digitalWrite(CC1101_CS_PIN, LOW);
  SPI.transfer(0x3A);  // SFRX - Flush RX FIFO
  digitalWrite(CC1101_CS_PIN, HIGH);
  delayMicroseconds(100);
  
  int state = radio.startReceive();
  
  if (debugEnabled && state != RADIOLIB_ERR_NONE) {
    Serial.print(F("[DEBUG] startReceive() failed: "));
    Serial.println(state);
  }
  
  inReceiveMode = true;
}

static bool applyConfig(const RadioConfig& cfg) {
  // Opreste receptia si pune in standby
  radio.standby();
  delay(10);
  
  int state = radio.begin(
    cfg.frequency,
    cfg.bitRate,
    cfg.freqDev,
    cfg.rxBandwidth,
    cfg.txPower,
    cfg.preambleLen
  );
  
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] begin() failed: "));
      Serial.println(state);
    }
    return false;
  }
  
  // Set sync word
  uint8_t syncWord[] = { cfg.syncWordH, cfg.syncWordL };
  state = radio.setSyncWord(syncWord, 2, 0, false);
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] setSyncWord() failed: "));
      Serial.println(state);
    }
    return false;
  }
  
  // Set CRC
  state = radio.setCrcFiltering(cfg.crcEnabled);
  if (state != RADIOLIB_ERR_NONE) {
    if (debugEnabled) {
      Serial.print(F("[DEBUG] setCrcFiltering() failed: "));
      Serial.println(state);
    }
    return false;
  }
  
  // IMPORTANT: Clear RX FIFO
  digitalWrite(CC1101_CS_PIN, LOW);
  SPI.transfer(0x3A);  // SFRX - Flush RX FIFO
  digitalWrite(CC1101_CS_PIN, HIGH);
  delayMicroseconds(100);
  
  // IMPORTANT: Reset flag-ul inainte de a seta interrupt handler
  radioReceived = false;
  
  // IMPORTANT: Re-attach interrupt handler DUPA begin()
  radio.setPacketReceivedAction(radioInterrupt);
  
  return true;
}

static bool transmitData(const char* data, int length) {
  inReceiveMode = false;
  
  // Transmite o singura data, ignora eroarea de timeout
  int state = radio.transmit((uint8_t*)data, length);
  
  if (debugEnabled) {
    Serial.print(F("[TX] "));
    Serial.print(length);
    Serial.print(F(" bytes, state: "));
    Serial.println(state);
  }
  
  // Intoarce-te la receptie indiferent de rezultat
  startReceive();
  
  // Consideram success chiar daca avem TX_TIMEOUT (-5)
  // deoarece transmisia se face efectiv
  return (state == RADIOLIB_ERR_NONE || state == -5);
}

// =============================================================================
// Default Config
// =============================================================================
static RadioConfig makeDefaultConfig() {
  RadioConfig c;
  c.frequency   = DEF_FREQUENCY;
  c.bitRate     = DEF_BITRATE;
  c.freqDev     = DEF_FREQ_DEV;
  c.rxBandwidth = DEF_RX_BW;
  c.txPower     = DEF_TX_POWER;
  c.preambleLen = DEF_PREAMBLE;
  c.syncWordH   = DEF_SYNC_WORD_H;
  c.syncWordL   = DEF_SYNC_WORD_L;
  c.crcEnabled  = true;
  return c;
}

// =============================================================================
// Helpers
// =============================================================================
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("ERROR")); }

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

static bool parseFloat(const String& s, float& out) {
  char* endp = nullptr;
  float v = strtof(s.c_str(), &endp);
  if (!(endp && (*endp == '\0' || *endp == ' '))) return false;
  out = v;
  return true;
}

static bool parseInt8(const String& s, int8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < -128 || v > 127) return false;
  out = (int8_t)v;
  return true;
}

static bool parseUInt8(const String& s, uint8_t& out) {
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseHex8(const String& s, uint8_t& out) {
  String t = s;
  t.trim();
  if (t.startsWith("0x") || t.startsWith("0X")) {
    t = t.substring(2);
  }
  char* endp = nullptr;
  long v = strtol(t.c_str(), &endp, 16);
  if (!(endp && *endp == '\0')) return false;
  if (v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

static bool parseOnOff(const String& s, bool& out) {
  String t = s; t.trim(); t.toUpperCase();
  if (t == "ON" || t == "1" || t == "TRUE")  { out = true;  return true; }
  if (t == "OFF"|| t == "0" || t == "FALSE") { out = false; return true; }
  return false;
}

static int findNearestBandwidth(float bw) {
  int best = 0;
  float bestDiff = abs(bw - VALID_BANDWIDTHS[0]);
  for (int i = 1; i < NUM_BANDWIDTHS; i++) {
    float diff = abs(bw - VALID_BANDWIDTHS[i]);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  }
  return best;
}

// =============================================================================
// Print Config
// =============================================================================
static void printConfigPretty(const RadioConfig& c) {
  Serial.println(F("====== CC1101 CONFIGURATION ======"));
  Serial.print(F("Frequency:    ")); Serial.print(c.frequency, 2); Serial.println(F(" MHz"));
  Serial.print(F("Bit Rate:     ")); Serial.print(c.bitRate, 1); Serial.println(F(" kbps"));
  Serial.print(F("Freq Dev:     ")); Serial.print(c.freqDev, 1); Serial.println(F(" kHz"));
  Serial.print(F("RX Bandwidth: ")); Serial.print(c.rxBandwidth, 2); Serial.println(F(" kHz"));
  Serial.print(F("TX Power:     ")); Serial.print(c.txPower); Serial.println(F(" dBm"));
  Serial.print(F("Preamble:     ")); Serial.print(c.preambleLen); Serial.println(F(" bytes"));
  Serial.print(F("Sync Word:    0x")); 
  if (c.syncWordH < 0x10) Serial.print("0");
  Serial.print(c.syncWordH, HEX);
  if (c.syncWordL < 0x10) Serial.print("0");
  Serial.println(c.syncWordL, HEX);
  Serial.print(F("CRC:          ")); Serial.println(c.crcEnabled ? F("Enabled") : F("Disabled"));
  Serial.println(F("=================================="));
}

// =============================================================================
// HELP
// =============================================================================
static void printHelp() {
  Serial.println(F(""));
  Serial.println(F("AT Shell for CC1101 Radio Module"));
  Serial.println(F(""));
  Serial.println(F("Core Commands:"));
  Serial.println(F("  AT               -> OK (test)"));
  Serial.println(F("  AT+HELP          -> This help"));
  Serial.println(F("  AT+CFG?          -> Show current config"));
  Serial.println(F("  AT+APPLY         -> Apply config to radio + save EEPROM"));
  Serial.println(F("  AT+RESET         -> Reset radio module"));
  Serial.println(F("  AT+DEFAULT       -> Restore defaults + save EEPROM"));
  Serial.println(F("  AT+BRIDGE=ON/OFF -> Enable/disable bridge mode"));
  Serial.println(F("  AT+DEBUG=ON/OFF  -> Enable/disable debug output"));
  Serial.println(F(""));
  Serial.println(F("Radio Parameters:"));
  Serial.println(F("  AT+FREQ=<MHz>    -> Set frequency (300-928 MHz)"));
  Serial.println(F("  AT+BR=<kbps>     -> Set bit rate (0.6-500 kbps)"));
  Serial.println(F("  AT+DEV=<kHz>     -> Set frequency deviation"));
  Serial.println(F("  AT+BW=<kHz>      -> Set RX bandwidth"));
  Serial.println(F("  AT+PWR=<dBm>     -> Set TX power (-30 to 12 dBm)"));
  Serial.println(F("  AT+PRE=<bytes>   -> Set preamble length (2-16)"));
  Serial.println(F("  AT+SYNC=<XXXX>   -> Set sync word (hex, e.g. D391)"));
  Serial.println(F("  AT+CRC=ON/OFF    -> Enable/disable CRC"));
  Serial.println(F(""));
  Serial.println(F("Indexed Setters:"));
  Serial.println(F("  AT+BW1..16       -> Bandwidth presets:"));
  Serial.println(F("                      1=58, 2=68, 3=81, 4=102, 5=116, 6=135,"));
  Serial.println(F("                      7=163, 8=203, 9=232, 10=271, 11=325,"));
  Serial.println(F("                      12=406, 13=464, 14=542, 15=650, 16=813 kHz"));
  Serial.println(F("  AT+BR1..11       -> Bitrate presets:"));
  Serial.println(F("                      1=0.6, 2=1.2, 3=2.4, 4=4.8, 5=9.6,"));
  Serial.println(F("                      6=19.2, 7=38.4, 8=76.8, 9=153.6,"));
  Serial.println(F("                      10=250, 11=500 kbps"));
  Serial.println(F("  AT+PWR1..10      -> Power presets:"));
  Serial.println(F("                      1=-30, 2=-20, 3=-15, 4=-10, 5=-6,"));
  Serial.println(F("                      6=0, 7=5, 8=7, 9=10, 10=12 dBm"));
  Serial.println(F(""));
  Serial.println(F("Set All (one command):"));
  Serial.println(F("  AT+SETRADIO=FREQ,BR,DEV,BW,PWR,PRE,SYNC,CRC"));
  Serial.println(F("    Example: AT+SETRADIO=433.0,4.8,5.2,135,10,16,D391,1"));
  Serial.println(F(""));
  Serial.println(F("Info:"));
  Serial.println(F("  AT+RSSI?         -> Show last RSSI"));
  Serial.println(F("  AT+LQI?          -> Show last LQI"));
  Serial.println(F(""));
}

// =============================================================================
// AT Command Handler
// =============================================================================
static bool handleAT(const String& lineRaw) {
  String line = lineRaw;
  line.trim();
  String u = line; u.toUpperCase();

  // Basic commands
  if (u == "AT") { serialOK(); return true; }
  if (u == "AT+HELP" || u == "AT?") { printHelp(); serialOK(); return true; }

  if (u == "AT+DEBUG=ON")  { debugEnabled = true;  serialOK(); return true; }
  if (u == "AT+DEBUG=OFF") { debugEnabled = false; serialOK(); return true; }

  if (u == "AT+BRIDGE=ON")  { bridgeEnabled = true;  serialOK(); return true; }
  if (u == "AT+BRIDGE=OFF") { bridgeEnabled = false; serialOK(); return true; }

  if (u == "AT+CFG?") {
    printConfigPretty(cfgCurrent);
    serialOK();
    return true;
  }

  if (u == "AT+APPLY") {
    bool ok = applyConfig(cfgCurrent);
    if (ok) {
      eepromSave(cfgCurrent);
      startReceive();
    }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+DEFAULT") {
    cfgCurrent = cfgDefault;
    bool ok = applyConfig(cfgCurrent);
    if (ok) {
      eepromSave(cfgCurrent);
      startReceive();
    }
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RESET") {
  Serial.print(F("[RADIO] Resetting... "));
  
  // Trimite SRES (strobe reset) direct prin SPI
  digitalWrite(CC1101_CS_PIN, LOW);
  SPI.transfer(0x30);  // SRES command
  digitalWrite(CC1101_CS_PIN, HIGH);
  delay(100);
  
  // Reinitializeaza cu configuratia curenta
  bool ok = applyConfig(cfgCurrent);
  if (ok) {
    startReceive();
    Serial.println(F("OK"));
  } else {
    Serial.println(F("FAILED"));
  }
  ok ? serialOK() : serialERR();
  return true;
  }

  if (u == "AT+RSSI?") {
    Serial.print(F("RSSI: "));
    Serial.print(radio.getRSSI());
    Serial.println(F(" dBm"));
    serialOK();
    return true;
  }

  if (u == "AT+LQI?") {
    Serial.print(F("LQI: "));
    Serial.println(radio.getLQI());
    serialOK();
    return true;
  }

  // --- Frequency ---
  if (u.startsWith("AT+FREQ=")) {
    float v;
    if (!parseFloat(line.substring(8), v)) { serialERR(); return true; }
    if (v < 300.0 || v > 928.0) { serialERR(); return true; }
    cfgCurrent.frequency = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Bit Rate (direct value) ---
  if (u.startsWith("AT+BR=")) {
    float v;
    if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    if (v < 0.3 || v > 600.0) { serialERR(); return true; }
    cfgCurrent.bitRate = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Bit Rate (indexed) ---
  if (u.startsWith("AT+BR") && u.length() > 5 && isDigit(u[5])) {
    int idx = u.substring(5).toInt();
    if (idx < 1 || idx > NUM_BITRATES) { serialERR(); return true; }
    cfgCurrent.bitRate = VALID_BITRATES[idx - 1];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Frequency Deviation ---
  if (u.startsWith("AT+DEV=")) {
    float v;
    if (!parseFloat(line.substring(7), v)) { serialERR(); return true; }
    if (v < 1.0 || v > 380.0) { serialERR(); return true; }
    cfgCurrent.freqDev = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- RX Bandwidth (direct value) ---
  if (u.startsWith("AT+BW=")) {
    float v;
    if (!parseFloat(line.substring(6), v)) { serialERR(); return true; }
    int idx = findNearestBandwidth(v);
    cfgCurrent.rxBandwidth = VALID_BANDWIDTHS[idx];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- RX Bandwidth (indexed) ---
  if (u.startsWith("AT+BW") && u.length() > 5 && isDigit(u[5])) {
    int idx = u.substring(5).toInt();
    if (idx < 1 || idx > NUM_BANDWIDTHS) { serialERR(); return true; }
    cfgCurrent.rxBandwidth = VALID_BANDWIDTHS[idx - 1];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- TX Power (direct value) ---
  if (u.startsWith("AT+PWR=")) {
    int8_t v;
    if (!parseInt8(line.substring(7), v)) { serialERR(); return true; }
    if (v < -30 || v > 12) { serialERR(); return true; }
    cfgCurrent.txPower = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- TX Power (indexed) ---
  if (u.startsWith("AT+PWR") && u.length() > 6 && isDigit(u[6])) {
    int idx = u.substring(6).toInt();
    if (idx < 1 || idx > NUM_POWERS) { serialERR(); return true; }
    cfgCurrent.txPower = VALID_POWERS[idx - 1];
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Preamble ---
  if (u.startsWith("AT+PRE=")) {
    uint8_t v;
    if (!parseUInt8(line.substring(7), v)) { serialERR(); return true; }
    if (v < 2 || v > 24) { serialERR(); return true; }
    cfgCurrent.preambleLen = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Sync Word ---
  if (u.startsWith("AT+SYNC=")) {
    String hexStr = line.substring(8);
    hexStr.trim();
    if (hexStr.startsWith("0x") || hexStr.startsWith("0X")) {
      hexStr = hexStr.substring(2);
    }
    if (hexStr.length() != 4) { serialERR(); return true; }
    
    uint8_t h, l;
    if (!parseHex8(hexStr.substring(0, 2), h)) { serialERR(); return true; }
    if (!parseHex8(hexStr.substring(2, 4), l)) { serialERR(); return true; }
    
    cfgCurrent.syncWordH = h;
    cfgCurrent.syncWordL = l;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- CRC ---
  if (u.startsWith("AT+CRC=")) {
    bool v;
    if (!parseOnOff(line.substring(7), v)) { serialERR(); return true; }
    cfgCurrent.crcEnabled = v;
    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // --- Set All Radio Params ---
  // AT+SETRADIO=FREQ,BR,DEV,BW,PWR,PRE,SYNC,CRC
  if (u.startsWith("AT+SETRADIO=")) {
    String p = line.substring(12);
    p.trim();

    String parts[8];
    int partsCount = 0;

    while (partsCount < 8) {
      int comma = p.indexOf(',');
      if (comma < 0) {
        parts[partsCount++] = p;
        break;
      }
      parts[partsCount++] = p.substring(0, comma);
      p = p.substring(comma + 1);
    }

    if (partsCount != 8) { serialERR(); return true; }

    float freq, br, dev, bw;
    int8_t pwr;
    uint8_t pre;
    uint8_t syncH, syncL;
    bool crc;

    if (!parseFloat(parts[0], freq) || freq < 300.0 || freq > 928.0) { serialERR(); return true; }
    if (!parseFloat(parts[1], br) || br < 0.3 || br > 600.0) { serialERR(); return true; }
    if (!parseFloat(parts[2], dev) || dev < 1.0 || dev > 380.0) { serialERR(); return true; }
    if (!parseFloat(parts[3], bw)) { serialERR(); return true; }
    if (!parseInt8(parts[4], pwr) || pwr < -30 || pwr > 12) { serialERR(); return true; }
    if (!parseUInt8(parts[5], pre) || pre < 2 || pre > 24) { serialERR(); return true; }
    
    // Sync word
    String syncStr = parts[6];
    syncStr.trim();
    if (syncStr.startsWith("0x") || syncStr.startsWith("0X")) {
      syncStr = syncStr.substring(2);
    }
    if (syncStr.length() != 4) { serialERR(); return true; }
    if (!parseHex8(syncStr.substring(0, 2), syncH)) { serialERR(); return true; }
    if (!parseHex8(syncStr.substring(2, 4), syncL)) { serialERR(); return true; }
    
    // CRC
    String crcStr = parts[7]; crcStr.trim();
    if (crcStr == "1" || crcStr.equalsIgnoreCase("ON") || crcStr.equalsIgnoreCase("TRUE")) {
      crc = true;
    } else if (crcStr == "0" || crcStr.equalsIgnoreCase("OFF") || crcStr.equalsIgnoreCase("FALSE")) {
      crc = false;
    } else {
      serialERR(); return true;
    }

    cfgCurrent.frequency   = freq;
    cfgCurrent.bitRate     = br;
    cfgCurrent.freqDev     = dev;
    cfgCurrent.rxBandwidth = VALID_BANDWIDTHS[findNearestBandwidth(bw)];
    cfgCurrent.txPower     = pwr;
    cfgCurrent.preambleLen = pre;
    cfgCurrent.syncWordH   = syncH;
    cfgCurrent.syncWordL   = syncL;
    cfgCurrent.crcEnabled  = crc;

    bool ok = applyConfig(cfgCurrent);
    if (ok) { eepromSave(cfgCurrent); startReceive(); }
    ok ? serialOK() : serialERR();
    return true;
  }

  // Unknown AT command
  if (startsWithAT(line)) return false;
  return false;
}

// =============================================================================
// Setup
// =============================================================================
void setup() {
  // oled_setup();
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(USB_BAUD);
  delay(1000);

  Serial.println();
  Serial.println(F("=========================================="));
  Serial.println(F("   CC1101 AT Bridge"));
  Serial.println(F("   115200 8N1 <-> 433 MHz Radio"));
  Serial.println(F("=========================================="));
  Serial.println();

  

  // Init SPI
  SPI.begin(4, 5, 6, 7);

  // EEPROM
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin failed"));
  }

  // Load or create config
  cfgDefault = makeDefaultConfig();
  cfgCurrent = cfgDefault;

  if (eepromLoad(cfgCurrent)) {
    Serial.println(F("[EEPROM] Config loaded"));
  } else {
    Serial.println(F("[EEPROM] Using defaults"));
    eepromSave(cfgCurrent);
  }

  // Init radio
  Serial.print(F("[RADIO] Initializing... "));
  if (applyConfig(cfgCurrent)) {
    Serial.println(F("OK"));
  } else {
    Serial.println(F("FAILED"));
    Serial.println(F("[WARN] Using defaults"));
    cfgCurrent = cfgDefault;
    if (!applyConfig(cfgCurrent)) {
      Serial.println(F("[ERROR] Radio init failed!"));
      while (true) delay(1000);
    }
  }

  printConfigPretty(cfgCurrent);

  // Start receiving
  startReceive();

  oled_setup();
  
  radio.standby();
  delay(10);
  bool ok = applyConfig(cfgCurrent);
  delay(100);
  
  radio.standby();
  delay(10);
  // Reinitializeaza complet modulul
  ok = applyConfig(cfgCurrent);
  if (ok) {
    startReceive();
    Serial.println(F("[READY] Bridge ON. Type AT+HELP for commands."));
    Serial.println(F("------------------------------------------"));
  } else {
    Serial.println(F("FAILED"));
  }
}


// =============================================================================
// Loop
// =============================================================================
void loop() {
  // LED heartbeat
  led1HzService();

  // ========== RADIO RX ==========
  if (radioReceived) {
    radioReceived = false;
    
    uint8_t radioBuffer[64];
    int length = radio.getPacketLength();
    
    if (length > 0 && length <= 64) {
      int state = radio.readData(radioBuffer, length);
      
      if (state == RADIOLIB_ERR_NONE) {
        // Send to Serial
        Serial.write(radioBuffer, length);
        
        if (debugEnabled) {
          Serial.print(F("\n[RX] "));
          Serial.print(length);
          Serial.print(F(" bytes, RSSI: "));
          Serial.print(radio.getRSSI());
          Serial.print(F(" dBm, LQI: "));
          Serial.println(radio.getLQI());
        }
      }
    }
    
    startReceive();
  }

  // ========== SERIAL RX (AT commands or bridge data) ==========
  String line = readLineUSB();
  if (line.length() > 0) {
    if (startsWithAT(line)) {
      if (!handleAT(line)) {
        serialERR();
      }
    } else if (bridgeEnabled) {
      // Bridge mode: send via radio with \r\n appended
      String dataWithCRLF = line + "\r\n";
      if (transmitData(dataWithCRLF.c_str(), dataWithCRLF.length())) {
        if (debugEnabled) {
          Serial.print(F("[TX] "));
          Serial.print(dataWithCRLF.length());
          Serial.println(F(" bytes"));
        }
      } else {\
        if (debugEnabled) {
          Serial.println(F("[TX] FAILED"));
        }
      }
    }
  }
}