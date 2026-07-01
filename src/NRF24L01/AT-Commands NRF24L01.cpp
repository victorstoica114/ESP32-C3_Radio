#include <Arduino.h>
#include <Wire.h>
#include <RadioLib.h>
#include <U8g2lib.h>
#include <EEPROM.h>
#include <math.h>

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
bool radioSleeping = false;
bool rxEnabledBeforeSleep = true;
bool debugEnabled  = debug_default_state;

// ------------------ CONFIG ------------------
struct RadioConfig {
  float freqMHz = 2400.0f;
  uint16_t bitRateKbps = 1000;
  int8_t powerDbm = -12;
  uint8_t addrWidth = 5;
  uint8_t txAddr[5] = { 0x01, 0x23, 0x45, 0x67, 0x89 };
  uint8_t rxAddr[6][5] = {
    { 0x01, 0x23, 0x45, 0x67, 0x89 },
    { 0x01, 0x23, 0x45, 0x67, 0x88 },
    { 0x01, 0x23, 0x45, 0x67, 0x87 },
    { 0x01, 0x23, 0x45, 0x67, 0x86 },
    { 0x01, 0x23, 0x45, 0x67, 0x85 },
    { 0x01, 0x23, 0x45, 0x67, 0x84 }
  };
  bool pipeEnabled[6] = { true, false, false, false, false, false };
  bool crcOn = true;
  uint8_t autoAckMask = 0x3F;
  uint8_t retryDelay = 5;
  uint8_t retryCount = 15;
  bool lnaOn = true;
  bool dynamicPayload = true;
  bool ackPayload = false;
  uint8_t fixedPayloadLen = 32;
};

RadioConfig cfg;
const RadioConfig cfgDefault;

static const uint32_t EEPROM_MAGIC = 0x4E524632UL; // "NRF2"
static const uint16_t EEPROM_VERSION = 0x0002;
static const size_t EEPROM_SIZE = 512;

// ------------------ RX CALLBACK ------------------
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

static void sanitizeConfig(RadioConfig& c);

// ------------------ SERIAL HELPERS ------------------
static inline void serialOK()  { Serial.println(F("OK")); }
static inline void serialERR() { Serial.println(F("#ERROR")); }
static inline void serialError(const __FlashStringHelper* msg) {
  Serial.print(F("#ERROR: "));
  Serial.println(msg);
}

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

static uint8_t nrfReadReg(uint8_t reg) {
  digitalWrite(NRF_CS, LOW);
  SPI.transfer(0x00 | (reg & 0x1F));
  uint8_t v = SPI.transfer(0xFF);
  digitalWrite(NRF_CS, HIGH);
  return v;
}

static void nrfWriteReg(uint8_t reg, uint8_t value) {
  digitalWrite(NRF_CS, LOW);
  SPI.transfer(0x20 | (reg & 0x1F));
  SPI.transfer(value);
  digitalWrite(NRF_CS, HIGH);
}

static void nrfFlushRx() {
  digitalWrite(NRF_CS, LOW);
  SPI.transfer(0xE2);
  digitalWrite(NRF_CS, HIGH);
}

static void nrfFlushTx() {
  digitalWrite(NRF_CS, LOW);
  SPI.transfer(0xE1);
  digitalWrite(NRF_CS, HIGH);
}

static void nrfClearIrq() {
  // Clear RX_DR, TX_DS and MAX_RT by writing 1 to each bit.
  nrfWriteReg(0x07, 0x70);
}

static int startReceiveClean(bool flushRxFifo) {
  receivedFlag = false;
  nrfClearIrq();
  if (flushRxFifo) {
    nrfFlushRx();
  }

  radio.setPacketReceivedAction(onRxDone);
  int st = radio.startReceive();
  delay(5);
  return st;
}

static uint8_t nrfReadRxPayloadWidth() {
  digitalWrite(NRF_CS, LOW);
  SPI.transfer(0x60); // R_RX_PL_WID
  uint8_t len = SPI.transfer(0xFF);
  digitalWrite(NRF_CS, HIGH);
  return len;
}

static bool nrfHasRxPayload() {
  uint8_t status = nrfReadReg(0x07);
  uint8_t fifoStatus = nrfReadReg(0x17);
  return (status & 0x40) || ((fifoStatus & 0x01) == 0);
}

