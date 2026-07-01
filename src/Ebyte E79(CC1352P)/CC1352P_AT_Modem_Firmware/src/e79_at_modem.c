/*
 * Ebyte E79-400DM2005S / TI CC1352P UART AT radio modem.
 *
 * Base RF configuration is generated from TI Proprietary RF
 * 2-GFSK 50 kbps 433 MHz settings for CC1352P_4_LAUNCHXL.
 */

#include <ctype.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <ti/drivers/GPIO.h>
#include <ti/drivers/Power.h>
#include <ti/drivers/UART2.h>
#include <ti/drivers/dpl/ClockP.h>
#include <ti/drivers/power/PowerCC26XX.h>
#include <ti/drivers/rf/RF.h>

#include DeviceFamily_constructPath(driverlib/rf_prop_mailbox.h)

#include "RFQueue.h"
#include "ti_drivers_config.h"
#include <ti_radio_config.h>

#define FW_NAME                 "E79_AT_MODEM"
#define FW_VERSION              "0.1.0"
#define FW_SDK                  "SimpleLink-LPF2-SDK 8.33.00.16"

#ifndef E79_UART_BAUD
#define E79_UART_BAUD           1000000U
#endif

#define UART_BAUD               E79_UART_BAUD

#define CMD_BUFFER_LEN          192U
#define UART_PRINTF_LEN         224U

#define MAX_RF_PAYLOAD          64U
#define NUM_DATA_ENTRIES        2U
#define RX_APPENDED_BYTES       3U

#define FREQ_MIN_HZ             431000000UL
#define FREQ_MAX_HZ             500000000UL
#define DEFAULT_FREQ_HZ         433920000UL
#define DEFAULT_RATE_BPS        50000UL
#define DEFAULT_PWR_DBM         13
#define DEFAULT_SYNC_WORD       0x930B51DEUL

#define E79_RF_SW_DIO5          5U
#define E79_RF_SW_DIO6          6U

typedef struct
{
    uint32_t freqHz;
    uint32_t rateBps;
    int8_t pwrDbm;
    uint32_t syncWord;
    bool debug;
    bool rxEnabled;
    bool sleeping;
} ModemConfig;

typedef struct
{
    uint8_t len;
    int8_t rssi;
    uint8_t data[MAX_RF_PAYLOAD];
} PacketInfo;

static const int8_t supportedPowersDbm[] = {
    -20, -15, -10, -5,
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
};

static ModemConfig cfg;

static UART2_Handle uartHandle;
static uint8_t uartRxByte;
static char uartInput[CMD_BUFFER_LEN];
static char uartLine[CMD_BUFFER_LEN];
static size_t uartInputLen;
static volatile bool uartLineReady;
static volatile bool uartLineOverflow;
static bool ignoreNextLf;
static bool uartDroppingLine;
static bool uartStartupSynced;
static bool awakePowerConstraintsHeld;

static RF_Object rfObject;
static RF_Handle rfHandle;
static RF_CmdHandle rxCmdHandle = RF_ALLOC_ERROR;
static bool rxCommandActive;

static dataQueue_t dataQueue;
static uint8_t txPacket[MAX_RF_PAYLOAD];

static volatile bool rxPacketReady;
static PacketInfo rxPacketPending;
static PacketInfo lastPacket;
static bool haveLastPacket;

static uint32_t rxCount;
static uint32_t txCount;
static uint32_t errorCount;
static uint32_t randomState = 0x1352E079UL;

#if defined(__TI_COMPILER_VERSION__)
#pragma DATA_ALIGN(rxDataEntryBuffer, 4);
static uint8_t rxDataEntryBuffer[RF_QUEUE_DATA_ENTRY_BUFFER_SIZE(NUM_DATA_ENTRIES,
                                                                 MAX_RF_PAYLOAD,
                                                                 RX_APPENDED_BYTES)];
#elif defined(__IAR_SYSTEMS_ICC__)
#pragma data_alignment = 4
static uint8_t rxDataEntryBuffer[RF_QUEUE_DATA_ENTRY_BUFFER_SIZE(NUM_DATA_ENTRIES,
                                                                 MAX_RF_PAYLOAD,
                                                                 RX_APPENDED_BYTES)];
#elif defined(__GNUC__)
static uint8_t rxDataEntryBuffer[RF_QUEUE_DATA_ENTRY_BUFFER_SIZE(NUM_DATA_ENTRIES,
                                                                 MAX_RF_PAYLOAD,
                                                                 RX_APPENDED_BYTES)]
    __attribute__((aligned(4)));
#else
#error This compiler is not supported.
#endif

