#include <Arduino.h>
#include <U8g2lib.h>

static constexpr int OLED_SDA_PIN = 5;
static constexpr int OLED_SCL_PIN = 6;
static constexpr int OLED_RESET_PIN = U8X8_PIN_NONE;
static constexpr int LED_PIN = 8;

static constexpr int CC1352_UART_RX_PIN = 20;  // ESP32 RX, connected to CC1352 TX
static constexpr int CC1352_UART_TX_PIN = 21;  // ESP32 TX, connected to CC1352 RX
static constexpr int CC1352_BOOT_PIN = 3;      // Drives E79 BOOT / CC1352P DIO15
static constexpr int CC1352_RESET_PIN = 10;    // Drives CC1352P RESET_N

#ifndef CC1352_BRIDGE_HOST_BAUD
#define CC1352_BRIDGE_HOST_BAUD 1000000
#endif

#ifndef CC1352_BOOT_ACTIVE_LOW
#define CC1352_BOOT_ACTIVE_LOW 1
#endif

#ifndef CC1352_RESET_ACTIVE_LOW
#define CC1352_RESET_ACTIVE_LOW 1
#endif

#ifndef CC1352_BOOT_OPEN_DRAIN
#define CC1352_BOOT_OPEN_DRAIN 1
#endif

#ifndef CC1352_RESET_OPEN_DRAIN
#define CC1352_RESET_OPEN_DRAIN 1
#endif

static constexpr uint32_t CC1352_UART_BAUD = CC1352_BRIDGE_HOST_BAUD;
static constexpr int CC1352_BOOT_ACTIVE_LEVEL = CC1352_BOOT_ACTIVE_LOW ? LOW : HIGH;
static constexpr int CC1352_BOOT_IDLE_LEVEL = CC1352_BOOT_ACTIVE_LOW ? HIGH : LOW;
static constexpr int CC1352_RESET_ACTIVE_LEVEL = CC1352_RESET_ACTIVE_LOW ? LOW : HIGH;
static constexpr int CC1352_RESET_IDLE_LEVEL = CC1352_RESET_ACTIVE_LOW ? HIGH : LOW;
static constexpr size_t BRIDGE_BUFFER_SIZE = 512;
static constexpr uint32_t MAGIC_TIMEOUT_MS = 1000;
static constexpr uint32_t HIDDEN_RESPONSE_TIMEOUT_MS = 500;
static constexpr size_t CONTROL_BUFFER_SIZE = 64;
static constexpr size_t HOST_LINE_BUFFER_SIZE = 192;
static constexpr size_t CC1352_LINE_BUFFER_SIZE = 256;
static constexpr size_t USB_SAFE_CHUNK_SIZE = 63;

static constexpr char CONTROL_PREFIX[] = "~CC1352P_";
static constexpr char RESET_COMMAND[] = "~CC1352P_RESET";
static constexpr char BOOT_LOW_COMMAND[] = "~CC1352P_BOOT=LOW";
static constexpr char BOOT_HIGH_COMMAND[] = "~CC1352P_BOOT=HIGH";
static constexpr char ENTER_BOOTLOADER_COMMAND[] = "~CC1352P_ENTER_BOOTLOADER";
static constexpr char BAUD_COMMAND[] = "~CC1352P_BAUD=";
static constexpr char AT_SEND_PREFIX[] = "AT+SEND=";

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, OLED_RESET_PIN, OLED_SCL_PIN, OLED_SDA_PIN);
HardwareSerial Cc1352Serial(1);

