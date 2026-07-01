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
#define CC1352_BRIDGE_HOST_BAUD 115200
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
static constexpr size_t CONTROL_BUFFER_SIZE = 64;
static constexpr size_t USB_SAFE_CHUNK_SIZE = 63;

static constexpr char CONTROL_PREFIX[] = "~CC1352P_";
static constexpr char RESET_COMMAND[] = "~CC1352P_RESET";
static constexpr char BOOT_LOW_COMMAND[] = "~CC1352P_BOOT=LOW";
static constexpr char BOOT_HIGH_COMMAND[] = "~CC1352P_BOOT=HIGH";
static constexpr char ENTER_BOOTLOADER_COMMAND[] = "~CC1352P_ENTER_BOOTLOADER";
static constexpr char BAUD_COMMAND[] = "~CC1352P_BAUD=";

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, OLED_RESET_PIN, OLED_SCL_PIN, OLED_SDA_PIN);
HardwareSerial Cc1352Serial(1);

static uint8_t controlBuffer[CONTROL_BUFFER_SIZE];
static size_t controlIndex = 0;
static uint32_t controlStartedAtMs = 0;
static uint32_t currentCc1352Baud = CC1352_UART_BAUD;
static uint32_t ledTickMs = 0;
static bool ledState = false;

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
    drawCentered("EBYTE", 42, u8g2_font_logisoso18_tr);
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
            digitalWrite(pin, LOW);
            pinMode(pin, OUTPUT);
        }
        else {
            digitalWrite(pin, HIGH);
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

static void flushControlPrefix()
{
    if (controlIndex == 0) {
        return;
    }

    Cc1352Serial.write(controlBuffer, controlIndex);
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
        Cc1352Serial.write(byte);
        return;
    }

    if (controlIndex == 0) {
        controlStartedAtMs = millis();
    }

    if (controlIndex >= sizeof(controlBuffer)) {
        flushControlPrefix();
        Cc1352Serial.write(byte);
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
    pumpUsbToCc1352();
    pumpCc1352ToUsb();
}
