#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <driver/i2s.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

#define I2S_PORT I2S_NUM_0
#define I2S_WS 25
#define I2S_SD 32
#define I2S_SCK 26

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15); // Your custom pins
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(WHITE);

  // I2S Setup
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = 44100,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 64,
    .use_apll = false
  };
  const i2s_pin_config_t pin_config = { .bck_io_num = I2S_SCK, .ws_io_num = I2S_WS, .data_out_num = -1, .data_in_num = I2S_SD };
  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
}

void loop() {
  int32_t sample = 0;
  size_t bytes_read;
  i2s_read(I2S_PORT, &sample, sizeof(sample), &bytes_read, portMAX_DELAY);
  
  // Calculate amplitude (make it positive and readable)
  int volume = abs(sample >> 16); 
  
  // Map the volume to screen height (adjust 2000 to match your environment)
  int barHeight = map(constrain(volume, 0, 2000), 0, 2000, 0, SCREEN_HEIGHT);

  display.clearDisplay();
  display.setCursor(0,0);
  display.print("Sound Level: ");
  display.println(volume);
  
  // Draw the bar
  display.fillRect(0, SCREEN_HEIGHT - barHeight, 50, barHeight, WHITE);
  display.display();
}