// Select what firmware variant PlatformIO should build.
//
// Step 1: choose the radio module.
// Step 2: choose the program/sketch for that module.
//
// RADIO_MODULE options:
//   RADIO_CC1101
//   RADIO_HC12
//   RADIO_NRF24L01
//   RADIO_RA01_SX1278
//   RADIO_RA01H_SX1276
//   RADIO_RA01SH_SX1262
//   RADIO_RA02_SX1278
//   RADIO_E28_SX1280
//   RADIO_EBYTE
//   RADIO_EBYTE_E22_SX1268
//   RADIO_EBYTE_E280_SX1280
//   RADIO_EBYTE_E79_CC1352P
//   RADIO_XL1276_D01_SX1276
//
// RADIO_PROGRAM options:
//   AT_COMMANDS
//   BIDIRECTIONAL_RX_TX
//   RECEIVE
//   SETTINGS
//   TRANSMIT
//   BRIDGE

// Change these two defines when switching what you want to test.
#ifndef RADIO_MODULE
#define RADIO_MODULE  RADIO_EBYTE_E79_CC1352P
#endif

#ifndef RADIO_PROGRAM
#define RADIO_PROGRAM AT_COMMANDS
#endif

// Keep this after RADIO_MODULE/RADIO_PROGRAM; it uses those selections.
#include "module_selection.h"
