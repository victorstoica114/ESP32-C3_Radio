#include <Arduino.h>
#include <RadioLib.h>

// nRF24 connections:
// CS pin:    7
// IRQ pin:   3
// CE pin:    10
nRF24 radio = new Module(7, 3, 10);

// flag pentru pachet recepționat
volatile bool receivedFlag = false;

// timer pentru trimitere periodică
unsigned long lastTxTime = 0;
const unsigned long TX_PERIOD_MS = 1000;

// contor pachete trimise
int packetCount = 0;

// callback pentru RX (se apelează când e disponibil un pachet)
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

void setup() {
  Serial.begin(9600);
  delay(100);

  // inițializare nRF24
  Serial.print(F("[nRF24] Initializing ... "));
  int state = radio.begin();
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // adresa comună TX/RX (5 bytes, implicit în RadioLib)
  byte addr[] = {0x01, 0x23, 0x45, 0x67, 0x89};

  // setăm pipe-ul de transmisie
  Serial.print(F("[nRF24] Setting transmit pipe ... "));
  state = radio.setTransmitPipe(addr);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // setăm pipe-ul de recepție 0 (aceeași adresă)
  Serial.print(F("[nRF24] Setting receive pipe 0 ... "));
  state = radio.setReceivePipe(0, addr);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // callback pentru pachet recepționat
  radio.setPacketReceivedAction(onRxDone);

  // pornim în modul RX
  Serial.print(F("[nRF24] Starting to listen ... "));
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

    String msg = "Hello World! #" + String(packetCount++);

    Serial.print(F("[nRF24] TX -> "));
    Serial.println(msg);

    // transmit blocant
    int state = radio.transmit(msg);

    if (state == RADIOLIB_ERR_NONE) {
      Serial.println(F("[nRF24] TX OK"));
    } else {
      Serial.print(F("[nRF24] TX failed, code "));
      Serial.println(state);
    }

    // revenim în RX
    state = radio.startReceive();
    if (state != RADIOLIB_ERR_NONE) {
      Serial.print(F("[nRF24] Failed to restart RX, code "));
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
      Serial.println(F("[nRF24] Packet received!"));
      Serial.print(F("[nRF24] Data:\t\t"));
      Serial.println(str);
    } else {
      Serial.print(F("[nRF24] RX failed, code "));
      Serial.println(state);
    }

    // rămânem în modul de ascultare
    radio.startReceive();
  }

  delay(1);
}
