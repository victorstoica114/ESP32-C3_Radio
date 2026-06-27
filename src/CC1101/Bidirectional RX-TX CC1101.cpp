#include <Arduino.h>
#include <RadioLib.h>

/*
  CC1101 Serial Bridge - Comunicatie bidirectionala
  
  Serial (115200 8N1) <---> CC1101 Radio
  
  - Ce primesti pe Serial -> se transmite prin radio
  - Ce primesti prin radio -> se trimite pe Serial
  
  Conexiuni CC1101 -> ESP32-C3:
  - VCC  -> 3.3V
  - GND  -> GND
  - CSN  -> GPIO 7
  - SCK  -> GPIO 4
  - MOSI -> GPIO 6
  - MISO -> GPIO 5
  - GDO0 -> GPIO 10
  - GDO2 -> GPIO 3
*/

// Configurare pini CC1101
CC1101 radio = new Module(7, 10, RADIOLIB_NC, 3);

// Buffer pentru date seriale
#define SERIAL_BUFFER_SIZE 64
char serialBuffer[SERIAL_BUFFER_SIZE];
int serialBufferIndex = 0;

// Timeout pentru pachet serial (ms)
#define SERIAL_TIMEOUT 50
unsigned long lastSerialTime = 0;

// Flag pentru receptie radio
volatile bool radioReceived = false;

// Stare curenta: true = RX, false = TX in progress
bool inReceiveMode = true;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void radioInterrupt(void) {
  radioReceived = true;
}

void startReceive() {
  radio.startReceive();
  inReceiveMode = true;
}

bool transmitData(const char* data, int length) {
  inReceiveMode = false;
  
  int state;
  int retries = 3;
  
  while (retries > 0) {
    // Transmisie sincrona (blocking) - mai simpla pentru bridge
    state = radio.transmit((uint8_t*)data, length);
    
    if (state == RADIOLIB_ERR_NONE) {
      startReceive();
      return true;
    }
    
    radio.standby();
    delay(10);
    retries--;
  }
  
  startReceive();
  return false;
}

void setup() {
  // Configurare Serial: 115200 8N1
  Serial.begin(115200);
  delay(1000);
  
  Serial.println();
  Serial.println("==========================================");
  Serial.println("   CC1101 Serial Bridge");
  Serial.println("   115200 8N1 <-> 433 MHz Radio");
  Serial.println("==========================================");
  Serial.println();
  
  // Initializare SPI
  SPI.begin(4, 5, 6, 7);
  
  // Initializare CC1101
  Serial.print("Initializare CC1101... ");
  int state = radio.begin(
    433.0,    // frecventa MHz
    4.8,      // bit rate kbps
    5.2,      // deviatie frecventa kHz
    135.0,    // bandwidth kHz
    10,       // putere dBm
    16        // preamble bytes
  );
  
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("OK");
  } else {
    Serial.print("EROARE: ");
    Serial.println(state);
    while (true) delay(1000);
  }
  
  // Sync word
  uint8_t syncWord[] = {0xD3, 0x91};
  radio.setSyncWord(syncWord, 2, 0, false);
  
  // CRC filtering
  radio.setCrcFiltering(true);
  
  // Seteaza interrupt pentru receptie
  radio.setPacketReceivedAction(radioInterrupt);
  
  // Incepe in modul receptie
  startReceive();
  
  Serial.println("Gata! Trimite date prin Serial...");
  Serial.println("------------------------------------------");
}

void loop() {
  // ========== PRIMIRE DATE DE LA RADIO ==========
  if (radioReceived) {
    radioReceived = false;
    
    uint8_t radioBuffer[64];
    int length = radio.getPacketLength();
    
    if (length > 0 && length <= 64) {
      int state = radio.readData(radioBuffer, length);
      
      if (state == RADIOLIB_ERR_NONE) {
        // Trimite datele primite prin Serial
        Serial.write(radioBuffer, length);
      }
    }
    
    // Restarteaza receptia
    startReceive();
  }
  
  // ========== PRIMIRE DATE DE LA SERIAL ==========
  while (Serial.available()) {
    char c = Serial.read();
    lastSerialTime = millis();
    
    if (serialBufferIndex < SERIAL_BUFFER_SIZE - 1) {
      serialBuffer[serialBufferIndex++] = c;
    }
  }
  
  // Daca avem date in buffer si a trecut timeout-ul, transmite
  if (serialBufferIndex > 0 && (millis() - lastSerialTime > SERIAL_TIMEOUT)) {
    serialBuffer[serialBufferIndex] = '\0';  // null terminate
    
    // Transmite prin radio
    if (transmitData(serialBuffer, serialBufferIndex)) {
      // Optional: echo local pentru debug
      // Serial.print("[TX OK] ");
      // Serial.println(serialBuffer);
    } else {
      Serial.println("[TX FAIL]");
    }
    
    // Reset buffer
    serialBufferIndex = 0;
  }
}