static uint8_t controlBuffer[CONTROL_BUFFER_SIZE];
static uint8_t hostLineBuffer[HOST_LINE_BUFFER_SIZE];
static uint8_t cc1352LineBuffer[CC1352_LINE_BUFFER_SIZE];
static size_t controlIndex = 0;
static size_t hostLineIndex = 0;
static size_t cc1352LineIndex = 0;
static uint32_t controlStartedAtMs = 0;
static uint32_t currentCc1352Baud = CC1352_UART_BAUD;
static uint32_t ledTickMs = 0;
static uint32_t hiddenResponseDeadlineMs = 0;
static uint8_t hiddenResponseCount = 0;
static bool ledState = false;
static bool hostIgnoreNextLf = false;
static bool cc1352IgnoreNextLf = false;
static bool hostDroppingLine = false;
static bool cc1352DroppingLine = false;
static bool cc1352RawForwardMode = false;

static void drawCentered(const char *text, int baselineY, const uint8_t *font)
{
    u8g2.setFont(font);
    int x = (128 - u8g2.getStrWidth(text)) / 2;
    if (x < 0) {
        x = 0;
    }
    u8g2.drawStr(x, baselineY, text);
}

static void oledDrawSplash()
{
    u8g2.clearBuffer();
    drawCentered("RADIO", 42, u8g2_font_logisoso18_tr);
    drawCentered("E79", 63, u8g2_font_logisoso18_tr);
    u8g2.sendBuffer();
}

static void oledSetup()
{
    u8g2.begin();
    u8g2.setContrast(255);
    u8g2.setBusClock(400000);
    oledDrawSplash();
}

static void led1HzService()
{
    uint32_t now = millis();
    if ((uint32_t)(now - ledTickMs) >= 1000U) {
        ledTickMs = now;
        ledState = !ledState;
        digitalWrite(LED_PIN, ledState ? HIGH : LOW);
    }
}

static void driveControlPin(int pin, bool active, int activeLevel, int idleLevel, bool openDrain)
{
    if (openDrain && activeLevel == LOW) {
        if (active) {
            pinMode(pin, OUTPUT);
            digitalWrite(pin, LOW);
        }
        else {
            pinMode(pin, INPUT);
        }
        return;
    }

    pinMode(pin, OUTPUT);
    digitalWrite(pin, active ? activeLevel : idleLevel);
}

static void setCc1352BootActive(bool active)
{
    driveControlPin(CC1352_BOOT_PIN,
                    active,
                    CC1352_BOOT_ACTIVE_LEVEL,
                    CC1352_BOOT_IDLE_LEVEL,
                    CC1352_BOOT_OPEN_DRAIN != 0);
}

static void setCc1352ResetActive(bool active)
{
    driveControlPin(CC1352_RESET_PIN,
                    active,
                    CC1352_RESET_ACTIVE_LEVEL,
                    CC1352_RESET_IDLE_LEVEL,
                    CC1352_RESET_OPEN_DRAIN != 0);
}

static void pulseCc1352Reset()
{
    setCc1352ResetActive(false);
    delay(20);
    setCc1352ResetActive(true);
    delay(40);
    setCc1352ResetActive(false);
    delay(150);
}

static void serviceHiddenResponseTimeout()
{
    if (hiddenResponseCount > 0 &&
        (int32_t)(millis() - hiddenResponseDeadlineMs) >= 0) {
        hiddenResponseCount = 0;
    }
}

static void enterCc1352Bootloader()
{
    setCc1352BootActive(true);
    delay(20);
    pulseCc1352Reset();
    delay(250);
    setCc1352BootActive(false);
    delay(50);
}

static void setCc1352Baud(uint32_t baud)
{
    if (baud == 0 || baud == currentCc1352Baud) {
        return;
    }

    Cc1352Serial.flush();
    Cc1352Serial.end();
    delay(20);
    Cc1352Serial.begin(baud, SERIAL_8N1, CC1352_UART_RX_PIN, CC1352_UART_TX_PIN);
    currentCc1352Baud = baud;
}

static bool lineStartsWithAt(const uint8_t *line, size_t len)
{
    return len >= 2 &&
           (line[0] == 'A' || line[0] == 'a') &&
           (line[1] == 'T' || line[1] == 't');
}

