/*
 * ============================================================================
 *  MEMO AI Robot Assistant — ESP32-S3 N16R8 Dual-Core Firmware
 *  (Core 1: Direct Audio DMA & TCP Engine | Core 0: 40 FPS FFT & OLED Display)
 * ============================================================================
 *  Architecture:
 *    - Core 1 (Arduino loop — Dedicated Audio & TCP Engine):
 *        * 100% Dedicated to I2S Microphone (INMP441) and Speaker (MAX98357A)
 *        * Direct, non-blocking TCP streaming to Python (exact proven 3f29f20 logic)
 *        * Direct instant streaming playback to speaker (zero PSRAM dependency)
 *        * ZERO display code on Core 1 -> Audio never drops, never lags!
 *    - Core 0 (Background displayTask — Dedicated Visualizer):
 *        * Computes 512-point FFT from fft_wave buffer
 *        * Renders real-time audio spectrum histogram (0..2kHz, 0dB, -20dB, -40dB) at ~40 FPS
 *        * 100% fluid, instant millisecond changes on OLED display!
 * ============================================================================
 */

#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "arduinoFFT.h"

// --- WIFI CONFIGURATION ---
const char* ssid     = "HUAWEI nova 3i";
const char* password = "senidu1234";

// --- TCP SERVER CONFIG ---
const uint16_t port = 8005;
WiFiServer server(port);
WiFiClient client;

// --- PIN ASSIGNMENTS (ESP32-S3 N16R8) ---
// I2S Microphone Pins (INMP441 — Port 0)
#define I2S_SCK  GPIO_NUM_4
#define I2S_WS   GPIO_NUM_5
#define I2S_SD   GPIO_NUM_6
#define I2S_PORT I2S_NUM_0

// I2S Speaker Pins (MAX98357A — Port 1)
#define I2S_SPK_DIN  GPIO_NUM_15
#define I2S_SPK_BCLK GPIO_NUM_16
#define I2S_SPK_LRC  GPIO_NUM_17
#define I2S_SPK_PORT I2S_NUM_1

// I2C Pins (OLED Display & MPU6050)
#define I2C_SDA 8
#define I2C_SCL 9

// --- AUDIO CONFIGURATION ---
#define SAMPLE_RATE          16000
#define MIC_BITS_PER_SAMPLE  I2S_BITS_PER_SAMPLE_16BIT
#define MIC_GAIN             8
#define MIC_BUF_SAMPLES      512

// Static mic buffer (1024 bytes = 512 samples)
int16_t mic_buf[MIC_BUF_SAMPLES];

// --- DISPLAY & LIVE SPECTRUM FFT ---
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

#define FFT_SAMPLES 512
double vReal[FFT_SAMPLES];
double vImag[FFT_SAMPLES];
ArduinoFFT<double> FFT(vReal, vImag, FFT_SAMPLES, (double)SAMPLE_RATE);

int16_t fft_wave[FFT_SAMPLES];
double maxWave = 0.0;
char robotStatusText[32] = "MEMO Ready";

// --- MPU6050 ---
Adafruit_MPU6050 mpu;
bool mpuAvailable = false;

// --- STATE MANAGEMENT ---
volatile bool isSpeaking = false;
unsigned long lastChunkTime = 0;

// Spectrum layout coordinates
#define PX2 0
#define PY1 12 // Top area for status
#define PY2 54 // Lower edge of spectrum (-40dB)

// ── SPECTRUM GRAPHICS FUNCTIONS (Core 0) ────────────────────────────────────
int barLength(double d) {
  float fy = 14.0 * (log10(d + 1e-6) + 1.5);
  int y = fy;
  return constrain(y, 0, 40);
}

void showSpectrum() {
  static int peak[128] = {0};
  for (int xi = 1; xi < 128; xi++) {
    int d = barLength(vReal[xi]);
    u8g2.drawVLine(xi + PX2, PY2 - d, d);
    u8g2.drawVLine(xi + PX2, PY2 - peak[xi], 1);
    if (peak[xi] < d) peak[xi] = d;
    if (peak[xi] > 0) peak[xi]--;
  }
}

