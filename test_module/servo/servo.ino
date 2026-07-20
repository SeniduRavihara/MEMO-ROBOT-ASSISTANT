#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <driver/i2s.h>

// Shared I2S Pins
#define I2S_WS 27    // Connect to Mic WS and Amp LRC
#define I2S_SCK 14   // Connect to Mic SCK and Amp BCLK
#define I2S_SD_IN 32 // Mic SD
#define I2S_SD_OUT 33// Amp DIN

// OLED Pins (Your setup)
#define SDA_PIN 4
#define SCL_PIN 15

Adafruit_SSD1306 display(128, 64, &Wire, -1);

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.clearDisplay();

  // I2S Configuration
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_TX),
    .sample_rate = 44100,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 64,
    .use_apll = false
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_SD_OUT,
    .data_in_num = I2S_SD_IN
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
}

void loop() {
  int32_t sample = 0;
  size_t bytes_read, bytes_written;

  // 1. Read Mic
  i2s_read(I2S_NUM_0, &sample, sizeof(sample), &bytes_read, portMAX_DELAY);
  fucking IDE become not 
  // 2. Play through Amp
  i2s_write(I2S_NUM_0, &sample, sizeof(sample), &bytes_written, portMAX_DELAY);

  // 3. Visuals on OLED
  int volume = abs(sample >> 16);
  int barWidth = map(constrain(volume, 0, 2000), 0, 2000, 0, 128);

  display.clearDisplay();
  display.fillRect(0, 20, barWidth, 20, WHITE); // Draw Volume Bar
  display.display();
}