static bool lineEquals(const uint8_t *line, size_t len, const char *text)
{
    const size_t textLen = strlen(text);

    return len == textLen && memcmp(line, text, textLen) == 0;
}

static bool lineStartsWith(const uint8_t *line, size_t len, const char *prefix)
{
    const size_t prefixLen = strlen(prefix);

    return len >= prefixLen && memcmp(line, prefix, prefixLen) == 0;
}

static int hexValue(uint8_t value)
{
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    if (value >= 'a' && value <= 'f') {
        return value - 'a' + 10;
    }
    if (value >= 'A' && value <= 'F') {
        return value - 'A' + 10;
    }
    return -1;
}

static void forwardHostLineToCc1352(const uint8_t *line, size_t len)
{
    if (len == 0) {
        return;
    }

    if (lineStartsWithAt(line, len)) {
        Cc1352Serial.write(line, len);
    }
    else {
        Cc1352Serial.write((const uint8_t *)AT_SEND_PREFIX, sizeof(AT_SEND_PREFIX) - 1);
        Cc1352Serial.write(line, len);
        if (hiddenResponseCount < 255) {
            hiddenResponseCount++;
            hiddenResponseDeadlineMs = millis() + HIDDEN_RESPONSE_TIMEOUT_MS;
        }
    }
    Cc1352Serial.write("\r\n");
}

static void forwardHostDataByte(uint8_t byte)
{
    if (cc1352RawForwardMode) {
        Cc1352Serial.write(byte);
        return;
    }

    if (byte == '\r' || byte == '\n') {
        if (byte == '\n' && hostIgnoreNextLf) {
            hostIgnoreNextLf = false;
            return;
        }

        hostIgnoreNextLf = (byte == '\r');

        if (hostDroppingLine) {
            hostDroppingLine = false;
        }
        else if (hostLineIndex > 0) {
            forwardHostLineToCc1352(hostLineBuffer, hostLineIndex);
        }
        hostLineIndex = 0;
        return;
    }

    hostIgnoreNextLf = false;

    if (hostDroppingLine) {
        return;
    }

    if (hostLineIndex + 1 <= sizeof(hostLineBuffer)) {
        hostLineBuffer[hostLineIndex++] = byte;
    }
    else {
        hostLineIndex = 0;
        hostDroppingLine = true;
        Serial.println(F("#ERROR: LINE_TOO_LONG"));
    }
}

static void flushControlPrefix()
{
    if (controlIndex == 0) {
        return;
    }

    for (size_t i = 0; i < controlIndex; ++i) {
        forwardHostDataByte(controlBuffer[i]);
    }
    controlIndex = 0;
}

static void maybeFlushStaleControlPrefix()
{
    if (controlIndex == 0) {
        return;
    }

    if ((uint32_t)(millis() - controlStartedAtMs) >= MAGIC_TIMEOUT_MS) {
        flushControlPrefix();
    }
}

static bool isControlPrefixMatch()
{
    const size_t prefixLen = sizeof(CONTROL_PREFIX) - 1;

    if (controlIndex > prefixLen) {
        return true;
    }

    for (size_t i = 0; i < controlIndex; ++i) {
        if (controlBuffer[i] != (uint8_t)CONTROL_PREFIX[i]) {
            return false;
        }
    }

    return true;
}

static uint32_t parseBaudValue(const char *text)
{
    uint32_t baud = 0;

    while (*text >= '0' && *text <= '9') {
        baud = (baud * 10u) + (uint32_t)(*text - '0');
        ++text;
    }

    if (*text != '\0') {
        return 0;
    }

    switch (baud) {
    case 9600:
    case 38400:
    case 57600:
    case 115200:
    case 230400:
    case 460800:
    case 500000:
    case 921600:
    case 1000000:
        return baud;
    default:
        return 0;
    }
}

