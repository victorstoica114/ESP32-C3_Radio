#include <RadioLib.h>
#include <Arduino.h>

// SX1276 has the following connections:
// NSS pin:   7
// DIO0 pin:  3
// RESET pin: 10
// DIO1 pin:  1
SX1276 radio = new Module(7, 3, 10, 1);

void setup() {
  Serial.begin(9600);
  delay(5000);
  Serial.println("Hello World!");
  // initialize SX1276 with default settings
  Serial.print(F("[SX1276] Initializing ... "));
  int state = radio.begin();
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  state = radio.begin(433.5, 500.0, 6, 5, 0x34, 2, 20, 1);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // you can also change the settings at runtime
  // and check if the configuration was changed successfully

  // set carrier frequency to 433.5 MHz
  if (radio.setFrequency(433.5) == RADIOLIB_ERR_INVALID_FREQUENCY) {
    Serial.println(F("Selected frequency is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set bandwidth to 250 kHz
  if (radio.setBandwidth(250.0) == RADIOLIB_ERR_INVALID_BANDWIDTH) {
    Serial.println(F("Selected bandwidth is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set spreading factor to 10
  if (radio.setSpreadingFactor(10) == RADIOLIB_ERR_INVALID_SPREADING_FACTOR) {
    Serial.println(F("Selected spreading factor is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set coding rate to 6
  if (radio.setCodingRate(6) == RADIOLIB_ERR_INVALID_CODING_RATE) {
    Serial.println(F("Selected coding rate is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set LoRa sync word to 0x14
  // NOTE: value 0x34 is reserved for LoRaWAN networks and should not be used
  if (radio.setSyncWord(0x14) != RADIOLIB_ERR_NONE) {
    Serial.println(F("Unable to set sync word!"));
    while (true) { delay(10); }
  }

  // set output power to 10 dBm (accepted range is -3 - 17 dBm)
  // NOTE: 20 dBm value allows high power operation, but transmission
  //       duty cycle MUST NOT exceed 1%
  if (radio.setOutputPower(10) == RADIOLIB_ERR_INVALID_OUTPUT_POWER) {
    Serial.println(F("Selected output power is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set over current protection limit to 80 mA (accepted range is 45 - 240 mA)
  // NOTE: set value to 0 to disable overcurrent protection
  if (radio.setCurrentLimit(80) == RADIOLIB_ERR_INVALID_CURRENT_LIMIT) {
    Serial.println(F("Selected current limit is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set LoRa preamble length to 15 symbols (accepted range is 6 - 65535)
  if (radio.setPreambleLength(15) == RADIOLIB_ERR_INVALID_PREAMBLE_LENGTH) {
    Serial.println(F("Selected preamble length is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set amplifier gain to 1 (accepted range is 1 - 6, where 1 is maximum gain)
  // NOTE: set value to 0 to enable automatic gain control
  //       leave at 0 unless you know what you're doing
  if (radio.setGain(1) == RADIOLIB_ERR_INVALID_GAIN) {
    Serial.println(F("Selected gain is invalid for this module!"));
    while (true) { delay(10); }
  }

  Serial.println(F("All settings successfully changed!"));
}

void loop() {
  // nothing here
}