static void rfRxCallback(RF_Handle h, RF_CmdHandle ch, RF_EventMask e);
static void uartRxCallback(UART2_Handle handle, void *buffer, size_t count,
                           void *userArg, int_fast16_t status);

static void uartWriteRaw(const char *text)
{
    if (uartHandle == NULL || text == NULL) {
        return;
    }

    UART2_write(uartHandle, text, strlen(text), NULL);
}

static void uartPrintf(const char *fmt, ...)
{
    char buffer[UART_PRINTF_LEN];
    va_list args;

    va_start(args, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, args);
    va_end(args);

    buffer[sizeof(buffer) - 1U] = '\0';
    uartWriteRaw(buffer);
}

static void sendOk(void)
{
    uartWriteRaw("OK\r\n");
}

static void sendError(const char *reason)
{
    errorCount++;
    uartPrintf("#ERROR: %s\r\n", reason);
}

static void sendSleepingError(void)
{
    errorCount++;
    uartWriteRaw("#ERROR: RADIO_SLEEPING (send AT+WAKE)\r\n");
}

static void holdAwakePowerConstraints(void)
{
    if (!awakePowerConstraintsHeld) {
        Power_setConstraint(PowerCC26XX_IDLE_PD_DISALLOW);
        Power_setConstraint(PowerCC26XX_SB_DISALLOW);
        awakePowerConstraintsHeld = true;
    }
}

static void releaseAwakePowerConstraints(void)
{
    if (awakePowerConstraintsHeld) {
        Power_releaseConstraint(PowerCC26XX_SB_DISALLOW);
        Power_releaseConstraint(PowerCC26XX_IDLE_PD_DISALLOW);
        awakePowerConstraintsHeld = false;
    }
}

static void startUartRead(void)
{
    if (uartHandle != NULL) {
        UART2_read(uartHandle, &uartRxByte, 1U, NULL);
    }
}

static void setDefaultConfig(void)
{
    cfg.freqHz = DEFAULT_FREQ_HZ;
    cfg.rateBps = DEFAULT_RATE_BPS;
    cfg.pwrDbm = DEFAULT_PWR_DBM;
    cfg.syncWord = DEFAULT_SYNC_WORD;
    cfg.debug = false;
    cfg.rxEnabled = false;
    cfg.sleeping = false;
}

static bool isSupportedPower(int32_t dbm)
{
    size_t i;

    for (i = 0; i < sizeof(supportedPowersDbm) / sizeof(supportedPowersDbm[0]); i++) {
        if (supportedPowersDbm[i] == dbm) {
            return true;
        }
    }

    return false;
}

static bool validateConfig(const ModemConfig *candidate, const char **error)
{
    if (candidate->freqHz < FREQ_MIN_HZ || candidate->freqHz > FREQ_MAX_HZ) {
        *error = "BAD_FREQ";
        return false;
    }

    if (candidate->rateBps != DEFAULT_RATE_BPS) {
        *error = "BAD_RATE";
        return false;
    }

    if (!isSupportedPower(candidate->pwrDbm)) {
        *error = "BAD_PWR";
        return false;
    }

    return true;
}

static bool validatePowerInput(int32_t dbm)
{
    if (dbm < -128 || dbm > 127) {
        return false;
    }

    return isSupportedPower(dbm);
}

static void configureFrequency(uint32_t freqHz)
{
    uint32_t wholeMHz = freqHz / 1000000UL;
    uint32_t remainderHz = freqHz % 1000000UL;
    uint32_t fract = (uint32_t)(((uint64_t)remainderHz * 65536ULL + 500000ULL) / 1000000ULL);

    if (fract >= 65536UL) {
        wholeMHz++;
        fract = 0;
    }

    RF_cmdPropRadioDivSetup.centerFreq = (uint16_t)wholeMHz;
    RF_cmdFs.frequency = (uint16_t)wholeMHz;
    RF_cmdFs.fractFreq = (uint16_t)fract;
}

static bool configurePower(int8_t dbm)
{
    RF_TxPowerTable_Value value = RF_TxPowerTable_findValue(txPowerTable_433_pa13, dbm);

    if (value.rawValue == RF_TxPowerTable_INVALID_VALUE) {
        return false;
    }

    RF_cmdPropRadioDivSetup.txPower = (uint16_t)value.rawValue;
    if (rfHandle != NULL) {
        RF_setTxPower(rfHandle, value);
    }

    return true;
}

