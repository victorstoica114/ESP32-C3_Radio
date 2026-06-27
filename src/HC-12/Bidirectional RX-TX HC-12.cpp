/*
  HC-12 test (ESP32 & AVR)
  - role select: transmitter (ping) or receiver (listen)
  - USB <-> HC-12 bridge (poți tasta în Serial Monitor și se trimite prin radio)
  - optional AT setup: bandă, canal, putere

  Hardware:
    HC-12 VCC -> 5V (merge și 3.3V, dar recomandat 5V conform fișei)
    HC-12 GND -> GND
    HC-12 RXD -> MCU TX (prin divizor dacă MCU e 5V->3.3V)
    HC-12 TXD -> MCU RX
    HC-12 SET -> pin digital (HIGH = normal, LOW = AT)
*/

#include <Arduino.h>

// ===================== CONFIG ROL =====================
#define HC12_IS_TRANSMITTER  1   // 1 = TX (trimite ping la 1s), 0 = RX (doar ascultă)

// ================== PINI & SERIALE ===================
// ---- Variante ESP32 (ex. ESP32-C3) ----
#if defined(ESP32)
  // Adaptează la placa ta:
  static const int HC12_RX_PIN   = 20;   // MCU RX  <- HC-12 TX
  static const int HC12_TX_PIN   = 21;   // MCU TX  -> HC-12 RX
  static const int HC12_SET_PIN  = 3;    // LOW = AT mode, HIGH = normal
  #define HC12_SERIAL     Serial1
  #define USB_SERIAL      Serial
#else
  // ---- AVR (UNO/Nano) ----
  #include <SoftwareSerial.h>
  static const int HC12_RX_PIN   = 10;   // Arduino RX  <- HC-12 TX
  static const int HC12_TX_PIN   = 11;   // Arduino TX  -> HC-12 RX
  static const int HC12_SET_PIN  = 4;    // LOW = AT mode, HIGH = normal
  SoftwareSerial HC12_SERIAL(HC12_RX_PIN, HC12_TX_PIN); // RX, TX
  #define USB_SERIAL      Serial
#endif

// ================== PARAMETRI COMUNICATIE =============
static const uint32_t USB_BAUD   = 115200;
static const uint32_t HC12_BAUD  = 9600;     // implicit HC-12
static const uint32_t AT_BAUD    = 9600;     // tot 9600 în AT

// ================== UTILE =============================
static void hc12WriteLine(const char* s) {
  HC12_SERIAL.write((const uint8_t*)s, strlen(s));
  HC12_SERIAL.write('\r'); HC12_SERIAL.write('\n');  // CRLF, pe placul HC-12
}

static void enterAT() {
  digitalWrite(HC12_SET_PIN, LOW);
  delay(50);
}

static void exitAT() {
  digitalWrite(HC12_SET_PIN, HIGH);
  delay(80);
}

// Trimite un AT și citește răspunsul
static void atCmd(const char* cmd) {
  hc12WriteLine(cmd);
  delay(60);
  while (HC12_SERIAL.available()) {
    USB_SERIAL.write(HC12_SERIAL.read());
  }
  USB_SERIAL.println();
}

// Opțional: setezi parametri (ex. canal C010, putere P8, baud 9600)
static void optionalATSetup() {
  enterAT();
  delay(50);

  USB_SERIAL.println(F("[AT] >> AT"));
  atCmd("AT");          // test
  USB_SERIAL.println(F("[AT] >> AT+B9600"));
  atCmd("AT+B9600");    // baud 9600 (default)
  USB_SERIAL.println(F("[AT] >> AT+C010"));
  atCmd("AT+C010");     // canal 10 (0..127)
  USB_SERIAL.println(F("[AT] >> AT+P8"));
  atCmd("AT+P8");       // putere maximă

  exitAT();
}

// ================== SETUP/LOOP ========================
static uint32_t lastPing = 0;

void setup() {
  pinMode(HC12_SET_PIN, OUTPUT);
  digitalWrite(HC12_SET_PIN, HIGH); // normal mode

  USB_SERIAL.begin(USB_BAUD);
  delay(200);
  USB_SERIAL.println();
  USB_SERIAL.println(F("[BOOT] HC-12 test"));

#if defined(ESP32)
  HC12_SERIAL.begin(HC12_BAUD, SERIAL_8N1, HC12_RX_PIN, HC12_TX_PIN);
#else
  HC12_SERIAL.begin(HC12_BAUD);
#endif
  delay(100);

  // (opțional) configurează prin AT (decomentează dacă vrei să rulezi o dată)
  // optionalATSetup();

  USB_SERIAL.println(F("[READY] Deschide două plăci: una TX, alta RX."));
  USB_SERIAL.println(F("       Poți și tasta în Serial Monitor -> se transmite prin radio."));
}

void loop() {
  // 1) Bridge USB -> HC-12
  while (USB_SERIAL.available()) {
    int c = USB_SERIAL.read();
    HC12_SERIAL.write((uint8_t)c);
  }

  // 2) Bridge HC-12 -> USB
  while (HC12_SERIAL.available()) {
    int c = HC12_SERIAL.read();
    USB_SERIAL.write((uint8_t)c);
  }

#if HC12_IS_TRANSMITTER
  // 3) TX: ping la 1s
  uint32_t now = millis();
  if (now - lastPing >= 1000) {
    lastPing = now;
    char buf[64];
    snprintf(buf, sizeof(buf), "PING t=%lu ms", (unsigned long)now);
    hc12WriteLine(buf);
    USB_SERIAL.print(F("[TX] ")); USB_SERIAL.println(buf);
  }
#endif
}
