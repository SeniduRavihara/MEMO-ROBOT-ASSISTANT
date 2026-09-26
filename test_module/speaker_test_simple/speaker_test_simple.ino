#include <driver/i2s.h>
#include <math.h>

// I2S Amplifier Pins (ESP32-S3 N16R8 safe pins)
#define I2S_BCLK 16
#define I2S_LRC  17
#define I2S_DIN  15

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

// Note frequencies (Hz)
#define NOTE_C4  262
#define NOTE_D4  294
#define NOTE_E4  330
#define NOTE_F4  349
#define NOTE_G4  392
#define NOTE_A4  440
#define NOTE_B4  494
#define NOTE_C5  523

void playTone(int frequency, int durationMs) {
  Serial.print("Playing tone: ");
  Serial.print(frequency);
  Serial.println(" Hz");

  float phase = 0;
  float phaseStep = 2.0 * PI * frequency / (float)SAMPLE_RATE;
  int totalSamples = SAMPLE_RATE * durationMs / 1000;

  for (int i = 0; i < totalSamples; i++) {
    int16_t sample = (int16_t)(sin(phase) * 10000.0);
    size_t bytes_written;
    i2s_write(I2S_NUM_0, &sample, sizeof(sample), &bytes_written, portMAX_DELAY);
    phase += phaseStep;
    if (phase >= 2.0 * PI) phase -= 2.0 * PI;
  }

  // Short silence between notes
  int16_t silence = 0;
  for (int i = 0; i < SAMPLE_RATE / 10; i++) {
    size_t bytes_written;
    i2s_write(I2S_NUM_0, &silence, sizeof(silence), &bytes_written, portMAX_DELAY);
  }
}

void loop() {
  Serial.println("\n=== Playing C Major Scale ===");
  playTone(NOTE_C4, 400);
  playTone(NOTE_D4, 400);
  playTone(NOTE_E4, 400);
  playTone(NOTE_F4, 400);
  playTone(NOTE_G4, 400);
  playTone(NOTE_A4, 400);
  playTone(NOTE_B4, 400);
  playTone(NOTE_C5, 600);

  delay(500);

  Serial.println("=== Playing Beep Pattern ===");
  playTone(NOTE_C5, 150);
  playTone(NOTE_C5, 150);
  playTone(NOTE_G4, 500);

  delay(1000);
}