static void configureRadioCommands(void)
{
    configureFrequency(cfg.freqHz);
    configurePower(cfg.pwrDbm);

    RF_cmdPropTx.pPkt = txPacket;
    RF_cmdPropTx.startTrigger.triggerType = TRIG_NOW;
    RF_cmdPropTx.syncWord = cfg.syncWord;

    RF_cmdPropRx.pQueue = &dataQueue;
    RF_cmdPropRx.rxConf.bAutoFlushIgnored = 1;
    RF_cmdPropRx.rxConf.bAutoFlushCrcErr = 1;
    RF_cmdPropRx.rxConf.bAppendRssi = 1;
    RF_cmdPropRx.maxPktLen = MAX_RF_PAYLOAD;
    RF_cmdPropRx.pktConf.bRepeatOk = 1;
    RF_cmdPropRx.pktConf.bRepeatNok = 1;
    RF_cmdPropRx.pktConf.bChkAddress = 0;
    RF_cmdPropRx.syncWord = cfg.syncWord;
}

static void rfSwitchOff(void)
{
    GPIO_write(E79_RF_SW_DIO5, 0);
    GPIO_write(E79_RF_SW_DIO6, 0);
}

static void rfSwitchRx(void)
{
    GPIO_write(E79_RF_SW_DIO5, 0);
    GPIO_write(E79_RF_SW_DIO6, 1);
}

static void rfSwitchTx(void)
{
    GPIO_write(E79_RF_SW_DIO6, 0);
    GPIO_write(E79_RF_SW_DIO5, 1);
}

static void rfSwitchInit(void)
{
    GPIO_setConfig(E79_RF_SW_DIO5, GPIO_CFG_OUT_STD | GPIO_CFG_OUT_LOW);
    GPIO_setConfig(E79_RF_SW_DIO6, GPIO_CFG_OUT_STD | GPIO_CFG_OUT_LOW);
    rfSwitchOff();
}

static bool radioOpen(void)
{
    RF_Params rfParams;

    if (rfHandle != NULL) {
        return true;
    }

    configureRadioCommands();
    RF_Params_init(&rfParams);
    rfHandle = RF_open(&rfObject, &RF_prop,
                       (RF_RadioSetup *)&RF_cmdPropRadioDivSetup,
                       &rfParams);
    if (rfHandle == NULL) {
        return false;
    }

    configurePower(cfg.pwrDbm);
    RF_runCmd(rfHandle, (RF_Op *)&RF_cmdFs, RF_PriorityNormal, NULL, 0);
    return true;
}

static void rxStop(void)
{
    if (rfHandle != NULL && rxCommandActive && rxCmdHandle >= 0) {
        RF_CmdHandle handle = rxCmdHandle;

        RF_cancelCmd(rfHandle, rxCmdHandle, RF_ABORT_GRACEFULLY);
        RF_pendCmd(rfHandle, handle,
                   RF_EventLastCmdDone |
                   RF_EventCmdCancelled |
                   RF_EventCmdAborted |
                   RF_EventCmdStopped);
    }

    rxCommandActive = false;
    rxCmdHandle = RF_ALLOC_ERROR;
    rfSwitchOff();
}

static bool rxStart(void)
{
    if (cfg.sleeping) {
        return false;
    }

    if (!radioOpen()) {
        return false;
    }

    if (rxCommandActive) {
        return true;
    }

    rfSwitchRx();
    rxCmdHandle = RF_postCmd(rfHandle, (RF_Op *)&RF_cmdPropRx,
                             RF_PriorityNormal, rfRxCallback,
                             RF_EventRxEntryDone);
    rxCommandActive = (rxCmdHandle != RF_ALLOC_ERROR);

    if (!rxCommandActive) {
        rfSwitchOff();
    }

    return rxCommandActive;
}

static void radioClose(void)
{
    rxStop();
    if (rfHandle != NULL) {
        RF_close(rfHandle);
        rfHandle = NULL;
    }
    rfSwitchOff();
}

static void resetModemState(void)
{
    holdAwakePowerConstraints();
    radioClose();
    setDefaultConfig();
    configureRadioCommands();

    rxPacketReady = false;
    haveLastPacket = false;
    rxCount = 0;
    txCount = 0;
    errorCount = 0;
}

static bool applyConfig(const ModemConfig *candidate)
{
    const char *error = NULL;
    bool restartRx;

    if (!validateConfig(candidate, &error)) {
        sendError(error);
        return false;
    }

    restartRx = rxCommandActive || (cfg.rxEnabled && !cfg.sleeping);
    if (restartRx) {
        rxStop();
    }

    cfg = *candidate;
    configureRadioCommands();

    if (!cfg.sleeping && rfHandle != NULL) {
        configurePower(cfg.pwrDbm);
        RF_runCmd(rfHandle, (RF_Op *)&RF_cmdFs, RF_PriorityNormal, NULL, 0);
    }

    if (!cfg.sleeping && cfg.rxEnabled) {
        if (!rxStart()) {
            sendError("RX_START_FAILED");
            return false;
        }
    }

    return true;
}

