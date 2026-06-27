#include<Arduino.h>

// Configurare pentru Serial1 (UART1)
#define UART1_RX_PIN 20
#define UART1_TX_PIN 21
#define UART1_BAUD   115200

// LED opțional (trafic)
#define LED_PIN 8

void setup() {
  // Serial USB (UART0)
  Serial.begin(115200);
  delay(5000);
  Serial.println();
  Serial.println("[ESP32-C3] Serial bridge started!");
  Serial.println("Serial @9600 <-> Serial1 @115200");
  // Inițializează UART1 pe pinii doriți
  Serial1.begin(UART1_BAUD, SERIAL_8N1, UART1_RX_PIN, UART1_TX_PIN);
  Serial1.setTimeout(1);

  // LED de trafic
  pinMode(LED_PIN, OUTPUT);
  pinMode(10, OUTPUT);
  pinMode(3, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(3, LOW);
  digitalWrite(10, LOW);
}

void loop() {
  // Transmitere Serial -> Serial1
  while (Serial.available()) {
    int c = Serial.read();
    Serial1.write(c);
    digitalWrite(LED_PIN, !digitalRead(LED_PIN)); // pulsează LED-ul
  }

  // Transmitere Serial1 -> Serial
  while (Serial1.available()) {
    int c = Serial1.read();
    Serial.write(c);
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }

  // Mic delay pentru stabilitate
  delay(1);
}
