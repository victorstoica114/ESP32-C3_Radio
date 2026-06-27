#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

#define NSS     7
#define DIO1    3
#define RESET   10
#define BUSY    1

SX1262 radio = new Module(NSS, DIO1, RESET, BUSY);

static void die(int state) {
  Serial.print(F("FAILED, code "));
  Serial.println(state);
  while (true) { delay(10); }
}

static void okOrDie(const __FlashStringHelper* label, int st) {
  Serial.print(label);
  if (st == RADIOLIB_ERR_NONE) {
    Serial.println(F("OK"));
  } else {
    Serial.println(st);
    die(st);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n=== SX1262 Settings (your pinout) ==="));

  SPI.begin(4, 5, 6, 7);

  Serial.print(F("[SX1262] Initializing ... "));
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 14, 8, 0, 1.8);
  if (state != RADIOLIB_ERR_NONE) die(state);
  Serial.println(F("OK"));

  okOrDie(F("[setFrequency] 868.3 MHz ... "),        radio.setFrequency(868.3));
  okOrDie(F("[setBandwidth] 250.0 kHz ... "),        radio.setBandwidth(250.0));
  okOrDie(F("[setSpreadingFactor] SF10 ... "),       radio.setSpreadingFactor(10));
  okOrDie(F("[setCodingRate] 4/6 ... "),             radio.setCodingRate(6));
  okOrDie(F("[setSyncWord] 0x34 ... "),              radio.setSyncWord(0x34));
  okOrDie(F("[setOutputPower] 14 dBm ... "),         radio.setOutputPower(14));
  okOrDie(F("[setCurrentLimit] 80 mA ... "),         radio.setCurrentLimit(80));
  okOrDie(F("[setPreambleLength] 15 ... "),          radio.setPreambleLength(15));
  okOrDie(F("[setCRC] enable ... "),                 radio.setCRC(true));

  Serial.println(F("\nAll settings successfully changed!"));

  radio.standby();
  delay(5);

  Serial.print(F("[TX TEST] "));
  state = radio.transmit("Settings OK!");
  Serial.println(state == RADIOLIB_ERR_NONE ? F("SUCCESS") : String(state));
}

void loop() {
  // nothing
}
