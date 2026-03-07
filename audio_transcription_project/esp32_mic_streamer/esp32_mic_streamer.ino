#include <driver/i2s.h>
#include <Wire.h>
#include <U8g2lib.h>

// I2S Microphone Pins (INMP441)
#define I2S_WS GPIO_NUM_25
#define I2S_SD GPIO_NUM_32
#define I2S_SCK GPIO_NUM_26
#define I2S_PORT I2S_NUM_0

// Audio settings
#define SAMPLE_RATE 16000 // 16kHz is standard for voice transcription
#define MIC_BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_32BIT
#define MIC_GAIN 8 // Artificial volume multiplier for distant speech

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

void showText(String text) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  
  // Basic text wrapping (max 21 chars per line)
  int y = 10;
  int startIdx = 0;
  while (startIdx < text.length()) {
    String line = text.substring(startIdx, startIdx + 21);
    u8g2.drawStr(0, y, line.c_str());
    y += 12;
    startIdx += 21;
    if (y > 60) break; // Screen full
  }
  
  u8g2.sendBuffer();
}

void setup() {
  // Use a fast baud rate for raw audio data
  Serial.begin(921600);
  Serial.setTimeout(10); // Very short timeout so we don't block audio
  
  Wire.begin(4, 15);
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 10, "Listening to MEMO...");
  u8g2.sendBuffer();

  // Wait a moment for serial to initialize
  delay(1000);

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
  // Check if Python sent any text to display
  if (Serial.available()) {
    String text = Serial.readStringUntil('\n');
    text.trim();
    if (text.length() > 0) {
      showText(text);
    }
  }

  size_t bytesIn = 0;
  // A chunk of 512 samples
  int32_t wave[512]; 
  
  esp_err_t result = i2s_read(I2S_PORT, &wave, sizeof(wave), &bytesIn, portMAX_DELAY);
  
  if (result == ESP_OK && bytesIn > 0) {
    int samples_read = bytesIn / sizeof(wave[0]);
    int16_t out_wave[512];
    
    // Shift 24-bit data inside 32-bit frame to 16-bit, then apply software gain
    for (int i = 0; i < samples_read; ++i) {
      int32_t sample = wave[i] >> 16;
      sample = sample * MIC_GAIN;
      
      // Clamp to 16-bit boundaries to prevent distortion/wrapping
      if (sample > 32767) sample = 32767;
      if (sample < -32768) sample = -32768;
      
      out_wave[i] = (int16_t)sample; 
    }

    // Write raw binary bytes straight to the Serial port
    Serial.write((uint8_t*)out_wave, samples_read * sizeof(int16_t));
  }
}
