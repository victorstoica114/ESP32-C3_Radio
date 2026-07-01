#define RADIO_CC1101_V1_433       1101433
#define RADIO_CC1101_V2_868       1102868
#define RADIO_HC12                1212
#define RADIO_NRF24L01            2401
#define RADIO_RA01_SX1278         11278
#define RADIO_RA01H_SX1276        11276
#define RADIO_RA01SH_SX1262       11262
#define RADIO_RA02_SX1278         21278
#define RADIO_E28_SX1280          281280
#define RADIO_EBYTE               3232
#define RADIO_EBYTE_E22_SX1268    223268
#define RADIO_EBYTE_E280_SX1280   2801280
#define RADIO_EBYTE_E79_CC1352P   791352
#define RADIO_EBYTE_E07_400M10S   740010
#define RADIO_EBYTE_E07_400MM10S  740011
#define RADIO_EBYTE_E07_433M20S   743320
#define RADIO_XL1276_D01_SX1276   127601

#define AT_COMMANDS          1
#define BIDIRECTIONAL_RX_TX  2
#define RECEIVE              3
#define SETTINGS             4
#define TRANSMIT             5
#define BRIDGE               6

#if RADIO_MODULE == RADIO_CC1101_V1_433
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "CC1101/AT-Commands CC1101.cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "CC1101/Bidirectional RX-TX CC1101.cpp"
  #elif RADIO_PROGRAM == RECEIVE
    #include "CC1101/Receive.cpp"
  #elif RADIO_PROGRAM == SETTINGS
    #include "CC1101/Settings.cpp"
  #elif RADIO_PROGRAM == TRANSMIT
    #include "CC1101/Transmit.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for CC1101_V1_433. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX, RECEIVE, SETTINGS, TRANSMIT."
  #endif
#elif RADIO_MODULE == RADIO_CC1101_V2_868
  #if RADIO_PROGRAM == AT_COMMANDS
    #define CC1101_MODULE_NAME "CC1101 868 MHz"
    #define CC1101_DISPLAY_LINE1 "RADIO"
    #define CC1101_DISPLAY_LINE2 "868MHz"
    #define CC1101_HELP_TITLE "AT Shell for CC1101 868 MHz Radio Module"
    #define CC1101_CONFIG_TITLE "====== CC1101 868 MHz CONFIGURATION ======"
    #define CC1101_BOOT_TITLE "CC1101 868 MHz AT Bridge"
    #define CC1101_BOOT_SUBTITLE "115200 8N1 <-> 868 MHz Radio"
    #define CC1101_DEF_FREQUENCY_MHZ 868.0f
    #define CC1101_NOMINAL_TX_POWER_DBM 10
    #define CC1101_EEPROM_MAGIC 0x43438681UL
    #include "CC1101/AT-Commands CC1101.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for CC1101_V2_868. Available: AT_COMMANDS."
  #endif
#elif RADIO_MODULE == RADIO_HC12
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "HC-12/AT-Commands HC-12.cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "HC-12/Bidirectional RX-TX HC-12.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for HC12. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX."
  #endif
#elif RADIO_MODULE == RADIO_NRF24L01
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "NRF24L01/AT-Commands NRF24L01.cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "NRF24L01/Bidirectional RX-TX NRF24L01.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for NRF24L01. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX."
  #endif
#elif RADIO_MODULE == RADIO_RA01_SX1278
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "RA-01(SX1278)/AT-Commands RA01(SX1278).cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "RA-01(SX1278)/Bidirectional RX-TX RA01(SX1278).cpp"
  #elif RADIO_PROGRAM == SETTINGS
    #include "RA-01(SX1278)/Settings_RA-01(SX1278).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for RA01_SX1278. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX, SETTINGS."
  #endif
#elif RADIO_MODULE == RADIO_RA01H_SX1276
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "RA-01H(SX1276)/AT-Commands RA-01H(SX1276).cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "RA-01H(SX1276)/Bidirectional RX-TX RA01H(SX1276).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for RA01H_SX1276. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX."
  #endif
#elif RADIO_MODULE == RADIO_RA01SH_SX1262
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "RA-01SH(SX1262)/AT-Commands RA-01SH(SX1262).cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "RA-01SH(SX1262)/Bidirectional RX-TX RA01(SX1262).cpp"
  #elif RADIO_PROGRAM == SETTINGS
    #include "RA-01SH(SX1262)/Settings_RA-01SH(SX1262).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for RA01SH_SX1262. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX, SETTINGS."
  #endif
#elif RADIO_MODULE == RADIO_RA02_SX1278
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "RA-02(SX1278)/AT-Commands RA01(SX1278).cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "RA-02(SX1278)/Bidirectional RX-TX RA01(SX1278).cpp"
  #elif RADIO_PROGRAM == SETTINGS
    #include "RA-02(SX1278)/Settings_RA-01(SX1278).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for RA02_SX1278. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX, SETTINGS."
  #endif
