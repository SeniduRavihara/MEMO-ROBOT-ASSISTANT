#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- WIFI CONFIGURATION ---
const char* ssid = "Xperia XZ2";
const char* password = "senu1234";

// --- TCP SERVER CONFIG ---
const uint16_t port = 8002;
WiFiServer server(port);
WiFiClient client;

// I2S Microphone Pins (INMP441)
#define I2S_WS GPIO_NUM_25
#define I2S_SD GPIO_NUM_32
#define I2S_SCK GPIO_NUM_26
#define I2S_PORT I2S_NUM_0

// Audio settings
#define SAMPLE_RATE 16000
#define MIC_BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_32BIT
#define MIC_GAIN 8

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

void showText(String text) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  
  int y = 10;
  int startIdx = 0;
  while (startIdx < text.length()) {
    String line = text.substring(startIdx, startIdx + 21);
    u8g2.drawStr(0, y, line.c_str());
    y += 12;
    startIdx += 21;
    if (y > 60) break; 
  }
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  
  Wire.begin(4, 15);
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 10, "Robot Loading...");
  u8g2.sendBuffer();

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(); 
  delay(100);

  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    attempts++;
    if (attempts > 30) {
      showText("WiFi Failed. Rebooting...");
      delay(2000);
      ESP.restart();
    }
  }

  server.begin();

  Serial.println("\nWiFi connected.");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  u8g2.clearBuffer();
  u8g2.drawStr(0, 10, "ROBOT ONLINE");
  u8g2.drawStr(0, 25, ("IP: " + WiFi.localIP().toString()).c_str());
  u8g2.drawStr(0, 40, "Port: 8002");
  u8g2.drawStr(0, 55, "Waiting for PC...");
  u8g2.sendBuffer();

  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = MIC_BITS_PER_SAMPLE,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false
  };

  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);
}

void loop() {
  if (!client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("PC Connected!");
      showText("AI Robot Active! Speak now...");
    }
  }

  if (client.connected()) {
    // Check if PC/Gemini sent any text talk back
    if (client.available()) {
      String text = client.readStringUntil('\n');
      text.trim();
      if (text.length() > 0) {
        Serial.println("Gemini: " + text);
        showText(text);
      }
    }

    // Read mic and stream to PC
    size_t bytesIn = 0;
    int32_t wave[512]; 
    esp_err_t result = i2s_read(I2S_PORT, &wave, sizeof(wave), &bytesIn, 0); // Non-blocking
    
    if (result == ESP_OK && bytesIn > 0) {
      int samples_read = bytesIn / sizeof(wave[0]);
      int16_t out_wave[512];
      for (int i = 0; i < samples_read; ++i) {
        int32_t sample = (wave[i] >> 16) * MIC_GAIN;
        if (sample > 32767) sample = 32767;
        if (sample < -32768) sample = -32768;
        out_wave[i] = (int16_t)sample; 
      }
      client.write((uint8_t*)out_wave, samples_read * sizeof(int16_t));
    }
  }
}