static bool parseUint32Strict(const char *text, uint32_t *value)
{
    char *end = NULL;
    unsigned long parsed;

    if (text == NULL || *text == '\0') {
        return false;
    }

    parsed = strtoul(text, &end, 10);
    if (end == text || *end != '\0' || parsed > 0xFFFFFFFFUL) {
        return false;
    }

    *value = (uint32_t)parsed;
    return true;
}

static bool parseInt32Strict(const char *text, int32_t *value)
{
    char *end = NULL;
    long parsed;

    if (text == NULL || *text == '\0') {
        return false;
    }

    parsed = strtol(text, &end, 10);
    if (end == text || *end != '\0') {
        return false;
    }

    *value = (int32_t)parsed;
    return true;
}

static bool parseHexWord(const char *text, uint32_t *value)
{
    uint32_t parsed = 0;
    size_t digits = 0;

    if (text == NULL) {
        return false;
    }

    if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        text += 2;
    }

    while (*text != '\0') {
        int nibble;

        if (*text >= '0' && *text <= '9') {
            nibble = *text - '0';
        }
        else if (*text >= 'a' && *text <= 'f') {
            nibble = *text - 'a' + 10;
        }
        else if (*text >= 'A' && *text <= 'F') {
            nibble = *text - 'A' + 10;
        }
        else {
            return false;
        }

        if (digits >= 8U) {
            return false;
        }

        parsed = (parsed << 4) | (uint32_t)nibble;
        digits++;
        text++;
    }

    if (digits == 0U) {
        return false;
    }

    *value = parsed;
    return true;
}

static bool hexNibble(char c, uint8_t *value)
{
    if (c >= '0' && c <= '9') {
        *value = (uint8_t)(c - '0');
        return true;
    }
    if (c >= 'a' && c <= 'f') {
        *value = (uint8_t)(c - 'a' + 10);
        return true;
    }
    if (c >= 'A' && c <= 'F') {
        *value = (uint8_t)(c - 'A' + 10);
        return true;
    }
    return false;
}

static bool parseHexPayload(const char *text, uint8_t *data, uint8_t *len)
{
    size_t textLen;
    size_t i;

    if (text == NULL) {
        return false;
    }

    textLen = strlen(text);
    if (textLen == 0U || (textLen % 2U) != 0U || textLen > (MAX_RF_PAYLOAD * 2U)) {
        return false;
    }

    for (i = 0; i < textLen / 2U; i++) {
        uint8_t hi;
        uint8_t lo;

        if (!hexNibble(text[i * 2U], &hi) || !hexNibble(text[i * 2U + 1U], &lo)) {
            return false;
        }
        data[i] = (uint8_t)((hi << 4) | lo);
    }

    *len = (uint8_t)(textLen / 2U);
    return true;
}

static char *trim(char *text)
{
    char *end;

    while (*text != '\0' && isspace((unsigned char)*text)) {
        text++;
    }

    if (*text == '\0') {
        return text;
    }

    end = text + strlen(text) - 1U;
    while (end > text && isspace((unsigned char)*end)) {
        *end = '\0';
        end--;
    }

    return text;
}

static void toUpperCopy(char *dst, const char *src, size_t dstLen)
{
    size_t i;

    for (i = 0; i + 1U < dstLen && src[i] != '\0'; i++) {
        dst[i] = (char)toupper((unsigned char)src[i]);
    }
    dst[i] = '\0';
}

static bool startsWith(const char *text, const char *prefix)
{
    return strncmp(text, prefix, strlen(prefix)) == 0;
}

static bool isAtPrefixChar(uint8_t c)
{
    return c == 'A' || c == 'a';
}

static bool isAtSecondChar(uint8_t c)
{
    return c == 'T' || c == 't';
}

static void appendHexByte(char *out, size_t outLen, size_t *pos, uint8_t value)
{
    static const char hex[] = "0123456789ABCDEF";

    if (*pos + 2U >= outLen) {
        return;
    }

    out[*pos] = hex[(value >> 4) & 0x0F];
    out[*pos + 1U] = hex[value & 0x0F];
    *pos += 2U;
    out[*pos] = '\0';
}

static void bytesToHex(const uint8_t *data, uint8_t len, char *out, size_t outLen)
{
    size_t pos = 0;
    uint8_t i;

    if (outLen == 0U) {
        return;
    }

    out[0] = '\0';
    for (i = 0; i < len; i++) {
        appendHexByte(out, outLen, &pos, data[i]);
    }
}

static bool isPrintablePayload(const uint8_t *data, uint8_t len)
{
    uint8_t i;

    for (i = 0; i < len; i++) {
        if (data[i] < 0x20U || data[i] > 0x7EU) {
            return false;
        }
    }
    return true;
}

