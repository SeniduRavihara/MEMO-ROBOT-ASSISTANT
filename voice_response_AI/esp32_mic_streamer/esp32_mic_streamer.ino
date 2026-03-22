#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- WIFI CONFIGURATION ---
const char* ssid = "4G-Senidu";
const char* password = "1234567890";

// --- TCP SERVER CONFIG ---
const uint16_t port = 8005;
WiFiServer server(port);
WiFiClient client;

// I2S Microphone Pins (INMP441)
#define I2S_WS GPIO_NUM_25
#define I2S_SD GPIO_NUM_32
#define I2S_SCK GPIO_NUM_26
#define I2S_PORT I2S_NUM_0

// I2S Speaker Pins (MAX98357)
#define I2S_SPK_BCLK GPIO_NUM_14
#define I2S_SPK_LRC GPIO_NUM_27
#define I2S_SPK_DOUT GPIO_NUM_33
#define I2S_SPK_PORT I2S_NUM_1

// Audio settings
#define SAMPLE_RATE 16000
#define MIC_BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_16BIT
#define MIC_GAIN 4

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

// Flag to pause mic streaming while speaker is active
volatile bool isSpeaking = false;

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

void playTone(float frequency, float durationSec, float volume) {
  int num_samples = int(SAMPLE_RATE * durationSec);
  // Allocate buffer for 16-bit stereo (2 channels)
  int16_t *buffer = (int16_t*)malloc(num_samples * 2 * sizeof(int16_t));
  if (buffer == NULL) {
     Serial.println("Failed to allocate audio buffer for tone");
     return;
  }

  // Calculate sine wave maximum amplitude
  float amplitude = volume * 32767.0f;
  
  for (int i = 0; i < num_samples; i++) {
    float t = (float)i / SAMPLE_RATE;
    int16_t sample = (int16_t)(amplitude * sin(2.0f * PI * frequency * t));
    
    // Fill both left and right channels for stereo 16-bit Right_Left format
    buffer[2 * i] = sample;     // Left Channel
    buffer[2 * i + 1] = sample; // Right Channel
  }

  size_t bytes_written;
  i2s_write(I2S_SPK_PORT, buffer, num_samples * 2 * sizeof(int16_t), &bytes_written, portMAX_DELAY);
  
  free(buffer);
}

void playBeep() {
  isSpeaking = true;

  // Exactly like test_speaker.ino — no DMA flush, just direct tone writes
  playTone(523, 0.15, 0.5);  // C5
  delay(150);
  playTone(659, 0.15, 0.5);  // E5
  delay(150);
  playTone(784, 0.15, 0.5);  // G5

  isSpeaking = false;
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
  u8g2.drawStr(0, 40, ("Port: " + String(port)).c_str());
  u8g2.drawStr(0, 55, "Initializing I2S...");
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

  if (i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL) != ESP_OK) {
    showText("Mic I2S Install Fail");
    return;
  }
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);

  // Initialize Speaker I2S — config matches test_speaker.ino (proven working)
  const i2s_config_t spk_i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };

  const i2s_pin_config_t spk_pin_config = {
    .bck_io_num = I2S_SPK_BCLK,
    .ws_io_num = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DOUT,
    .data_in_num = I2S_PIN_NO_CHANGE
  };

  if (i2s_driver_install(I2S_SPK_PORT, &spk_i2s_config, 0, NULL) != ESP_OK) {
    showText("Spk I2S Install Fail");
    return;
  }
  i2s_set_pin(I2S_SPK_PORT, &spk_pin_config);
  i2s_start(I2S_SPK_PORT);

  Serial.println("Setup Complete - Server Listening...");
  u8g2.clearBuffer();
  u8g2.drawStr(0, 10, "ROBOT ONLINE");
  u8g2.drawStr(0, 25, ("IP: " + WiFi.localIP().toString()).c_str());
  u8g2.drawStr(0, 40, ("Port: " + String(port)).c_str());
  u8g2.drawStr(0, 55, "READY FOR PC!");
  u8g2.sendBuffer();
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
    // Check if PC/Gemini sent any data (Commands or Audio)
    if (client.available() >= 5) {
      char header_peek[6];
      client.readBytes(header_peek, 5);
      header_peek[5] = '\0';
      
      if (strcmp(header_peek, "TEXT:") == 0) {
        String text = client.readStringUntil('\n');
        text.trim();
        Serial.println(">>> RECEIVED TEXT: " + text);
        showText(text);
        
        // Play confirmation beep after displaying Gemini response
        Serial.println(">>> PLAYING BEEP");
        playBeep();
      } 
      else if (strcmp(header_peek, "AUDIO") == 0) {
        Serial.println(">>> DETECTED AUDIO HEADER");
        // Read 4 bytes length (Big-Endian from Python)
        uint32_t audio_len = 0;
        uint8_t len_buf[4];
        
        while (client.connected() && client.available() < 4) { delay(1); } 
        client.readBytes(len_buf, 4);
        
        audio_len = ((uint32_t)len_buf[0] << 24) | ((uint32_t)len_buf[1] << 16) | ((uint32_t)len_buf[2] << 8) | (uint32_t)len_buf[3];
        Serial.printf(">>> RECEIVING AUDIO DATA: %u bytes\n", audio_len);
        
        uint32_t total_received = 0;
        uint8_t audio_buf[1024];
        while (total_received < audio_len && client.connected()) {
           int available_now = client.available();
           if (available_now > 0) {
             int to_read = min((uint32_t)available_now, audio_len - total_received);
             to_read = min((uint32_t)1024, (uint32_t)to_read);
             
             // Guarantee 4-byte boundary (16-bit Stereo PCM)
             to_read = (to_read / 4) * 4;
             
             // If we're at the very end and there's a 1-byte mismatch, just read it to break the loop
             if (to_read == 0 && available_now > 0) {
                to_read = min((uint32_t)available_now, audio_len - total_received);
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
        Serial.println(">>> AUDIO PLAYBACK FINISHED");
      } 
      else {
        Serial.printf(">>> UNKNOWN HEADER: [%s]\n", header_peek);
      }
    }

    // Read mic and stream to PC (skip while speaker is active to avoid feedback)
    if (!isSpeaking) {
      size_t bytesIn = 0;
      int16_t wave[512]; 
      esp_err_t result = i2s_read(I2S_PORT, &wave, sizeof(wave), &bytesIn, 0); // Non-blocking
      
      if (result == ESP_OK && bytesIn > 0) {
        int samples_read = bytesIn / sizeof(wave[0]);
        for (int i = 0; i < samples_read; ++i) {
          int32_t sample = (int32_t)wave[i] * MIC_GAIN;
          if (sample > 32767) sample = 32767;
          if (sample < -32768) sample = -32768;
          wave[i] = (int16_t)sample; 
        }
        client.write((uint8_t*)wave, samples_read * sizeof(int16_t));
      }
    }
  }
}
