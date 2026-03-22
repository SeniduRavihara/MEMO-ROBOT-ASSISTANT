#include <Arduino.h>
#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- WIFI CONFIGURATION ---
const char* ssid = "Xperia XZ2";
const char* password = "senidu1234";

// --- TCP SERVER CONFIG ---
const uint16_t port = 8003; // Using 8003 to isolate from main project
WiFiServer server(port);
WiFiClient client;

// I2S Speaker Pins (MAX98357)
#define I2S_SPK_BCLK GPIO_NUM_14
#define I2S_SPK_LRC GPIO_NUM_27
#define I2S_SPK_DOUT GPIO_NUM_33
#define I2S_SPK_PORT I2S_NUM_1

// Audio settings
#define SAMPLE_RATE 16000

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

void showText(const char* text1, const char* text2) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 15, text1);
  u8g2.drawStr(0, 35, text2);
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  
  // Init Display
  Wire.begin(4, 15);
  u8g2.begin();
  showText("TCP Test Project", "Connecting Wi-Fi...");

  // Init Wi-Fi
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
      showText("Error:", "Wi-Fi Failed");
      delay(2000);
      ESP.restart();
    }
  }

  // Start Server
  server.begin();
  Serial.println("\nWiFi connected.");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  char ipStr[30];
  snprintf(ipStr, sizeof(ipStr), "IP: %s", WiFi.localIP().toString().c_str());
  showText("Waiting PC...", ipStr);

  // Initialize Speaker I2S
  const i2s_config_t spk_i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT, // Needs Stereo for Hardware!
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 6,
    .dma_buf_len = 160,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };

  const i2s_pin_config_t spk_pin_config = {
    .bck_io_num = I2S_SPK_BCLK,
    .ws_io_num = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DOUT,
    .data_in_num = I2S_PIN_NO_CHANGE
  };

  i2s_driver_install(I2S_SPK_PORT, &spk_i2s_config, 0, NULL);
  i2s_set_pin(I2S_SPK_PORT, &spk_pin_config);
  
  Serial.println("I2S SPIKE UP! Hardware Ready.");
}

void loop() {
  if (!client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("PC Connected via TCP!");
      showText("TCP Linked!", "Awaiting command...");
    }
  }

  if (client.connected() && client.available() >= 5) {
      char header_peek[6];
      client.readBytes(header_peek, 5);
      header_peek[5] = '\0';
      
      if (strcmp(header_peek, "TEXT:") == 0) {
        String text = client.readStringUntil('\n');
        text.trim();
        Serial.println(">>> RECEIVED TEXT: " + text);
        showText("Python Says:", text.c_str());
      } 
      else if (strcmp(header_peek, "AUDIO") == 0) {
        Serial.println(">>> DETECTED AUDIO PCM HEADER");
        showText("Downloading...", "Audio PCM Stream");

        // Read 4 bytes length
        uint32_t audio_len = 0;
        uint8_t len_buf[4];
        while (client.connected() && client.available() < 4) { delay(1); } 
        client.readBytes(len_buf, 4);
        audio_len = ((uint32_t)len_buf[0] << 24) | ((uint32_t)len_buf[1] << 16) | ((uint32_t)len_buf[2] << 8) | (uint32_t)len_buf[3];
        
        Serial.printf(">>> Expecting PCM length: %u bytes\n", audio_len);
        
        uint32_t total_received = 0;
        uint8_t audio_buf[1024];

        while (total_received < audio_len && client.connected()) {
           int available_now = client.available();
           if (available_now > 0) {
             int to_read = min((uint32_t)available_now, audio_len - total_received);
             to_read = min((uint32_t)1024, (uint32_t)to_read);
             
             // Guarantee 4-byte boundary (16-bit Stereo PCM)
             int original_read = to_read;
             to_read = (to_read / 4) * 4;
             
             // Escape Hatch logic for end byte mismatch
             if (to_read == 0 && available_now > 0) {
                to_read = min((uint32_t)available_now, audio_len - total_received);
                Serial.printf("Escape hatch activated: %i bytes left to read.\n", to_read);
             }
             if (to_read == 0) { delay(1); continue; }
             
             int read_now = client.readBytes((uint8_t*)audio_buf, to_read);
             if (read_now > 0) {
               size_t bytes_written = 0;
               i2s_write(I2S_SPK_PORT, audio_buf, read_now, &bytes_written, portMAX_DELAY);
               total_received += read_now;
             }
           } else {
             delay(1);
           }
        }
        Serial.println(">>> PCM AUDIO CHUNK PLAYBACK FINISHED");
        showText("Playback done!", "Ready...");
      } 
      else {
        Serial.printf(">>> UNKNOWN TCP HEADER: [%s]\n", header_peek);
      }
  }
}
