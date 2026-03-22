#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>
#include <Wire.h>
#include <U8g2lib.h>

#define I2S_PORT I2S_NUM_1
#define I2S_BCLK GPIO_NUM_14
#define I2S_LRC GPIO_NUM_27
#define I2S_DOUT GPIO_NUM_33

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
  Serial.println("\n--- Hardware Test: Speaker & Display ---");

  // Init Display
  Wire.begin(4, 15);
  u8g2.begin();
  showText("Hardware Test", "Initializing...");

  // Basic I2S configuration matching the MAX98357 (Stereo 16-bit flow)
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = true,
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCLK,
    .ws_io_num = I2S_LRC,
    .data_out_num = I2S_DOUT,
    .data_in_num = I2S_PIN_NO_CHANGE
  };

  if (i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL) != ESP_OK) {
    Serial.println("Failed to install I2S driver");
    showText("Error:", "I2S Install Failed");
    return;
  }
  
  if (i2s_set_pin(I2S_PORT, &pin_config) != ESP_OK) {
    Serial.println("Failed to set I2S pins");
    showText("Error:", "I2S Pin Setup Failed");
    return;
  }

  Serial.println("I2S initialized successfully. Starting audio loops...");
  showText("Setup Complete!", "Starting Test...");
  delay(1000);
}

void playTone(float frequency, float durationSec, float volume) {
  int num_samples = int(SAMPLE_RATE * durationSec);
  // Allocate buffer for 16-bit stereo (2 channels)
  int16_t *buffer = (int16_t*)malloc(num_samples * 2 * sizeof(int16_t));
  if (buffer == NULL) {
     Serial.println("Failed to allocate audio buffer");
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
  i2s_write(I2S_PORT, buffer, num_samples * 2 * sizeof(int16_t), &bytes_written, portMAX_DELAY);
  
  free(buffer);
}

// Note frequencies (Hz)
#define NOTE_E5  659
#define NOTE_C5  523
#define NOTE_G5  784
#define NOTE_G4  392

void loop() {
  Serial.println("Playing Melody...");
  showText("Testing Speaker", "Playing Melody...");
  float vol = 0.5;
  
  playTone(NOTE_E5, 0.15, vol); delay(150);
  playTone(NOTE_E5, 0.15, vol); delay(300);
  playTone(NOTE_E5, 0.15, vol); delay(300);
  playTone(NOTE_C5, 0.15, vol); delay(150);
  playTone(NOTE_E5, 0.15, vol); delay(300);
  playTone(NOTE_G5, 0.15, vol); delay(600);
  playTone(NOTE_G4, 0.15, vol); delay(600);
  
  Serial.println("Waiting 2 seconds...");
  showText("Test Complete", "Waiting 2s...");
  delay(2000);
}