static bool handleControlLine()
{
    char line[CONTROL_BUFFER_SIZE];
    const size_t count = controlIndex;

    for (size_t i = 0; i < count; ++i) {
        line[i] = (char)controlBuffer[i];
    }

    while (controlIndex > 0 &&
           (line[controlIndex - 1] == '\n' || line[controlIndex - 1] == '\r')) {
        line[--controlIndex] = '\0';
    }
    line[controlIndex] = '\0';

    controlIndex = 0;

    if (strcmp(line, RESET_COMMAND) == 0) {
        cc1352RawForwardMode = false;
        hostLineIndex = 0;
        hostDroppingLine = false;
        pulseCc1352Reset();
        return true;
    }

    if (strcmp(line, BOOT_LOW_COMMAND) == 0) {
        setCc1352BootActive(true);
        return true;
    }

    if (strcmp(line, BOOT_HIGH_COMMAND) == 0) {
        setCc1352BootActive(false);
        return true;
    }

    if (strcmp(line, ENTER_BOOTLOADER_COMMAND) == 0) {
        enterCc1352Bootloader();
        cc1352RawForwardMode = true;
        hostLineIndex = 0;
        hostDroppingLine = false;
        return true;
    }

    const size_t baudCommandLen = sizeof(BAUD_COMMAND) - 1;
    if (strncmp(line, BAUD_COMMAND, baudCommandLen) == 0) {
        const uint32_t baud = parseBaudValue(line + baudCommandLen);
        if (baud != 0) {
            setCc1352Baud(baud);
            return true;
        }
    }

    Cc1352Serial.write((const uint8_t *)line, strlen(line));
    return false;
}

static void forwardHostByte(uint8_t byte)
{
    if (controlIndex == 0 && byte != (uint8_t)CONTROL_PREFIX[0]) {
        forwardHostDataByte(byte);
        return;
    }

    if (controlIndex == 0) {
        controlStartedAtMs = millis();
    }

    if (controlIndex >= sizeof(controlBuffer)) {
        flushControlPrefix();
        forwardHostDataByte(byte);
        return;
    }

    controlBuffer[controlIndex++] = byte;

    if (!isControlPrefixMatch()) {
        flushControlPrefix();
        return;
    }

    if (byte == '\n') {
        handleControlLine();
    }
}

static void pumpUsbToCc1352()
{
    uint8_t buffer[BRIDGE_BUFFER_SIZE];
    int available = Serial.available();

    if (available <= 0) {
        return;
    }

    if (available > (int)sizeof(buffer)) {
        available = sizeof(buffer);
    }

    const size_t count = Serial.read(buffer, available);
    for (size_t i = 0; i < count; ++i) {
        forwardHostByte(buffer[i]);
    }
    if (count > 0) {
        Cc1352Serial.flush();
    }
}

static bool emitRxTextLine(const uint8_t *line, size_t len)
{
    const uint8_t *firstComma = nullptr;
    const uint8_t *secondComma = nullptr;

    if (!lineStartsWith(line, len, "+RX:")) {
        return false;
    }

    for (size_t i = 4; i < len; ++i) {
        if (line[i] == ',') {
            firstComma = line + i;
            break;
        }
    }
    if (firstComma == nullptr) {
        return false;
    }

    for (const uint8_t *p = firstComma + 1; p < line + len; ++p) {
        if (*p == ',') {
            secondComma = p;
            break;
        }
    }
    if (secondComma == nullptr) {
        return false;
    }

    const uint8_t *payload = secondComma + 1;
    Serial.write(payload, (line + len) - payload);
    Serial.println();
    return true;
}

