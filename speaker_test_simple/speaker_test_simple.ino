#include <driver/i2s.h>
#include <math.h>

// I2S Amplifier Pins
#define I2S_BCLK 14
#define I2S_LRC  27
#define I2S_DIN  33

#define SAMPLE_RATE 44100

void setup() {
  Serial.begin(115200);
  Serial.println("Starting simple speaker test...");

  // I2S Configuration for Output Only (Amplifier)
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 64,
    .use_apll = false
  };

  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCLK,
    .ws_io_num = I2S_LRC,
    .data_out_num = I2S_DIN,
    .data_in_num = -1 // Not used for output
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
  i2s_start(I2S_NUM_0);
  
  Serial.println("Amplifier initialized. Generating tone...");
}

void loop() {
  // Generate a simple 440Hz sine wave tone
  static float phase = 0;
  
  // Create a 16-bit audio sample. 
  // We multiply the sine wave (-1.0 to 1.0) by a large amplitude.
  // We keep it a bit below the absolute 16-bit max (32767) to prevent nasty clipping.
  int16_t sample = (int16_t)(sin(phase) * 10000.0); 
  
  size_t bytes_written;
  i2s_write(I2S_NUM_0, &sample, sizeof(sample), &bytes_written, portMAX_DELAY);
  
  // Advance the phase for 440Hz at 44100Hz sample rate
  // Calculation: 2 * PI * Frequency / SampleRate
  phase += 2.0 * PI * 440.0 / 44100.0;
  
  // Wrap phase to keep math clean
  if (phase >= 2.0 * PI) {
    phase -= 2.0 * PI;
  }
}
