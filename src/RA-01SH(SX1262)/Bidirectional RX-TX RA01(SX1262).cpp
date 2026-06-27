#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

#define NSS     7
#define DIO1    1
#define RESET   10
#define BUSY    3

SX1262 radio = new Module(NSS, DIO1, RESET, BUSY);

volatile bool receivedFlag = false;

unsigned long lastTxTime = 0;
const unsigned long TX_PERIOD_MS = 1000;
int packetCount = 0;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onRxDone(void) {
  receivedFlag = true;
}

static void die(int st) {
  Serial.print(F("FAILED, code "));
  Serial.println(st);
  while (true) delay(10);
}

void setup() {
  Serial.begin(9600);
  delay(300);

  SPI.begin(4, 5, 6, 7);

  Serial.print(F("[SX1262] Initializing ... "));
  int st = radio.begin(868.0, 125.0, 9, 7, 0x12, 14, 8, 0, 1.8);
  if (st != RADIOLIB_ERR_NONE) die(st);
  Serial.println(F("success!"));

  // callback RX
  radio.setPacketReceivedAction(onRxDone);

  Serial.print(F("[SX1262] Starting to listen ... "));
  st = radio.startReceive();
  if (st != RADIOLIB_ERR_NONE) die(st);
  Serial.println(F("success!"));

  delay(5);
  lastTxTime = millis();
}

void loop() {
  unsigned long now = millis();

  // 1) TX periodic
  if (now - lastTxTime >= TX_PERIOD_MS) {
    lastTxTime = now;

    String msg = "Hello World! #" + String(packetCount++);

    Serial.print(F("[SX1262] TX -> "));
    Serial.println(msg);

    // IMPORTANT: oprește RX înainte de TX (evită stări intermediare)
    radio.standby();
    delay(2);

    int st = radio.transmit(msg);

    if (st == RADIOLIB_ERR_NONE) {
      Serial.println(F("[SX1262] TX OK"));
    } else {
      Serial.print(F("[SX1262] TX failed, code "));
      Serial.println(st);
    }

    // revino în RX + guard time
    st = radio.startReceive();
    if (st != RADIOLIB_ERR_NONE) {
      Serial.print(F("[SX1262] Failed to restart RX, code "));
      Serial.println(st);
    }
    delay(10); // guard time mai mare (ajută pe C3 + wiring)
  }

  // 2) RX handling
  if (receivedFlag) {
    receivedFlag = false;

    String str;
    int st = radio.readData(str);

    // Filtru simplu pentru “pachet gol”:
    if (st == RADIOLIB_ERR_NONE && str.length() == 0) {
      // cel mai des e un eveniment rezidual; rearm RX și ieși
      radio.startReceive();
      return;
    }

    if (st == RADIOLIB_ERR_NONE) {
      Serial.println(F("[SX1262] Packet received!"));

      Serial.print(F("[SX1262] Data:\t\t"));
      Serial.println(str);

      Serial.print(F("[SX1262] RSSI:\t\t"));
      Serial.print(radio.getRSSI());
      Serial.println(F(" dBm"));

      Serial.print(F("[SX1262] SNR:\t\t"));
      Serial.print(radio.getSNR());
      Serial.println(F(" dB"));

      Serial.print(F("[SX1262] Freq Err:\t"));
      Serial.print(radio.getFrequencyError());
      Serial.println(F(" Hz"));

    } else if (st == RADIOLIB_ERR_CRC_MISMATCH) {
      Serial.println(F("[SX1262] CRC error on received packet!"));
    } else {
      Serial.print(F("[SX1262] RX failed, code "));
      Serial.println(st);
    }

    radio.startReceive();
  }
}
