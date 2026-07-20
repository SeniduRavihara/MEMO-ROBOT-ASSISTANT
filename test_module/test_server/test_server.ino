#include <WiFi.h>
#include <U8g2lib.h>
#include <Wire.h>

// --- WiFi Credentials ---
const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";

// Screen Setup (SDA=4, SCL=5)
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

void updateOLED(const char* line1, const char* line2) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 15, "--- NETWORK TEST ---");
  u8g2.drawStr(0, 35, line1);
  u8g2.drawStr(0, 55, line2);
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  delay(2000); // Essential delay for automatic startup stability

  // Start OLED on Super Mini pins 4 & 5
  Wire.begin(4, 5); 
  u8g2.begin();
  updateOLED("WIFI STATUS:", "Searching...");

  // Force a clean start for the WiFi chip
  WiFi.disconnect(true);
  delay(500);
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    attempts++;

    // Every 10 attempts (5 seconds), show progress on screen
    if (attempts % 10 == 0) {
      updateOLED("STILL SEARCHING", ssid);
    }
    
    // If it takes more than 20 seconds, restart connection
    if (attempts > 40) {
        Serial.println("\nRetrying WiFi...");
        WiFi.begin(ssid, password);
        attempts = 0;
    }
  }

  // SUCCESS: Display the IP on OLED!
  Serial.println("\nWiFi Connected!");
  updateOLED("CONNECTED!", WiFi.localIP().toString().c_str());
}

void loop() {
  // Stay online and keep the screen updated heartbeat
  static unsigned long lastCheck = 0;
  if (millis() - lastCheck > 10000) {
    lastCheck = millis();
    if (WiFi.status() == WL_CONNECTED) {
      updateOLED("STATUS: ONLINE", WiFi.localIP().toString().c_str());
    } else {
      updateOLED("STATUS: OFFLINE", "Reconnecting...");
      WiFi.begin(ssid, password);
    }
  }
}