static int nrfReadReceivedText(String& out) {
  uint8_t len = cfg.dynamicPayload ? nrfReadRxPayloadWidth() : cfg.fixedPayloadLen;
  if (len > 32) {
    nrfFlushRx();
    nrfClearIrq();
    return RADIOLIB_ERR_PACKET_TOO_LONG;
  }

  char buf[33];
  memset(buf, 0, sizeof(buf));

  digitalWrite(NRF_CS, LOW);
  SPI.transfer(0x61); // R_RX_PAYLOAD; first returned byte is STATUS, ignore it.
  for (uint8_t i = 0; i < len; i++) {
    buf[i] = (char)SPI.transfer(0xFF);
  }
  digitalWrite(NRF_CS, HIGH);

  nrfClearIrq();
  out = String(buf);
  return RADIOLIB_ERR_NONE;
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
  for (int i = 0; i < cfg.addrWidth; i++) {
    if (a[i] < 16) Serial.print('0');
    Serial.print(a[i], HEX);
  }
  Serial.println();
}

static void printConfig() {
  Serial.println(F("CFG:"));
  Serial.print(F("  FREQ=")); Serial.print(cfg.freqMHz, 1); Serial.println(F(" MHz"));
  Serial.print(F("  CHAN=")); Serial.println((int)lroundf(cfg.freqMHz - 2400.0f));
  Serial.print(F("  RATE=")); Serial.print(cfg.bitRateKbps); Serial.println(F(" kbps"));
  Serial.print(F("  PWR=")); Serial.print(cfg.powerDbm); Serial.println(F(" dBm"));
  Serial.print(F("  ADDR_WIDTH=")); Serial.println(cfg.addrWidth);
  printAddrLine(F("  TXADDR=0x"), cfg.txAddr);
  for (uint8_t i = 0; i < 6; i++) {
    Serial.print(F("  PIPE")); Serial.print(i); Serial.print('=');
    Serial.print(cfg.pipeEnabled[i] ? F("ON ") : F("OFF "));
    printAddrLine(F("RXADDR=0x"), cfg.rxAddr[i]);
  }
  Serial.print(F("  CRC=")); Serial.println(cfg.crcOn ? F("ON") : F("OFF"));
  Serial.print(F("  AUTOACK_MASK=0x")); Serial.println(cfg.autoAckMask, HEX);
  Serial.print(F("  RETRIES_DELAY=")); Serial.println(cfg.retryDelay);
  Serial.print(F("  RETRIES_COUNT=")); Serial.println(cfg.retryCount);
  Serial.print(F("  LNA=")); Serial.println(cfg.lnaOn ? F("ON") : F("OFF"));
  Serial.print(F("  DYN_PAYLOAD=")); Serial.println(cfg.dynamicPayload ? F("ON") : F("OFF"));
  Serial.print(F("  ACK_PAYLOAD=")); Serial.println(cfg.ackPayload ? F("ON") : F("OFF"));
  Serial.print(F("  FIXED_PAYLOAD_LEN=")); Serial.println(cfg.fixedPayloadLen);
  Serial.print(F("  RX="));
  Serial.println(rxEnabled ? F("ON") : F("OFF"));
  Serial.print(F("  SLEEP="));
  Serial.println(radioSleeping ? F("YES") : F("NO"));
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
  Serial.println(F("  AT+DEFAULT          -> restore safe defaults + save EEPROM"));
  Serial.println(F("RF:"));
  Serial.println(F("  AT+FREQ=<2400..2525> / AT+FREQ?"));
  Serial.println(F("  AT+CHAN=<0..125>     / AT+CHAN?"));
  Serial.println(F("  AT+RATE=250|1000|2000 / AT+RATE?"));
  Serial.println(F("  AT+PWR=-18|-12|-6|0  / AT+PWR?"));
  Serial.println(F("Address:"));
  Serial.println(F("  AT+ADDR=<hex>       -> set TX/RX0 address"));
  Serial.println(F("  AT+ADDR?            -> print TX/RX0 address"));
  Serial.println(F("  AT+ADDRWIDTH=3|4|5  / AT+ADDRWIDTH?"));
  Serial.println(F("  AT+TXADDR=<hex>     / AT+TXADDR?"));
  Serial.println(F("  AT+RXADDR<n>=<hex>  / AT+RXADDR<n>? (n=0..5)"));
  Serial.println(F("  AT+PIPE<n>=ON|OFF   / AT+PIPES?"));
  Serial.println(F("Link layer:"));
  Serial.println(F("  AT+CRC=ON|OFF       / AT+CRC?"));
  Serial.println(F("  AT+AUTOACK=ON|OFF   / AT+AUTOACK?"));
  Serial.println(F("  AT+AUTOACK<n>=ON|OFF"));
  Serial.println(F("  AT+RETRIES=<0..15>,<0..15> / AT+RETRIES?"));
  Serial.println(F("  AT+LNA=ON|OFF       / AT+LNA?"));
  Serial.println(F("  AT+DYN=ON|OFF       / AT+DYN?"));
  Serial.println(F("  AT+ACKPAY=ON|OFF    / AT+ACKPAY?"));
  Serial.println(F("  AT+PLEN=<1..32>     / AT+PLEN?"));
  Serial.println(F("Diagnostics:"));
  Serial.println(F("  AT+STATUS?          -> STATUS/FIFO/RPD registers"));
  Serial.println(F("RX:"));
  Serial.println(F("  AT+RX=ON            -> start RX"));
  Serial.println(F("  AT+RX=OFF           -> standby"));
  Serial.println(F("  AT+SLEEP            -> sleep / power-down"));
  Serial.println(F("  AT+WAKE             -> wake + restore RX"));
  Serial.println(F("Debug:"));
  Serial.println(F("  AT+DEBUG=ON|OFF / AT+DEBUG?"));
  Serial.println(F("Data:"));
  Serial.println(F("  any non-AT line -> transmit as text payload"));
  Serial.println(F("Example: AT+ADDR=0123456789"));
}

