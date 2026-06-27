// include the library
#include <RadioLib.h>
#include <Arduino.h>

// SX1280 connections:
// NSS pin:   7
// DIO1 pin:  1
// NRST pin:  10
// BUSY pin:  3
SX1280 radio = new Module(7, 1, 10, 3);

// flag pentru pachet recepționat
volatile bool receivedFlag = false;

// timer pentru trimitere periodică
unsigned long lastTxTime = 0;
const unsigned long TX_PERIOD_MS = 1000;

// contor pachete trimise
int packetCount = 0;

// ISR pentru RX (se apelează când e disponibil un pachet)
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

void setup() {
  Serial.begin(9600);
  delay(5000);      // păstrat din codul tău
  Serial.println("Hello world");

  // initialize SX1280 with default settings
  Serial.print(F("[SX1280] Initializing ... "));
  int state = radio.begin();
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // setăm funcția apelată când se primește un pachet
  radio.setPacketReceivedAction(onRxDone);

  // pornim în modul recepție
  Serial.print(F("[SX1280] Starting to listen ... "));
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

    // mesajul de trimis
    String msg = "Hello World! #" + String(packetCount++);

    Serial.print(F("[SX1280] TX -> "));
    Serial.println(msg);

    // transmit blocant
    int state = radio.transmit(msg);

    if (state == RADIOLIB_ERR_NONE) {
      Serial.println(F("[SX1280] TX OK"));
    } else {
      Serial.print(F("[SX1280] TX failed, code "));
      Serial.println(state);
    }

    // revenim în modul RX
    state = radio.startReceive();
    if (state != RADIOLIB_ERR_NONE) {
      Serial.print(F("[SX1280] Failed to restart RX, code "));
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
      // packet was successfully received
      Serial.println(F("[SX1280] Received packet!"));

      // print data of the packet
      Serial.print(F("[SX1280] Data:\t\t"));
      Serial.println(str);

      // print RSSI (Received Signal Strength Indicator)
      Serial.print(F("[SX1280] RSSI:\t\t"));
      Serial.print(radio.getRSSI());
      Serial.println(F(" dBm"));

      // print SNR (Signal-to-Noise Ratio)
      Serial.print(F("[SX1280] SNR:\t\t"));
      Serial.print(radio.getSNR());
      Serial.println(F(" dB"));

      // print the Frequency Error
      Serial.print(F("[SX1280] Frequency Error:\t"));
      Serial.print(radio.getFrequencyError());
      Serial.println(F(" Hz"));

    } else if (state == RADIOLIB_ERR_CRC_MISMATCH) {
      Serial.println(F("[SX1280] CRC error!"));
    } else {
      Serial.print(F("[SX1280] RX failed, code "));
      Serial.println(state);
    }

    // rămânem în listen
    radio.startReceive();
  }
}
