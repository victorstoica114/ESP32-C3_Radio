#include <Arduino.h>
#include <RadioLib.h>

/*
  Test CC1101 modules with ESP32-C3 using RadioLib - VERSIUNE IMBUNATATITA
  
  Conexiuni CC1101 -> ESP32-C3:
  - VCC  -> 3.3V
  - GND  -> GND
  - CSN  -> GPIO 7
  - SCK  -> GPIO 4 (default SPI SCK)
  - MOSI -> GPIO 6 (default SPI MOSI)
  - MISO -> GPIO 5 (default SPI MISO)
  - GDO0 -> GPIO 10
  - GDO2 -> GPIO 3
*/

// ========== CONFIGURARE ==========
// Schimba la false pentru modul receptor
#define TRANSMITTER_MODE true

// Configurare pini CC1101
CC1101 radio = new Module(7, 10, RADIOLIB_NC, 3);

// Forward declarations
void transmitPacket();

// Variabile
volatile bool operationDone = false;
int packetCounter = 0;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  operationDone = true;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println();
  Serial.println("==========================================");
  Serial.println("   Test CC1101 - Versiune Imbunatatita");
  Serial.println("==========================================");
  
  #if TRANSMITTER_MODE
    Serial.println("Mod: TRANSMITTER");
  #else
    Serial.println("Mod: RECEIVER");
  #endif
  Serial.println();
  
  // Initializare SPI
  SPI.begin(4, 5, 6, 7);
  
  // Initializare CC1101
  Serial.println("Initializare CC1101...");
  int state = radio.begin(
    433.0,   // frecventa MHz
    4.8,      // bit rate kbps
    5.2,      // deviatie frecventa kHz
    135.0,    // bandwidth kHz
    10,       // putere dBm
    16        // preamble bytes
  );
  
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("✓ CC1101 initializat cu succes!");
  } else {
    Serial.print("✗ Eroare initializare: ");
    Serial.println(state);
    while (true) delay(1000);
  }
  
  // Sync word - TREBUIE IDENTIC PE AMBELE MODULE!
  uint8_t syncWord[] = {0xD3, 0x91};
  state = radio.setSyncWord(syncWord, 2, 0, false);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("Eroare setSyncWord: ");
    Serial.println(state);
  } else {
    Serial.println("✓ Sync word setat: 0xD391");
  }
  
  // Activeaza CRC
  state = radio.setCrcFiltering(true);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("Eroare setCrcFiltering: ");
    Serial.println(state);
  } else {
    Serial.println("✓ CRC filtering activat");
  }
  
  Serial.println();
  Serial.println("Configuratie finala:");
  Serial.println("  Frecventa:  433.92 MHz");
  Serial.println("  Bit rate:   4.8 kbps");
  Serial.println("  Bandwidth:  135 kHz");
  Serial.println("  Sync word:  0xD391");
  Serial.println();
  
  // Seteaza callback
  radio.setPacketReceivedAction(setFlag);
  radio.setPacketSentAction(setFlag);
  
  #if TRANSMITTER_MODE
    Serial.println("Incep transmisia (o data la 3 secunde)...");
    Serial.println();
    delay(1000);
    transmitPacket();
  #else
    Serial.println("Astept pachete...");
    Serial.println();
    radio.startReceive();
  #endif
}

void transmitPacket() {
  char message[32];
  snprintf(message, sizeof(message), "PKT:%04d:TEST", packetCounter);
  
  Serial.print("[TX] Trimit: ");
  Serial.println(message);
  
  // Retry logic pentru erori temporare
  int state;
  int retries = 3;
  
  while (retries > 0) {
    state = radio.startTransmit(message);
    if (state == RADIOLIB_ERR_NONE) {
      break;  // Success
    }
    
    Serial.print("[TX] Retry... (eroare: ");
    Serial.print(state);
    Serial.println(")");
    
    // Reset radio si incearca din nou
    radio.standby();
    delay(50);
    retries--;
  }
  
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print("[TX] ✗ Eroare dupa retry-uri: ");
    Serial.println(state);
  }
  
  packetCounter++;
}

void loop() {
  if (operationDone) {
    operationDone = false;
    
    #if TRANSMITTER_MODE
      Serial.println("[TX] ✓ Trimis!");
      Serial.println();
      
      delay(3000);
      transmitPacket();
      
    #else
      // RECEIVER
      String data;
      int state = radio.readData(data);
      
      if (state == RADIOLIB_ERR_NONE) {
        float rssi = radio.getRSSI();
        
        if (rssi > -100) {
          Serial.println("------------------------------------------");
          Serial.print("[RX] ✓ Primit: ");
          Serial.println(data);
          Serial.print("     RSSI: ");
          Serial.print(rssi);
          Serial.println(" dBm");
          Serial.print("     LQI:  ");
          Serial.println(radio.getLQI());
          Serial.println("------------------------------------------");
        }
      }
      // Erori CRC sunt ignorate (zgomot)
      
      radio.startReceive();
    #endif
  }
}