static void emitRxPacket(const PacketInfo *packet)
{
    if (isPrintablePayload(packet->data, packet->len)) {
        char text[MAX_RF_PAYLOAD + 1U];

        memcpy(text, packet->data, packet->len);
        text[packet->len] = '\0';
        uartPrintf("+RX:%u,%d,%s\r\n", packet->len, packet->rssi, text);
    }
    else {
        char hex[(MAX_RF_PAYLOAD * 2U) + 1U];

        bytesToHex(packet->data, packet->len, hex, sizeof(hex));
        uartPrintf("+RXHEX:%u,%d,%s\r\n", packet->len, packet->rssi, hex);
    }
}

static void printConfig(void)
{
    uartPrintf("+CFG:FREQ=%lu,RATE=%lu,PWR=%d,MOD=2GFSK,SYNC=0x%08lX,ADDR=N/A,CHAN=N/A,RX=%s,SLEEP=%s,DEBUG=%s\r\n",
               (unsigned long)cfg.freqHz,
               (unsigned long)cfg.rateBps,
               cfg.pwrDbm,
               (unsigned long)cfg.syncWord,
               cfg.rxEnabled ? "ON" : "OFF",
               cfg.sleeping ? "YES" : "NO",
               cfg.debug ? "ON" : "OFF");
    sendOk();
}

static uint32_t random32(void)
{
    uint32_t x = randomState ^ (uint32_t)ClockP_getSystemTicks();

    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    randomState = x;
    return x;
}

static uint32_t uptimeSeconds(void)
{
    uint64_t ticks = ClockP_getSystemTicks64();
    uint64_t us = ticks * (uint64_t)ClockP_getSystemTickPeriod();

    return (uint32_t)(us / 1000000ULL);
}

static void printHelp(void)
{
    uartWriteRaw("+HELP:AT,AT?,AT+HELP,AT+CFG?,AT+DEFAULT,AT+RESET,AT+VERSION?\r\n");
    uartWriteRaw("+HELP:AT+DEBUG?,AT+DEBUG=ON,AT+DEBUG=OFF\r\n");
    uartWriteRaw("+HELP:AT+FREQ?,AT+FREQ=<Hz>,AT+PWR?,AT+PWR=<dBm>,AT+RATE?,AT+RATE=<bps>,AT+MOD?,AT+MOD=2GFSK\r\n");
    uartWriteRaw("+HELP:AT+SYNC?,AT+SYNC=<hex>,AT+ADDR?,AT+CHAN?\r\n");
    uartWriteRaw("+HELP:AT+RX=ON,AT+RX=OFF,AT+SEND=<text>,AT+SENDHEX=<hex>,AT+SLEEP,AT+WAKE\r\n");
    uartWriteRaw("+HELP:AT+RSSI?,AT+STATUS?,AT+LASTPKT?,AT+RANDOM?,AT+UPTIME?,AT+SETRADIO=FREQ,RATE,PWR,MOD,SYNC\r\n");
    sendOk();
}

static bool sendPacket(const uint8_t *data, uint8_t len)
{
    bool restartRx = rxCommandActive;
    RF_EventMask event;

    if (cfg.sleeping) {
        sendSleepingError();
        return false;
    }

    if (len == 0U || len > MAX_RF_PAYLOAD) {
        sendError("BAD_LEN");
        return false;
    }

    if (!radioOpen()) {
        sendError("RADIO_OPEN_FAILED");
        return false;
    }

    if (restartRx) {
        rxStop();
    }

    memcpy(txPacket, data, len);
    RF_cmdPropTx.pktLen = len;
    RF_cmdPropTx.syncWord = cfg.syncWord;

    rfSwitchTx();
    event = RF_runCmd(rfHandle, (RF_Op *)&RF_cmdPropTx, RF_PriorityNormal, NULL, 0);
    rfSwitchOff();

    if (restartRx || cfg.rxEnabled) {
        if (!rxStart()) {
            sendError("RX_START_FAILED");
            return false;
        }
    }

    if ((event & RF_EventLastCmdDone) == 0U) {
        sendError("TX_FAILED");
        return false;
    }

    txCount++;
    sendOk();
    return true;
}