// ------------------ RADIO APPLY/RESET ------------------
static bool applyConfigToRadio() {
  sanitizeConfig(cfg);
  radioSleeping = false;
  int st;

  st = radio.setFrequency(cfg.freqMHz);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setBitRate(cfg.bitRateKbps);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setOutputPower(cfg.powerDbm);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setAddressWidth(cfg.addrWidth);
  if (st != RADIOLIB_ERR_NONE) return false;

  st = radio.setCrcFiltering(cfg.crcOn);
  if (st != RADIOLIB_ERR_NONE) return false;

  for (uint8_t i = 0; i < 6; i++) {
    st = radio.setAutoAck(i, (cfg.autoAckMask & (1 << i)) != 0);
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  st = radio.setLNA(cfg.lnaOn);
  if (st != RADIOLIB_ERR_NONE) return false;

  // Pipes
  st = radio.setTransmitPipe(cfg.txAddr);
  if (st != RADIOLIB_ERR_NONE) return false;

  for (uint8_t i = 0; i < 6; i++) {
    if (!cfg.pipeEnabled[i]) {
      st = radio.disablePipe(i);
      if (st != RADIOLIB_ERR_NONE) return false;
      continue;
    }

    if (i <= 1) {
      st = radio.setReceivePipe(i, cfg.rxAddr[i]);
    } else {
      st = radio.setReceivePipe(i, cfg.rxAddr[i][cfg.addrWidth - 1]);
    }
    if (st != RADIOLIB_ERR_NONE) return false;
  }

  // SETUP_RETR: high nibble = delay code, low nibble = retry count.
  nrfWriteReg(0x04, (uint8_t)(((cfg.retryDelay & 0x0F) << 4) | (cfg.retryCount & 0x0F)));

  uint8_t feature = 0;
  if (cfg.dynamicPayload) feature |= 0x04; // EN_DPL
  if (cfg.ackPayload) feature |= 0x02;     // EN_ACK_PAY
  nrfWriteReg(0x1D, feature);
  nrfWriteReg(0x1C, cfg.dynamicPayload ? 0x3F : 0x00); // DYNPD
  if (!cfg.dynamicPayload) {
    uint8_t len = constrain(cfg.fixedPayloadLen, (uint8_t)1, (uint8_t)32);
    for (uint8_t r = 0x11; r <= 0x16; r++) nrfWriteReg(r, len);
  }
  nrfFlushRx();
  nrfFlushTx();

  // RX callback
  radio.setPacketReceivedAction(onRxDone);

  // RX state
  if (rxEnabled) {
    st = startReceiveClean(false);
    if (st != RADIOLIB_ERR_NONE) return false;
  } else {
    radio.standby();
  }

  return true;
}

static bool parseOnOff(String s, bool& out) {
  s.trim();
  s.toUpperCase();
  if (s == "ON" || s == "1" || s == "TRUE") { out = true; return true; }
  if (s == "OFF" || s == "0" || s == "FALSE") { out = false; return true; }
  return false;
}

static bool parseLong(String s, long& out) {
  s.trim();
  char* endp = nullptr;
  long v = strtol(s.c_str(), &endp, 10);
  if (!(endp && *endp == '\0')) return false;
  out = v;
  return true;
}

static bool parseFloatValue(String s, float& out) {
  s.trim();
  char* endp = nullptr;
  float v = strtof(s.c_str(), &endp);
  if (!(endp && *endp == '\0')) return false;
  out = v;
  return true;
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
  rec.magic = EEPROM_MAGIC;
  rec.version = EEPROM_VERSION;
  rec.length = (uint16_t)sizeof(RadioConfig);
  rec.cfg = in;
  rec.crc = crc32_calc((const uint8_t*)&rec.cfg, sizeof(RadioConfig));
  EEPROM.put(0, rec);
  return EEPROM.commit();
}

static void sanitizeConfig(RadioConfig& c) {
  if (c.freqMHz < 2400.0f || c.freqMHz > 2525.0f) c.freqMHz = cfgDefault.freqMHz;
  if (!(c.bitRateKbps == 250 || c.bitRateKbps == 1000 || c.bitRateKbps == 2000)) c.bitRateKbps = cfgDefault.bitRateKbps;
  if (!(c.powerDbm == -18 || c.powerDbm == -12 || c.powerDbm == -6 || c.powerDbm == 0)) c.powerDbm = cfgDefault.powerDbm;
  if (c.addrWidth < 3 || c.addrWidth > 5) c.addrWidth = cfgDefault.addrWidth;
  c.autoAckMask &= 0x3F;
  c.retryDelay &= 0x0F;
  c.retryCount &= 0x0F;
  if (c.fixedPayloadLen < 1 || c.fixedPayloadLen > 32) c.fixedPayloadLen = cfgDefault.fixedPayloadLen;
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
    st = startReceiveClean(true);
    if (st != RADIOLIB_ERR_NONE) return false;
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
  int st = radio.begin((int16_t)lroundf(cfg.freqMHz), cfg.bitRateKbps, cfg.powerDbm, cfg.addrWidth);
  if (st != RADIOLIB_ERR_NONE) {
    // Some clones need a second attempt
    delay(20);
    st = radio.begin((int16_t)lroundf(cfg.freqMHz), cfg.bitRateKbps, cfg.powerDbm, cfg.addrWidth);
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
  // 9) Leave CS idle. Do not force CE low when RX is enabled;
  // RadioLib drives CE high for receive mode.
  // -------------------------------------------------
  digitalWrite(NRF_CS, HIGH);

  return true;
}

static void printStatusRegisters() {
  Serial.print(F("STATUS=0x")); Serial.println(nrfReadReg(0x07), HEX);
  Serial.print(F("FIFO_STATUS=0x")); Serial.println(nrfReadReg(0x17), HEX);
  Serial.print(F("RF_CH=")); Serial.println(nrfReadReg(0x05));
  Serial.print(F("RF_SETUP=0x")); Serial.println(nrfReadReg(0x06), HEX);
  Serial.print(F("EN_AA=0x")); Serial.println(nrfReadReg(0x01), HEX);
  Serial.print(F("EN_RXADDR=0x")); Serial.println(nrfReadReg(0x02), HEX);
  Serial.print(F("SETUP_RETR=0x")); Serial.println(nrfReadReg(0x04), HEX);
  Serial.print(F("FEATURE=0x")); Serial.println(nrfReadReg(0x1D), HEX);
  Serial.print(F("DYNPD=0x")); Serial.println(nrfReadReg(0x1C), HEX);
  Serial.print(F("RPD=")); Serial.println(radio.isCarrierDetected() ? F("YES") : F("NO"));
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

  if (u == "AT+DEFAULT") {
    cfg = cfgDefault;
    rxEnabled = true;
    radioSleeping = false;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+FREQ?") { Serial.print(F("FREQ=")); Serial.println(cfg.freqMHz, 1); serialOK(); return true; }
  if (u.startsWith("AT+FREQ=")) {
    float v; if (!parseFloatValue(line.substring(8), v) || v < 2400.0f || v > 2525.0f) { serialERR(); return true; }
    cfg.freqMHz = v;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+CHAN?") { Serial.print(F("CHAN=")); Serial.println((int)lroundf(cfg.freqMHz - 2400.0f)); serialOK(); return true; }
  if (u.startsWith("AT+CHAN=")) {
    long v; if (!parseLong(line.substring(8), v) || v < 0 || v > 125) { serialERR(); return true; }
    cfg.freqMHz = 2400.0f + (float)v;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+RATE?") { Serial.print(F("RATE=")); Serial.println(cfg.bitRateKbps); serialOK(); return true; }
  if (u.startsWith("AT+RATE=")) {
    long v; if (!parseLong(line.substring(8), v) || !(v == 250 || v == 1000 || v == 2000)) { serialERR(); return true; }
    cfg.bitRateKbps = (uint16_t)v;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+PWR?") { Serial.print(F("PWR=")); Serial.println(cfg.powerDbm); serialOK(); return true; }
  if (u.startsWith("AT+PWR=")) {
    long v; if (!parseLong(line.substring(7), v) || !(v == -18 || v == -12 || v == -6 || v == 0)) { serialERR(); return true; }
    cfg.powerDbm = (int8_t)v;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  // Address query
  if (u == "AT+ADDR?") {
    printAddrLine(F("ADDR=0x"), cfg.txAddr);
    serialOK();
    return true;
  }

  // Address set
  if (u.startsWith("AT+ADDR=")) {
    uint8_t tmp[5];
    if (!parseHex5Bytes(line.substring(8), tmp)) { serialERR(); return true; }
    memcpy(cfg.txAddr, tmp, 5);
    memcpy(cfg.rxAddr[0], tmp, 5);
    cfg.pipeEnabled[0] = true;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+ADDRWIDTH?") { Serial.print(F("ADDRWIDTH=")); Serial.println(cfg.addrWidth); serialOK(); return true; }
  if (u.startsWith("AT+ADDRWIDTH=")) {
    long v; if (!parseLong(line.substring(13), v) || v < 3 || v > 5) { serialERR(); return true; }
    cfg.addrWidth = (uint8_t)v;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+TXADDR?") { printAddrLine(F("TXADDR=0x"), cfg.txAddr); serialOK(); return true; }
  if (u.startsWith("AT+TXADDR=")) {
    uint8_t tmp[5];
    if (!parseHex5Bytes(line.substring(10), tmp)) { serialERR(); return true; }
    memcpy(cfg.txAddr, tmp, 5);
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  for (uint8_t pipe = 0; pipe < 6; pipe++) {
    String q = String("AT+RXADDR") + pipe + "?";
    String s = String("AT+RXADDR") + pipe + "=";
    if (u == q) {
      Serial.print(F("RXADDR")); Serial.print(pipe); Serial.print(F("=0x"));
      for (uint8_t i = 0; i < cfg.addrWidth; i++) {
        if (cfg.rxAddr[pipe][i] < 16) Serial.print('0');
        Serial.print(cfg.rxAddr[pipe][i], HEX);
      }
      Serial.println();
      serialOK();
      return true;
    }
    if (u.startsWith(s)) {
      uint8_t tmp[5];
      if (!parseHex5Bytes(line.substring(s.length()), tmp)) { serialERR(); return true; }
      memcpy(cfg.rxAddr[pipe], tmp, 5);
      cfg.pipeEnabled[pipe] = true;
      bool ok = resetRadioBeginAndApply();
      if (ok) eepromSaveConfig(cfg);
      ok ? serialOK() : serialERR();
      return true;
    }
  }

  if (u == "AT+PIPES?") {
    for (uint8_t pipe = 0; pipe < 6; pipe++) {
      Serial.print(F("PIPE")); Serial.print(pipe); Serial.print('=');
      Serial.println(cfg.pipeEnabled[pipe] ? F("ON") : F("OFF"));
    }
    serialOK();
    return true;
  }

  for (uint8_t pipe = 0; pipe < 6; pipe++) {
    String s = String("AT+PIPE") + pipe + "=";
    if (u.startsWith(s)) {
      bool on; if (!parseOnOff(line.substring(s.length()), on)) { serialERR(); return true; }
      cfg.pipeEnabled[pipe] = on;
      bool ok = resetRadioBeginAndApply();
      if (ok) eepromSaveConfig(cfg);
      ok ? serialOK() : serialERR();
      return true;
    }
  }

  if (u == "AT+CRC?") { Serial.print(F("CRC=")); Serial.println(cfg.crcOn ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u.startsWith("AT+CRC=")) {
    bool on; if (!parseOnOff(line.substring(7), on)) { serialERR(); return true; }
    cfg.crcOn = on;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+AUTOACK?") { Serial.print(F("AUTOACK_MASK=0x")); Serial.println(cfg.autoAckMask, HEX); serialOK(); return true; }
  if (u.startsWith("AT+AUTOACK=")) {
    bool on; if (!parseOnOff(line.substring(11), on)) { serialERR(); return true; }
    cfg.autoAckMask = on ? 0x3F : 0x00;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }
  for (uint8_t pipe = 0; pipe < 6; pipe++) {
    String s = String("AT+AUTOACK") + pipe + "=";
    if (u.startsWith(s)) {
      bool on; if (!parseOnOff(line.substring(s.length()), on)) { serialERR(); return true; }
      if (on) cfg.autoAckMask |= (1 << pipe);
      else cfg.autoAckMask &= ~(1 << pipe);
      bool ok = resetRadioBeginAndApply();
      if (ok) eepromSaveConfig(cfg);
      ok ? serialOK() : serialERR();
      return true;
    }
  }

  if (u == "AT+RETRIES?") {
    Serial.print(F("RETRIES=")); Serial.print(cfg.retryDelay); Serial.print(','); Serial.println(cfg.retryCount);
    serialOK(); return true;
  }
  if (u.startsWith("AT+RETRIES=")) {
    String p = line.substring(11);
    int comma = p.indexOf(',');
    if (comma < 0) { serialERR(); return true; }
    long d, c;
    if (!parseLong(p.substring(0, comma), d) || !parseLong(p.substring(comma + 1), c) || d < 0 || d > 15 || c < 0 || c > 15) { serialERR(); return true; }
    cfg.retryDelay = (uint8_t)d;
    cfg.retryCount = (uint8_t)c;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+LNA?") { Serial.print(F("LNA=")); Serial.println(cfg.lnaOn ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u.startsWith("AT+LNA=")) {
    bool on; if (!parseOnOff(line.substring(7), on)) { serialERR(); return true; }
    cfg.lnaOn = on;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+DYN?") { Serial.print(F("DYN=")); Serial.println(cfg.dynamicPayload ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u.startsWith("AT+DYN=")) {
    bool on; if (!parseOnOff(line.substring(7), on)) { serialERR(); return true; }
    cfg.dynamicPayload = on;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+ACKPAY?") { Serial.print(F("ACKPAY=")); Serial.println(cfg.ackPayload ? F("ON") : F("OFF")); serialOK(); return true; }
  if (u.startsWith("AT+ACKPAY=")) {
    bool on; if (!parseOnOff(line.substring(10), on)) { serialERR(); return true; }
    cfg.ackPayload = on;
    if (on) cfg.dynamicPayload = true;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+PLEN?") { Serial.print(F("PLEN=")); Serial.println(cfg.fixedPayloadLen); serialOK(); return true; }
  if (u.startsWith("AT+PLEN=")) {
    long v; if (!parseLong(line.substring(8), v) || v < 1 || v > 32) { serialERR(); return true; }
    cfg.fixedPayloadLen = (uint8_t)v;
    bool ok = resetRadioBeginAndApply();
    if (ok) eepromSaveConfig(cfg);
    ok ? serialOK() : serialERR();
    return true;
  }

  if (u == "AT+STATUS?") {
    printStatusRegisters();
    serialOK();
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
    int st = startReceiveClean(true);
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

  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println(F("[EEPROM] begin() failed, using RAM defaults."));
  }
  if (!eepromLoadConfig(cfg)) {
    cfg = cfgDefault;
    eepromSaveConfig(cfg);
  }
  sanitizeConfig(cfg);

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
      if (radioSleeping) {
        serialError(F("RADIO_SLEEPING (send AT+WAKE)"));
        return;
      }
      if (line.length() > 32) {
        serialError(F("PAYLOAD_TOO_LONG (max 32 bytes)"));
        return;
      }
      if (!cfg.dynamicPayload && line.length() != cfg.fixedPayloadLen) {
        serialError(F("FIXED_PAYLOAD_LENGTH_MISMATCH (send AT+DYN=ON or adjust AT+PLEN)"));
        return;
      }

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
        startReceiveClean(false);
      }
    }
  }

  if (!receivedFlag && rxEnabled && !radioSleeping && nrfHasRxPayload()) {
    receivedFlag = true;
  }

  // Radio RX -> Serial
  if (receivedFlag && !radioSleeping) {
    receivedFlag = false;

    String str;
    int st = nrfReadReceivedText(str);

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
      startReceiveClean(false);
    }
  }
}