void showOthers() {
  u8g2.drawHLine(0, PY2, 128); // Spectrum bottom line

  // Frequency ticks
  for (int xp = PX2; xp < 127; xp += 5) {
    u8g2.drawVLine(xp, PY2 + 1, 1);
  }
  u8g2.drawVLine(PX2 + 25, PY2 + 1, 2);
  u8g2.drawVLine(PX2 + 50, PY2 + 1, 2);

  // Frequency labels
  u8g2.setFont(u8g2_font_micro_tr);
  u8g2.setCursor(0, 56);   u8g2.print("0");
  u8g2.setCursor(55, 56);  u8g2.print("1k");
  u8g2.setCursor(115, 56); u8g2.print("2k");

  // Dotted dB lines
  for (int y = PY2 - 7; y > 14; y -= 14) {
    for (int x = 0; x < 100; x += 5) {
      u8g2.drawHLine(x, y, 2);
    }
  }

  // dB labels
  u8g2.setFont(u8g2_font_micro_tr);
  u8g2.setCursor(102, 16); u8g2.print("0dB");
  u8g2.setCursor(102, 29); u8g2.print("-20");
  u8g2.setCursor(102, 43); u8g2.print("-40");

  // Status line in top band
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 0, robotStatusText);
}

void displayAll() {
  u8g2.clearBuffer();
  showSpectrum();
  showOthers();
  u8g2.sendBuffer();
}

void performFFT() {
  maxWave = 0.0;
  for (int i = 0; i < FFT_SAMPLES; i++) {
    vReal[i] = (double)fft_wave[i] * 3.3 / 4096.0;
    vImag[i] = 0;
    int tmp = abs(fft_wave[i]);
    if (tmp > maxWave) maxWave = tmp;
  }
  FFT.windowing(FFTWindow::Hamming, FFTDirection::Forward);
  FFT.compute(FFTDirection::Forward);
  FFT.complexToMagnitude();
}

// ── TEXT DISPLAY HELPER (Boot Only) ──────────────────────────────────────────
void showText(String text) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  int y = 0;
  int startIdx = 0;
  while (startIdx < (int)text.length()) {
    String line = text.substring(startIdx, startIdx + 21);
    u8g2.drawStr(0, y, line.c_str());
    y += 12;
    startIdx += 21;
    if (y > 54) break;
  }
  u8g2.sendBuffer();
}

// ── SERVER COMMAND PARSER ───────────────────────────────────────────────────
void handleServerText(String text) {
  text.trim();
  Serial.println(">>> SERVER TEXT: " + text);

  if (text.startsWith("Listening")) {
    strncpy(robotStatusText, "Listening...", sizeof(robotStatusText) - 1);
  } else if (text.startsWith("Thinking")) {
    strncpy(robotStatusText, "Thinking...", sizeof(robotStatusText) - 1);
  } else if (text.startsWith("AI Robot Active")) {
    strncpy(robotStatusText, "MEMO Ready!", sizeof(robotStatusText) - 1);
  } else {
    if (text.length() > 20) {
      String shortText = text.substring(0, 18) + "..";
      strncpy(robotStatusText, shortText.c_str(), sizeof(robotStatusText) - 1);
    } else {
      strncpy(robotStatusText, text.c_str(), sizeof(robotStatusText) - 1);
    }
  }
}

// ── CORE 0: DEDICATED FLUID DISPLAY TASK (~40 FPS) ──────────────────────────
void displayTask(void* pvParameters) {
  for (;;) {
    if (!isSpeaking) {
      performFFT();
      displayAll();
    }
    vTaskDelay(pdMS_TO_TICKS(22)); // ~40 FPS ultra-fluid visualizer on Core 0!
  }
}

