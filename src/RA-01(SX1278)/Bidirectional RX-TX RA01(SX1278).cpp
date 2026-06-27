#include <Arduino.h>
#include <RadioLib.h>

// SX1278 connections:
// NSS pin:   7
// DIO0 pin:  3
// RESET pin: 10
// DIO1 pin:  1
SX1278 radio = new Module(7, 3, 10, 1);

// flag pentru pachet recepționat
volatile bool receivedFlag = false;

// timer pentru trimitere periodică
unsigned long lastTxTime = 0;
const unsigned long TX_PERIOD_MS = 1000;

// contor pachete trimise
int packetCount = 0;

// callback pentru RX (DIO0)
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

void setup() {
  Serial.begin(9600);
  delay(100);

  Serial.print(F("[SX1278] Initializing ... "));
  int state = radio.begin();
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // setăm acțiunea pentru pachet recepționat
  radio.setPacketReceivedAction(onRxDone);

  // pornim în modul de recepție
  Serial.print(F("[SX1278] Starting to listen ... "));
  state = radio.startReceive();
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  lastTxTime = millis();
}

void loop() {
  unsigned long now = millis();

  // -------------------------------------------------
  // 1) Transmitere pachet la fiecare 1 secundă
  // -------------------------------------------------
  if (now - lastTxTime >= TX_PERIOD_MS) {
    lastTxTime = now;

    // pregătim mesajul
    String msg = "Hello World! #" + String(packetCount++);

    Serial.print(F("[SX1278] TX -> "));
    Serial.println(msg);

    // transmitem blocant (functie transmit)
    int state = radio.transmit(msg);

    if (state == RADIOLIB_ERR_NONE) {
      Serial.println(F("[SX1278] TX OK"));
    } else {
      Serial.print(F("[SX1278] TX failed, code "));
      Serial.println(state);
    }

    // revenim în modul RX pentru a asculta pachete
    state = radio.startReceive();
    if (state != RADIOLIB_ERR_NONE) {
      Serial.print(F("[SX1278] Failed to restart RX, code "));
      Serial.println(state);
    }
  }

  // -------------------------------------------------
  // 2) Tratare pachet recepționat
  // -------------------------------------------------
  if (receivedFlag) {
    receivedFlag = false;

    String str;
    int state = radio.readData(str);

    if (state == RADIOLIB_ERR_NONE) {
      Serial.println(F("[SX1278] Packet received!"));

      Serial.print(F("[SX1278] Data:\t\t"));
      Serial.println(str);

      Serial.print(F("[SX1278] RSSI:\t\t"));
      Serial.print(radio.getRSSI());
      Serial.println(F(" dBm"));

      Serial.print(F("[SX1278] SNR:\t\t"));
      Serial.print(radio.getSNR());
      Serial.println(F(" dB"));

      Serial.print(F("[SX1278] Frequency Error:\t"));
      Serial.print(radio.getFrequencyError());
      Serial.println(F(" Hz"));

    } else if (state == RADIOLIB_ERR_CRC_MISMATCH) {
      Serial.println(F("[SX1278] CRC error on received packet!"));

    } else {
      Serial.print(F("[SX1278] RX failed, code "));
      Serial.println(state);
    }

    // ne asigurăm că rămânem în modul RX
    radio.startReceive();
  }

  // buclă lejeră
  delay(1);
}