static void processSetRadio(char *args)
{
    char *parts[5];
    char *token;
    uint8_t count = 0;
    ModemConfig next = cfg;
    uint32_t freq;
    uint32_t rate;
    int32_t pwr;
    uint32_t sync;
    char modUpper[16];

    token = strtok(args, ",");
    while (token != NULL && count < 5U) {
        parts[count++] = trim(token);
        token = strtok(NULL, ",");
    }

    if (count != 5U || token != NULL) {
        sendError("BAD_ARGS");
        return;
    }

    if (!parseUint32Strict(parts[0], &freq) ||
        !parseUint32Strict(parts[1], &rate) ||
        !parseInt32Strict(parts[2], &pwr) ||
        !parseHexWord(parts[4], &sync)) {
        sendError("BAD_ARGS");
        return;
    }

    toUpperCopy(modUpper, parts[3], sizeof(modUpper));
    if (strcmp(modUpper, "2GFSK") != 0) {
        sendError("BAD_MOD");
        return;
    }

    next.freqHz = freq;
    next.rateBps = rate;
    if (!validatePowerInput(pwr)) {
        sendError("BAD_PWR");
        return;
    }

    next.pwrDbm = (int8_t)pwr;
    next.syncWord = sync;

    if (applyConfig(&next)) {
        sendOk();
    }
}