// ── SETUP ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n========================================");
  Serial.println("  🤖 MEMO AI ROBOT DUAL-CORE FIRMWARE");
  Serial.println("  Core 1: Direct Audio DMA | Core 0: 40 FPS OLED");
  Serial.println("========================================");

  // 1. Initialize I2C with 400kHz Fast Mode & OLED Display
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  u8g2.begin();
  u8g2.setFontPosTop();
  showText("MEMO Booting...\nDual-Core Setup");

  // 2. Connect to Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);
  WiFi.begin(ssid, password);

  showText("Connecting WiFi:\n" + String(ssid));

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++attempts > 25) {
      Serial.println("\n[WiFi] Connection timeout. Standalone mode.");
      showText("Standalone Mode\n(No Wi-Fi)");
      delay(1200);
      break;
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    server.begin();
    Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    showText("WiFi Connected!\nIP: " + WiFi.localIP().toString());
    delay(1200);
  }

  // 3. Initialize I2S Microphone (INMP441 — Port 0, 32 DMA buffers = 2.0s FIFO)
  const i2s_config_t i2s_config = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = MIC_BITS_PER_SAMPLE,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 32,
    .dma_buf_len          = 1024,
    .use_apll             = false
  };
  const i2s_pin_config_t pin_config = {
    .bck_io_num   = I2S_SCK,
    .ws_io_num    = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_SD
  };
  if (i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL) != ESP_OK) {
    showText("Mic I2S Fail!");
    return;
  }
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);

  // 4. Initialize I2S Speaker (MAX98357A — Port 1)
  const i2s_config_t spk_i2s_config = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 32,
    .dma_buf_len          = 1024,
    .use_apll             = false,
    .tx_desc_auto_clear   = true
  };
  const i2s_pin_config_t spk_pin_config = {
    .bck_io_num   = I2S_SPK_BCLK,
    .ws_io_num    = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DIN,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };
  i2s_driver_install(I2S_SPK_PORT, &spk_i2s_config, 0, NULL);
  i2s_set_pin(I2S_SPK_PORT, &spk_pin_config);
  i2s_start(I2S_SPK_PORT);

  // 5. Optional MPU6050
  if (mpu.begin()) {
    mpuAvailable = true;
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }

  // 6. Launch Dedicated Fluid Spectrum Display Task on Core 0 (Priority 1)
  // Completely offloads OLED rendering and FFT calculation from Core 1!
  xTaskCreatePinnedToCore(
    displayTask,
    "DisplayTask",
    4096,
    NULL,
    1,
    NULL,
    0  // Pin to Core 0!
  );

  Serial.println("[Setup] Ready! Core 1: Audio DMA & TCP | Core 0: 40 FPS OLED Display");
}

