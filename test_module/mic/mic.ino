bine t#include <driver/i2s.h>

// Define the port globally so everyone can see it
#define I2S_PORT I2S_NUM_0

void setup() {
  Serial.begin(115200);
  
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

  const i2s_pin_config_t pin_config = {
    .bck_io_num = 26, // SCK
    .ws_io_num = 25,  // WS
    .data_out_num = -1,
    .data_in_num = 32 // SD
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
}

void loop() {
  int32_t sample = 0;
  size_t bytes_read;
  
  // Now I2S_PORT is visible here!
  i2s_read(I2S_PORT, &sample, sizeof(sample), &bytes_read, portMAX_DELAY);

  if (bytes_read > 0) {
    // Shifting right by 16 bits to make the number readable
    Serial.println(sample >> 16); 
  }
}