static void processCommand(char *line)
{
    char upper[CMD_BUFFER_LEN];
    char *cmd = trim(line);

    if (*cmd == '\0') {
        return;
    }

    toUpperCopy(upper, cmd, sizeof(upper));

    if (strcmp(upper, "AT") == 0) {
        sendOk();
    }
    else if (strcmp(upper, "AT?") == 0) {
        uartPrintf("+ID:%s,%s,%s\r\n", FW_NAME, FW_VERSION, FW_SDK);
        sendOk();
    }
    else if (strcmp(upper, "AT+HELP") == 0) {
        printHelp();
    }
    else if (strcmp(upper, "AT+VERSION?") == 0) {
        uartWriteRaw("+VERSION:" FW_NAME "," FW_VERSION "," FW_SDK "\r\n");
        sendOk();
    }
    else if (strcmp(upper, "AT+CFG?") == 0) {
        printConfig();
    }
    else if (strcmp(upper, "AT+DEFAULT") == 0) {
        ModemConfig next;

        setDefaultConfig();
        next = cfg;
        if (applyConfig(&next)) {
            sendOk();
        }
    }
    else if (strcmp(upper, "AT+RESET") == 0) {
        resetModemState();
        sendOk();
    }
    else if (strcmp(upper, "AT+DEBUG?") == 0) {
        uartPrintf("+DEBUG:%s\r\n", cfg.debug ? "ON" : "OFF");
        sendOk();
    }
    else if (strcmp(upper, "AT+DEBUG=ON") == 0) {
        cfg.debug = true;
        sendOk();
    }
    else if (strcmp(upper, "AT+DEBUG=OFF") == 0) {
        cfg.debug = false;
        sendOk();
    }
    else if (strcmp(upper, "AT+FREQ?") == 0) {
        uartPrintf("+FREQ:%lu\r\n", (unsigned long)cfg.freqHz);
        sendOk();
    }
    else if (startsWith(upper, "AT+FREQ=")) {
        uint32_t value;
        ModemConfig next = cfg;

        if (!parseUint32Strict(cmd + strlen("AT+FREQ="), &value)) {
            sendError("BAD_FREQ");
            return;
        }
        next.freqHz = value;
        if (applyConfig(&next)) {
            sendOk();
        }
    }
    else if (strcmp(upper, "AT+PWR?") == 0) {
        uartPrintf("+PWR:%d\r\n", cfg.pwrDbm);
        sendOk();
    }
    else if (startsWith(upper, "AT+PWR=")) {
        int32_t value;
        ModemConfig next = cfg;

        if (!parseInt32Strict(cmd + strlen("AT+PWR="), &value)) {
            sendError("BAD_PWR");
            return;
        }
        if (!validatePowerInput(value)) {
            sendError("BAD_PWR");
            return;
        }
        next.pwrDbm = (int8_t)value;
        if (applyConfig(&next)) {
            sendOk();
        }
    }
    else if (strcmp(upper, "AT+RATE?") == 0) {
        uartPrintf("+RATE:%lu\r\n", (unsigned long)cfg.rateBps);
        sendOk();
    }
    else if (startsWith(upper, "AT+RATE=")) {
        uint32_t value;
        ModemConfig next = cfg;

        if (!parseUint32Strict(cmd + strlen("AT+RATE="), &value)) {
            sendError("BAD_RATE");
            return;
        }
        next.rateBps = value;
        if (applyConfig(&next)) {
            sendOk();
        }
    }
    else if (strcmp(upper, "AT+MOD?") == 0) {
        uartWriteRaw("+MOD:2GFSK\r\n");
        sendOk();
    }
    else if (strcmp(upper, "AT+MOD=2GFSK") == 0) {
        sendOk();
    }
    else if (startsWith(upper, "AT+MOD=")) {
        sendError("BAD_MOD");
    }
    else if (strcmp(upper, "AT+SYNC?") == 0) {
        uartPrintf("+SYNC:0x%08lX\r\n", (unsigned long)cfg.syncWord);
        sendOk();
    }
    else if (startsWith(upper, "AT+SYNC=")) {
        uint32_t value;
        ModemConfig next = cfg;

        if (!parseHexWord(cmd + strlen("AT+SYNC="), &value)) {
            sendError("BAD_SYNC");
            return;
        }
        next.syncWord = value;
        if (applyConfig(&next)) {
            sendOk();
        }
    }
    else if (strcmp(upper, "AT+ADDR?") == 0) {
        uartWriteRaw("+ADDR:N/A\r\n");
        sendOk();
    }
    else if (startsWith(upper, "AT+ADDR=")) {
        sendError("ADDR_NA");
    }
    else if (strcmp(upper, "AT+CHAN?") == 0) {
        uartWriteRaw("+CHAN:N/A\r\n");
        sendOk();
    }
    else if (startsWith(upper, "AT+CHAN=")) {
        sendError("CHAN_NA");
    }
    else if (strcmp(upper, "AT+RX=ON") == 0) {
        if (cfg.sleeping) {
            sendSleepingError();
            return;
        }
        cfg.rxEnabled = true;
        if (rxStart()) {
            sendOk();
        }
        else {
            sendError("RX_START_FAILED");
        }
    }
    else if (strcmp(upper, "AT+RX=OFF") == 0) {
        cfg.rxEnabled = false;
        rxStop();
        sendOk();
    }
    else if (startsWith(upper, "AT+SEND=")) {
        const char *payload = cmd + strlen("AT+SEND=");
        size_t len = strlen(payload);

        if (len == 0U || len > MAX_RF_PAYLOAD) {
            sendError("BAD_LEN");
            return;
        }
        sendPacket((const uint8_t *)payload, (uint8_t)len);
    }
    else if (startsWith(upper, "AT+SENDHEX=")) {
        uint8_t data[MAX_RF_PAYLOAD];
        uint8_t len;

        if (!parseHexPayload(cmd + strlen("AT+SENDHEX="), data, &len)) {
            sendError("BAD_HEX");
            return;
        }
        sendPacket(data, len);
    }
    else if (strcmp(upper, "AT+SLEEP") == 0) {
        cfg.sleeping = true;
        radioClose();
        sendOk();
        releaseAwakePowerConstraints();
    }
    else if (strcmp(upper, "AT+WAKE") == 0) {
        holdAwakePowerConstraints();
        cfg.sleeping = false;
        if (cfg.rxEnabled) {
            if (!rxStart()) {
                sendError("RX_START_FAILED");
                return;
            }
        }
        sendOk();
    }
    else if (strcmp(upper, "AT+RSSI?") == 0) {
        int8_t rssi = RF_GET_RSSI_ERROR_VAL;

        if (!cfg.sleeping && rfHandle != NULL) {
            rssi = RF_getRssi(rfHandle);
        }
        if (rssi == RF_GET_RSSI_ERROR_VAL) {
            uartWriteRaw("+RSSI:N/A\r\n");
        }
        else {
            uartPrintf("+RSSI:%d\r\n", rssi);
        }
        sendOk();
    }
    else if (strcmp(upper, "AT+STATUS?") == 0) {
        uartPrintf("+STATUS:SLEEP=%s,RX=%s,RF=%s,TXCNT=%lu,RXCNT=%lu,ERRCNT=%lu,UPTIME=%lu\r\n",
                   cfg.sleeping ? "YES" : "NO",
                   cfg.rxEnabled ? "ON" : "OFF",
                   rfHandle != NULL ? "OPEN" : "CLOSED",
                   (unsigned long)txCount,
                   (unsigned long)rxCount,
                   (unsigned long)errorCount,
                   (unsigned long)uptimeSeconds());
        sendOk();
    }
    else if (strcmp(upper, "AT+LASTPKT?") == 0) {
        if (!haveLastPacket) {
            uartWriteRaw("+LASTPKT:NONE\r\n");
        }
        else {
            char hex[(MAX_RF_PAYLOAD * 2U) + 1U];

            bytesToHex(lastPacket.data, lastPacket.len, hex, sizeof(hex));
            uartPrintf("+LASTPKT:%u,%d,%s\r\n", lastPacket.len, lastPacket.rssi, hex);
        }
        sendOk();
    }
    else if (strcmp(upper, "AT+RANDOM?") == 0) {
        uartPrintf("+RANDOM:0x%08lX\r\n", (unsigned long)random32());
        sendOk();
    }
    else if (strcmp(upper, "AT+UPTIME?") == 0) {
        uartPrintf("+UPTIME:%lu\r\n", (unsigned long)uptimeSeconds());
        sendOk();
    }
    else if (startsWith(upper, "AT+SETRADIO=")) {
        processSetRadio(cmd + strlen("AT+SETRADIO="));
    }
    else {
        sendError("UNKNOWN_CMD");
    }
}