// ── CORE 1: MAIN AUDIO & TCP ENGINE LOOP ────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // 1. Accept new TCP connection from PC (if Wi-Fi is connected)
  if (WiFi.status() == WL_CONNECTED && !client.connected()) {
    client = server.available();
    if (client) {
      client.setNoDelay(true); // Disable Nagle's algorithm for instant streaming!
      client.setTimeout(10);   // Fast timeout
      Serial.println("[TCP] PC Connected (TCP_NODELAY Enabled)!");
      strncpy(robotStatusText, "PC Connected!", sizeof(robotStatusText) - 1);
    }
  }

  // 2. Handle Incoming TCP Commands from PC
  if (client.connected() && client.available() >= 5) {
    char header_peek[6];
    client.readBytes(header_peek, 5);
    header_peek[5] = '\0';

    // ── TEXT COMMAND ────────────────────────────────────────────────────────
    if (strcmp(header_peek, "TEXT:") == 0) {
      String text = client.readStringUntil('\n');
      handleServerText(text);
    }

    // ── CHUNK STREAMING AUDIO COMMAND ───────────────────────────────────────
    else if (strcmp(header_peek, "CHUNK") == 0) {
      while (client.connected() && client.available() < 4) delay(1);
      uint8_t len_buf[4];
      client.readBytes(len_buf, 4);
      uint32_t chunk_len = ((uint32_t)len_buf[0] << 24) |
                           ((uint32_t)len_buf[1] << 16) |
                           ((uint32_t)len_buf[2] << 8)  |
                            (uint32_t)len_buf[3];

      if (chunk_len > 0) {
        isSpeaking = true;
        strncpy(robotStatusText, "AI Speaking...", sizeof(robotStatusText) - 1);
        lastChunkTime = millis();

        uint32_t total_got = 0;
        uint8_t mono_buf[1024];

        while (total_got < chunk_len && client.connected()) {
          int avail = client.available();
          if (avail > 0) {
            int to_read = min((uint32_t)avail, chunk_len - total_got);
            to_read = min((uint32_t)1024, (uint32_t)to_read);
            to_read = (to_read / 2) * 2;
            if (to_read == 0) { delay(1); continue; }

            int got = client.readBytes((char*)mono_buf, to_read);
            if (got > 0) {
              int16_t stereo_buf[1024];
              int16_t* mono_samples = (int16_t*)mono_buf;
              int samples = got / 2;
              for (int i = 0; i < samples; i++) {
                stereo_buf[i * 2]     = mono_samples[i];
                stereo_buf[i * 2 + 1] = mono_samples[i];
              }
              size_t wr = 0;
              i2s_write(I2S_SPK_PORT, stereo_buf, samples * 4, &wr, portMAX_DELAY);
              total_got += got;
            }
          } else {
            delay(1);
          }
        }
      } else {
        // chunk_len == 0 -> End of streaming
        uint8_t zero_flush[1024] = {0};
        for (int z = 0; z < 2; z++) {
          size_t zwr = 0;
          i2s_write(I2S_SPK_PORT, zero_flush, sizeof(zero_flush), &zwr, portMAX_DELAY);
        }
        delay(150);
        isSpeaking = false;
        strncpy(robotStatusText, "MEMO Ready", sizeof(robotStatusText) - 1);
      }
    }

    // ── AUDIO COMMAND (Direct Instant Speaker Playback) ─────────────────────
    else if (strcmp(header_peek, "AUDIO") == 0) {
      while (client.connected() && client.available() < 4) delay(1);

      uint8_t len_buf[4];
      client.readBytes(len_buf, 4);
      uint32_t audio_len = ((uint32_t)len_buf[0] << 24) |
                           ((uint32_t)len_buf[1] << 16) |
                           ((uint32_t)len_buf[2] << 8)  |
                            (uint32_t)len_buf[3];
      Serial.printf("[AUDIO] Ingesting %u bytes mono PCM...\n", audio_len);

      isSpeaking = true;
      strncpy(robotStatusText, "AI Speaking...", sizeof(robotStatusText) - 1);

      uint32_t total_received = 0;
      uint8_t mono_buf[1024];
      int16_t stereo_buf[1024];
      unsigned long start_recv = millis();

      while (total_received < audio_len && client.connected()) {
        int avail = client.available();
        if (avail > 0) {
          int to_read = min((uint32_t)avail, audio_len - total_received);
          to_read = min((uint32_t)1024, (uint32_t)to_read);
          to_read = (to_read / 2) * 2;
          if (to_read == 0) { delay(1); continue; }

          int got = client.readBytes((char*)mono_buf, to_read);
          if (got > 0) {
            int16_t* mono_samples = (int16_t*)mono_buf;
            int samples = got / 2;
            for (int i = 0; i < samples; i++) {
              stereo_buf[i * 2]     = mono_samples[i];
              stereo_buf[i * 2 + 1] = mono_samples[i];
            }
            size_t written = 0;
            i2s_write(I2S_SPK_PORT, stereo_buf, samples * 4, &written, portMAX_DELAY);
            total_received += got;
            start_recv = millis();
          }
        } else {
          delay(1);
          if (millis() - start_recv > 5000) break;
        }
      }

      Serial.printf("[AUDIO] Playback complete (%u / %u bytes)\n", total_received, audio_len);

      uint8_t zero_flush[1024] = {0};
      for (int z = 0; z < 2; z++) {
        size_t zwr = 0;
        i2s_write(I2S_SPK_PORT, zero_flush, sizeof(zero_flush), &zwr, portMAX_DELAY);
      }
      delay(150);
      isSpeaking = false;
      strncpy(robotStatusText, "MEMO Ready", sizeof(robotStatusText) - 1);
    }
  }

  // 3. CONTINUOUS MICROPHONE CAPTURE & DIRECT STREAMING TO PC
  // (Exact proven non-blocking logic of commit 3f29f20 — timeout = 0)
  if (!isSpeaking) {
    size_t bytesIn = 0;
    esp_err_t result = i2s_read(I2S_PORT, mic_buf, sizeof(mic_buf), &bytesIn, 0);
    if (result == ESP_OK && bytesIn > 0) {
      int samples = bytesIn / sizeof(int16_t);

      for (int i = 0; i < samples; i++) {
        int32_t s = (int32_t)mic_buf[i] * MIC_GAIN;
        mic_buf[i] = (int16_t)constrain(s, -32768, 32767);
      }

      // Update FFT waveform buffer for Core 0 display task
      if (samples <= FFT_SAMPLES) {
        memcpy(fft_wave, mic_buf, samples * sizeof(int16_t));
      }

      // Forward directly to TCP server if connected
      if (client.connected()) {
        client.write((uint8_t*)mic_buf, bytesIn);
      }
    }
  }

  // Safety watchdog: reset speaking state if no chunk received for 6 seconds
  if (isSpeaking && (now - lastChunkTime > 6000)) {
    isSpeaking = false;
    strncpy(robotStatusText, "MEMO Ready", sizeof(robotStatusText) - 1);
  }
}
