// include the library
#include <RadioLib.h>
#include<Arduino.h>

// SX1280 has the following connections:
// NSS pin:   7
// DIO1 pin:  1
// NRST pin:  10
// BUSY pin:  3
SX1280 radio = new Module(7, 1, 10, 3);

void setup() {
  Serial.begin(9600);
  delay(5000);
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

  // initialize the second LoRa instance with
  // non-default settings
  // this LoRa link will have high data rate,
  // but lower range
  Serial.print(F("[SX1280] Initializing ... "));
  // carrier frequency:           2450.0 MHz
  // bandwidth:                   1625.0 kHz
  // spreading factor:            7
  // coding rate:                 5
  // sync word:                   0x12 (private network)
  // output power:                2 dBm
  // preamble length:             20 symbols
  state = radio.begin(2450.0, 1625.0, 7, 5, 0x12, 2, 20);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // you can also change the settings at runtime
  // and check if the configuration was changed successfully

  // set carrier frequency to 2410.5 MHz
  if (radio.setFrequency(2410.5) == RADIOLIB_ERR_INVALID_FREQUENCY) {
    Serial.println(F("Selected frequency is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set bandwidth to 203.125 kHz
  if (radio.setBandwidth(203.125) == RADIOLIB_ERR_INVALID_BANDWIDTH) {
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

  // set output power to -2 dBm
  if (radio.setOutputPower(-2) == RADIOLIB_ERR_INVALID_OUTPUT_POWER) {
    Serial.println(F("Selected output power is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set LoRa preamble length to 16 symbols (accepted range is 2 - 65535)
  if (radio.setPreambleLength(16) == RADIOLIB_ERR_INVALID_PREAMBLE_LENGTH) {
    Serial.println(F("Selected preamble length is invalid for this module!"));
    while (true) { delay(10); }
  }

  // disable CRC
  if (radio.setCRC(false) == RADIOLIB_ERR_INVALID_CRC_CONFIGURATION) {
    Serial.println(F("Selected CRC is invalid for this module!"));
    while (true) { delay(10); }
  }

  Serial.println(F("All settings succesfully changed!"));
}

void loop() {
  // nothing here
}