static void rfRxCallback(RF_Handle h, RF_CmdHandle ch, RF_EventMask e)
{
    (void)h;
    (void)ch;

    if ((e & RF_EventRxEntryDone) != 0U) {
        rfc_dataEntryGeneral_t *entry = RFQueue_getDataEntry();
        uint8_t *raw = (uint8_t *)&entry->data;
        uint8_t len = raw[0];

        if (len <= MAX_RF_PAYLOAD && !rxPacketReady) {
            rxPacketPending.len = len;
            memcpy(rxPacketPending.data, &raw[1], len);
            rxPacketPending.rssi = (int8_t)raw[1U + len];
            rxPacketReady = true;
        }

        RFQueue_nextEntry();
    }
}

static void uartRxCallback(UART2_Handle handle, void *buffer, size_t count,
                           void *userArg, int_fast16_t status)
{
    uint8_t c;

    (void)handle;
    (void)buffer;
    (void)count;
    (void)userArg;

    if (status != UART2_STATUS_SUCCESS) {
        uartInputLen = 0;
        startUartRead();
        return;
    }

    c = uartRxByte;
    if (c == '\r' || c == '\n') {
        if (c == '\n' && ignoreNextLf) {
            ignoreNextLf = false;
            startUartRead();
            return;
        }

        ignoreNextLf = (c == '\r');

        if (uartDroppingLine) {
            uartDroppingLine = false;
            uartLineOverflow = true;
        }
        else if (uartInputLen > 0U && !uartLineReady) {
            if (!uartStartupSynced &&
                (uartInputLen < 2U ||
                 !isAtPrefixChar((uint8_t)uartInput[0]) ||
                 !isAtSecondChar((uint8_t)uartInput[1]))) {
                uartInputLen = 0;
                startUartRead();
                return;
            }

            memcpy(uartLine, uartInput, uartInputLen);
            uartLine[uartInputLen] = '\0';
            uartLineReady = true;
            uartStartupSynced = true;
        }
        uartInputLen = 0;
        startUartRead();
        return;
    }

    ignoreNextLf = false;

    if (uartDroppingLine) {
        startUartRead();
        return;
    }

    if (!uartStartupSynced) {
        if (uartInputLen == 0U) {
            if (!isAtPrefixChar(c)) {
                startUartRead();
                return;
            }
        }
        else if (uartInputLen == 1U && !isAtSecondChar(c)) {
            uartInputLen = 0;
            if (!isAtPrefixChar(c)) {
                startUartRead();
                return;
            }
        }
    }

    if (uartInputLen + 1U < sizeof(uartInput)) {
        uartInput[uartInputLen++] = (char)c;
    }
    else {
        uartInputLen = 0;
        uartDroppingLine = true;
    }

    startUartRead();
}

void *mainThread(void *arg0)
{
    UART2_Params uartParams;

    (void)arg0;

    setDefaultConfig();
    holdAwakePowerConstraints();
    rfSwitchInit();

    if (RFQueue_defineQueue(&dataQueue,
                            rxDataEntryBuffer,
                            sizeof(rxDataEntryBuffer),
                            NUM_DATA_ENTRIES,
                            MAX_RF_PAYLOAD + RX_APPENDED_BYTES) != 0U) {
        while (1) {
        }
    }

    configureRadioCommands();

    UART2_Params_init(&uartParams);
    uartParams.baudRate = UART_BAUD;
    uartParams.readMode = UART2_Mode_CALLBACK;
    uartParams.readCallback = uartRxCallback;
    uartParams.readReturnMode = UART2_ReadReturnMode_FULL;

    uartHandle = UART2_open(CONFIG_UART2_0, &uartParams);
    if (uartHandle == NULL) {
        while (1) {
        }
    }

    startUartRead();

    while (1) {
        if (uartLineOverflow) {
            uartLineOverflow = false;
            sendError("LINE_TOO_LONG");
        }

        if (uartLineReady) {
            char line[CMD_BUFFER_LEN];

            strcpy(line, uartLine);
            uartLineReady = false;
            processCommand(line);
        }

        if (rxPacketReady) {
            PacketInfo packet;

            packet = rxPacketPending;
            rxPacketReady = false;
            lastPacket = packet;
            haveLastPacket = true;
            rxCount++;
            emitRxPacket(&packet);
        }

        usleep(1000);
    }
}