#elif RADIO_MODULE == RADIO_E28_SX1280
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "E28(SX1280)/AT-Commands E28(SX1280).cpp"
  #elif RADIO_PROGRAM == BIDIRECTIONAL_RX_TX
    #include "E28(SX1280)/Bidirectional RX-TX E28(SX1280).cpp"
  #elif RADIO_PROGRAM == SETTINGS
    #include "E28(SX1280)/Settings_E28(SX1280).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for E28_SX1280. Available: AT_COMMANDS, BIDIRECTIONAL_RX_TX, SETTINGS."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "Ebyte/AT-Commands Ebyte E32.cpp"
  #elif RADIO_PROGRAM == BRIDGE
    #include "Ebyte/Ebyte.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE. Available: AT_COMMANDS, BRIDGE."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE_E22_SX1268
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "Ebyte E22(SX1268)/AT-Commands Ebyte E22(SX1268).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE_E22_SX1268. Available: AT_COMMANDS."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE_E280_SX1280
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "Ebyte E280(SX1280)/AT-Commands Ebyte E280(SX1280).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE_E280_SX1280. Available: AT_COMMANDS."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE_E79_CC1352P
  #if RADIO_PROGRAM == AT_COMMANDS || RADIO_PROGRAM == BRIDGE
    #include "Ebyte E79(CC1352P)/ESP32 Bridge/ESP32 Bridge Ebyte E79(CC1352P).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE_E79_CC1352P. Available: AT_COMMANDS, BRIDGE."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE_E07_400M10S
  #if RADIO_PROGRAM == AT_COMMANDS
    #define CC1101_MODULE_NAME "Ebyte E07-400M10S"
    #define CC1101_DISPLAY_LINE1 "RADIO"
    #define CC1101_DISPLAY_LINE2 "E07 10"
    #define CC1101_HELP_TITLE "AT Shell for Ebyte E07-400M10S (CC1101)"
    #define CC1101_CONFIG_TITLE "====== E07-400M10S CONFIGURATION ======"
    #define CC1101_BOOT_TITLE "E07-400M10S AT Bridge"
    #define CC1101_NOMINAL_TX_POWER_DBM 10
    #define CC1101_EEPROM_MAGIC 0x45303731UL
    #include "CC1101/AT-Commands CC1101.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE_E07_400M10S. Available: AT_COMMANDS."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE_E07_400MM10S
  #if RADIO_PROGRAM == AT_COMMANDS
    #define CC1101_MODULE_NAME "Ebyte E07-400MM10S"
    #define CC1101_DISPLAY_LINE1 "RADIO"
    #define CC1101_DISPLAY_LINE2 "E07 MM"
    #define CC1101_HELP_TITLE "AT Shell for Ebyte E07-400MM10S (CC1101)"
    #define CC1101_CONFIG_TITLE "====== E07-400MM10S CONFIGURATION ======"
    #define CC1101_BOOT_TITLE "E07-400MM10S AT Bridge"
    #define CC1101_NOMINAL_TX_POWER_DBM 10
    #define CC1101_EEPROM_MAGIC 0x45303732UL
    #include "CC1101/AT-Commands CC1101.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE_E07_400MM10S. Available: AT_COMMANDS."
  #endif
#elif RADIO_MODULE == RADIO_EBYTE_E07_433M20S
  #if RADIO_PROGRAM == AT_COMMANDS
    #define CC1101_MODULE_NAME "Ebyte E07-433M20S"
    #define CC1101_DISPLAY_LINE1 "RADIO"
    #define CC1101_DISPLAY_LINE2 "E07 20"
    #define CC1101_HELP_TITLE "AT Shell for Ebyte E07-433M20S (CC1101 + PA/LNA)"
    #define CC1101_CONFIG_TITLE "====== E07-433M20S CONFIGURATION ======"
    #define CC1101_BOOT_TITLE "E07-433M20S AT Bridge"
    #define CC1101_NOMINAL_TX_POWER_DBM 20
    #define CC1101_EEPROM_MAGIC 0x45303733UL
    #include "CC1101/AT-Commands CC1101.cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for EBYTE_E07_433M20S. Available: AT_COMMANDS."
  #endif
#elif RADIO_MODULE == RADIO_XL1276_D01_SX1276
  #if RADIO_PROGRAM == AT_COMMANDS
    #include "XL1276-D01 (SX1276)/AT-Commands_XL1276-D01(SX1276).cpp"
  #elif RADIO_PROGRAM == RECEIVE
    #include "XL1276-D01 (SX1276)/receiver_XL1276-D01(SX1276).cpp"
  #elif RADIO_PROGRAM == SETTINGS
    #include "XL1276-D01 (SX1276)/Settings_XL1276-D01(SX1276).cpp"
  #elif RADIO_PROGRAM == TRANSMIT
    #include "XL1276-D01 (SX1276)/transmiter_XL1276-D01(SX1276).cpp"
  #else
    #error "Selected RADIO_PROGRAM is not available for XL1276_D01_SX1276. Available: AT_COMMANDS, RECEIVE, SETTINGS, TRANSMIT."
  #endif
#else
  #error "Selected RADIO_MODULE is not available. Available: RADIO_CC1101_V1_433, RADIO_CC1101_V2_868, RADIO_HC12, RADIO_NRF24L01, RADIO_RA01_SX1278, RADIO_RA01H_SX1276, RADIO_RA01SH_SX1262, RADIO_RA02_SX1278, RADIO_E28_SX1280, RADIO_EBYTE, RADIO_EBYTE_E22_SX1268, RADIO_EBYTE_E280_SX1280, RADIO_EBYTE_E79_CC1352P, RADIO_EBYTE_E07_400M10S, RADIO_EBYTE_E07_400MM10S, RADIO_EBYTE_E07_433M20S, RADIO_XL1276_D01_SX1276."
#endif
