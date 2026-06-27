
// include the library
#include <RadioLib.h>

// CC1101 has the following connections:
// CS pin:    7
// GDO0 pin:  10
// RST pin:   unused
// GDO2 pin:  3 (optional)
CC1101 radio = new Module(7, 10, RADIOLIB_NC, 3);


void setup() {
  Serial.begin(9600);
  delay(5000);
  Serial.println("Hello World!");
  // initialize CC1101 with default settings
  Serial.print(F("[CC1101] Initializing ... "));
  int state = radio.begin();
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println(F("success!"));
  } else {
    Serial.print(F("failed, code "));
    Serial.println(state);
    while (true) { delay(10); }
  }

  // initialize CC1101 with non-default settings
  Serial.print(F("[CC1101] Initializing ... "));
  // carrier frequency:                   434.0 MHz
  // bit rate:                            32.0 kbps
  // frequency deviation:                 60.0 kHz
  // Rx bandwidth:                        250.0 kHz
  // output power:                        7 dBm
  // preamble length:                     32 bits
  state = radio.begin(434.0, 32.0, 60.0, 250.0, 7, 32);
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
    Serial.println(F("[CC1101] Selected frequency is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set bit rate to 100.0 kbps
  state = radio.setBitRate(100.0);
  if (state == RADIOLIB_ERR_INVALID_BIT_RATE) {
    Serial.println(F("[CC1101] Selected bit rate is invalid for this module!"));
    while (true) { delay(10); }
  } else if (state == RADIOLIB_ERR_INVALID_BIT_RATE_BW_RATIO) {
    Serial.println(F("[CC1101] Selected bit rate to bandwidth ratio is invalid!"));
    Serial.println(F("[CC1101] Increase receiver bandwidth to set this bit rate."));
    while (true) { delay(10); }
  }

  // set receiver bandwidth to 250.0 kHz
  if (radio.setRxBandwidth(250.0) == RADIOLIB_ERR_INVALID_RX_BANDWIDTH) {
    Serial.println(F("[CC1101] Selected receiver bandwidth is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set allowed frequency deviation to 10.0 kHz
  if (radio.setFrequencyDeviation(10.0) == RADIOLIB_ERR_INVALID_FREQUENCY_DEVIATION) {
    Serial.println(F("[CC1101] Selected frequency deviation is invalid for this module!"));
    while (true) { delay(10); }
  }

  // set output power to 5 dBm
  if (radio.setOutputPower(5) == RADIOLIB_ERR_INVALID_OUTPUT_POWER) {
    Serial.println(F("[CC1101] Selected output power is invalid for this module!"));
    while (true) { delay(10); }
  }

  // 2 bytes can be set as sync word
  if (radio.setSyncWord(0x01, 0x23) == RADIOLIB_ERR_INVALID_SYNC_WORD) {
    Serial.println(F("[CC1101] Selected sync word is invalid for this module!"));
    while (true) { delay(10); }
  }

}

void loop() {
  // nothing here
}