static bool emitRxHexLine(const uint8_t *line, size_t len)
{
    const uint8_t *firstComma = nullptr;
    const uint8_t *secondComma = nullptr;

    if (!lineStartsWith(line, len, "+RXHEX:")) {
        return false;
    }

    for (size_t i = 7; i < len; ++i) {
        if (line[i] == ',') {
            firstComma = line + i;
            break;
        }
    }
    if (firstComma == nullptr) {
        return false;
    }

    for (const uint8_t *p = firstComma + 1; p < line + len; ++p) {
        if (*p == ',') {
            secondComma = p;
            break;
        }
    }
    if (secondComma == nullptr) {
        return false;
    }

    const uint8_t *hex = secondComma + 1;
    const size_t hexLen = (line + len) - hex;
    if ((hexLen % 2) != 0) {
        return false;
    }

    for (size_t i = 0; i < hexLen; i += 2) {
        const int high = hexValue(hex[i]);
        const int low = hexValue(hex[i + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        Serial.write((uint8_t)((high << 4) | low));
    }
    Serial.println();
    return true;
}

static void emitCc1352Line(const uint8_t *line, size_t len)
{
    if (len == 0) {
        return;
    }

    if (lineEquals(line, len, "OK")) {
        if (hiddenResponseCount > 0) {
            hiddenResponseCount--;
            return;
        }
        Serial.println(F("OK"));
        return;
    }

    if (lineStartsWith(line, len, "#ERROR:")) {
        if (hiddenResponseCount > 0) {
            hiddenResponseCount--;
        }
        Serial.write(line, len);
        Serial.println();
        return;
    }

    if (emitRxTextLine(line, len) || emitRxHexLine(line, len)) {
        return;
    }

    Serial.write(line, len);
    Serial.println();
}

static void forwardCc1352Byte(uint8_t byte)
{
    if (byte == '\r' || byte == '\n') {
        if (byte == '\n' && cc1352IgnoreNextLf) {
            cc1352IgnoreNextLf = false;
            return;
        }

        cc1352IgnoreNextLf = (byte == '\r');

        if (cc1352DroppingLine) {
            cc1352DroppingLine = false;
        }
        else if (cc1352LineIndex > 0) {
            emitCc1352Line(cc1352LineBuffer, cc1352LineIndex);
        }
        cc1352LineIndex = 0;
        return;
    }

    cc1352IgnoreNextLf = false;

    if (cc1352DroppingLine) {
        return;
    }

    if (cc1352LineIndex + 1 <= sizeof(cc1352LineBuffer)) {
        cc1352LineBuffer[cc1352LineIndex++] = byte;
    }
    else {
        cc1352LineIndex = 0;
        cc1352DroppingLine = true;
    }
}

static void pumpCc1352ToUsb()
{
    uint8_t buffer[BRIDGE_BUFFER_SIZE];
    int available = Cc1352Serial.available();

    if (available <= 0) {
        return;
    }

    if (available > (int)sizeof(buffer)) {
        available = sizeof(buffer);
    }

    const size_t count = Cc1352Serial.read(buffer, available);
    if (!cc1352RawForwardMode) {
        for (size_t i = 0; i < count; ++i) {
            forwardCc1352Byte(buffer[i]);
        }
        Serial.flush();
        return;
    }

    size_t offset = 0;
    while (offset < count) {
        size_t chunk = count - offset;
        if (chunk > USB_SAFE_CHUNK_SIZE) {
            chunk = USB_SAFE_CHUNK_SIZE;
        }

        Serial.write(buffer + offset, chunk);
        Serial.flush();
        offset += chunk;
    }
}

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    setCc1352BootActive(false);
    setCc1352ResetActive(false);

    oledSetup();

    Serial.begin(115200);
    Serial.setRxBufferSize(4096);
    Serial.setTxTimeoutMs(20);
    Serial.setDebugOutput(false);

    Cc1352Serial.setRxBufferSize(4096);
    Cc1352Serial.setTxBufferSize(2048);
    Cc1352Serial.begin(CC1352_UART_BAUD, SERIAL_8N1, CC1352_UART_RX_PIN, CC1352_UART_TX_PIN);
}

void loop()
{
    led1HzService();
    maybeFlushStaleControlPrefix();
    serviceHiddenResponseTimeout();
    pumpUsbToCc1352();
    pumpCc1352ToUsb();
}
