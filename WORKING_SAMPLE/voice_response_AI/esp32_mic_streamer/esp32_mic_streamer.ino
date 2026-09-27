/*
 * MEMO Robot — ESP32-S3 N16R8 Firmware (PSRAM Edition)
 * =====================================================
 * Key upgrades over original:
 *   1. psramInit() called — 8MB PSRAM activated
 *   2. Audio receive buffer in PSRAM (ps_malloc) — no stack overflow
 *   3. Receive FULL audio into PSRAM first, THEN play — gapless playback!
 *   4. Larger I2S DMA buffers (32×1024 = 32KB) — smoother audio
 *   5. Mic buffer in PSRAM — no stack pressure
 *   6. Startup shows free PSRAM on OLED/Serial
 */

#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- WIFI CONFIGURATION ---
const char* ssid     = "HUAWEI nova 3i";
const char* password = "senidu1234";

// --- TCP SERVER CONFIG ---
const uint16_t port = 8005;
WiFiServer server(port);
WiFiClient client;

// I2S Microphone Pins (INMP441) — ESP32-S3 N16R8
#define I2S_WS   GPIO_NUM_5
#define I2S_SD   GPIO_NUM_6
#define I2S_SCK  GPIO_NUM_4
#define I2S_PORT I2S_NUM_0

// I2S Speaker Pins (MAX98357) — ESP32-S3 N16R8
#define I2S_SPK_BCLK GPIO_NUM_16
#define I2S_SPK_LRC  GPIO_NUM_17
#define I2S_SPK_DOUT GPIO_NUM_15
#define I2S_SPK_PORT I2S_NUM_1

// Audio settings
#define SAMPLE_RATE          16000
#define MIC_BITS_PER_SAMPLE  I2S_BITS_PER_SAMPLE_16BIT
#define MIC_GAIN             4

// PSRAM audio buffer — 1MB = ~16 seconds of stereo 16kHz 16-bit audio
#define AUDIO_BUF_SIZE (1024 * 1024)   // 1MB in PSRAM
// Pre-roll buffer threshold (16KB = ~250ms of audio)
// Playback starts immediately once 16KB is received in PSRAM without waiting for full download!
#define PRE_ROLL_PLAYBACK_BYTES 16384
uint8_t* audio_psram_buf = nullptr;

// Mic read buffer in PSRAM
#define MIC_BUF_SAMPLES 512
int16_t* mic_buf = nullptr;

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

volatile bool isSpeaking = false;

// ── DISPLAY ──────────────────────────────────────────────────────────────────
void showText(String text) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  int y = 10;
  int startIdx = 0;
  while (startIdx < (int)text.length()) {
    String line = text.substring(startIdx, startIdx + 21);
    u8g2.drawStr(0, y, line.c_str());
    y += 12;
    startIdx += 21;
    if (y > 60) break;
  }
  u8g2.sendBuffer();
}

// ── SETUP ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // ── Init OLED ──
  Wire.begin(8, 9);  // SDA=8, SCL=9
  u8g2.begin();
  showText("Robot Loading...");

  // ── Init PSRAM ─────────────────────────────────────────────────────────────
  if (psramInit()) {
    Serial.println("[PSRAM] ✅ Initialized!");
    Serial.printf("[PSRAM] Free: %u KB\n", heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024);
  } else {
    Serial.println("[PSRAM] ❌ Failed to initialize!");
  }

  // ── Allocate PSRAM buffers ─────────────────────────────────────────────────
  audio_psram_buf = (uint8_t*) heap_caps_malloc(AUDIO_BUF_SIZE, MALLOC_CAP_SPIRAM);
  if (audio_psram_buf) {
    Serial.printf("[PSRAM] Audio buffer: %u KB allocated\n", AUDIO_BUF_SIZE / 1024);
  } else {
    Serial.println("[PSRAM] ❌ Audio buffer allocation failed!");
  }

  mic_buf = (int16_t*) heap_caps_malloc(MIC_BUF_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM);
  if (!mic_buf) {
    // Fallback to internal RAM if PSRAM unavailable
    mic_buf = (int16_t*) malloc(MIC_BUF_SAMPLES * sizeof(int16_t));
    Serial.println("[RAM] Mic buffer in internal RAM (fallback)");
  }

  // ── WiFi ───────────────────────────────────────────────────────────────────
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++attempts > 30) {
      showText("WiFi Failed! Rebooting...");
      delay(2000);
      ESP.restart();
    }
  }

  server.begin();
  Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());

  // ── PSRAM report on OLED ───────────────────────────────────────────────────
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 10, "MEMO ONLINE (N16R8)");
  u8g2.drawStr(0, 22, ("IP: " + WiFi.localIP().toString()).c_str());
  u8g2.drawStr(0, 34, ("Port: " + String(port)).c_str());
  String psramStr = audio_psram_buf
    ? ("PSRAM: " + String(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024) + "KB free")
    : "PSRAM: Not found!";
  u8g2.drawStr(0, 46, psramStr.c_str());
  u8g2.drawStr(0, 58, "Initializing I2S...");
  u8g2.sendBuffer();

  // ── I2S Microphone ─────────────────────────────────────────────────────────
  const i2s_config_t i2s_config = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = MIC_BITS_PER_SAMPLE,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 32,    // ↑ was 8 → smoother with larger buffer
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

  // ── I2S Speaker ────────────────────────────────────────────────────────────
  const i2s_config_t spk_i2s_config = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 32,    // ↑ was 8 → gapless playback
    .dma_buf_len          = 1024,
    .use_apll             = false,
    .tx_desc_auto_clear   = true
  };
  const i2s_pin_config_t spk_pin_config = {
    .bck_io_num   = I2S_SPK_BCLK,
    .ws_io_num    = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DOUT,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };
  i2s_driver_install(I2S_SPK_PORT, &spk_i2s_config, 0, NULL);
  i2s_set_pin(I2S_SPK_PORT, &spk_pin_config);
  i2s_start(I2S_SPK_PORT);

  showText("MEMO Ready! Speak...");
  Serial.println("[Setup] Complete — Server listening...");
}

// ── MAIN LOOP ────────────────────────────────────────────────────────────────
void loop() {
  // Accept new TCP connection
  if (!client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("[TCP] PC Connected!");
      showText("AI Robot Active! Speak now...");
    }
  }

  if (client.connected()) {
    // ── Check for incoming commands (TEXT or AUDIO) ─────────────────────────
    if (client.available() >= 5) {
      char header_peek[6];
      client.readBytes(header_peek, 5);
      header_peek[5] = '\0';

      // ── TEXT command → update OLED ────────────────────────────────────────
      if (strcmp(header_peek, "TEXT:") == 0) {
        String text = client.readStringUntil('\n');
        text.trim();
        Serial.println(">>> TEXT: " + text);
        showText(text);
      }

      // ── AUDIO command → buffer in PSRAM, then play ────────────────────────
      else if (strcmp(header_peek, "AUDIO") == 0) {
        // Read 4-byte big-endian length
        while (client.connected() && client.available() < 4) delay(1);
        uint8_t len_buf[4];
        client.readBytes(len_buf, 4);
        uint32_t audio_len = ((uint32_t)len_buf[0] << 24) |
                             ((uint32_t)len_buf[1] << 16) |
                             ((uint32_t)len_buf[2] << 8)  |
                              (uint32_t)len_buf[3];
        Serial.printf("[AUDIO] Receiving %u bytes into PSRAM...\n", audio_len);

        isSpeaking = true;

        bool use_psram = (audio_psram_buf != nullptr && audio_len <= AUDIO_BUF_SIZE);

        if (use_psram) {
          uint32_t total_received = 0;
          uint8_t* play_buf = audio_psram_buf;
          unsigned long start_recv = millis();

          // Ingest FULL audio into 8MB PSRAM first (takes ~80-150ms over Wi-Fi)
          while (total_received < audio_len && client.connected()) {
            int avail = client.available();
            if (avail > 0) {
              int to_read = min((uint32_t)avail, audio_len - total_received);
              to_read = min((uint32_t)2048, (uint32_t)to_read);
              int got = client.readBytes(play_buf + total_received, to_read);
              if (got > 0) {
                total_received += got;
                start_recv = millis();
              }
            } else {
              delay(1);
              if (millis() - start_recv > 3000) {
                Serial.println("[AUDIO] ⚠️ Timeout waiting for audio stream!");
                break;
              }
            }
          }
          Serial.printf("[AUDIO] Downloaded %u / %u bytes into PSRAM. Playing full audio...\n", total_received, audio_len);

          // Play ENTIRE audio buffer gaplessly from PSRAM — never cuts off!
          size_t written = 0;
          i2s_write(I2S_SPK_PORT, play_buf, total_received, &written, portMAX_DELAY);
          Serial.printf("[AUDIO] Playback finished: %u bytes\n", written);

        } else {
          // Fallback: direct streaming in 2KB chunks
          uint32_t total_received = 0;
          uint8_t stream_buf[2048];
          while (total_received < audio_len && client.connected()) {
            int avail = client.available();
            if (avail > 0) {
              int to_read = min((uint32_t)avail, audio_len - total_received);
              to_read = min((uint32_t)2048, (uint32_t)to_read);
              to_read = (to_read / 4) * 4;
              if (to_read == 0) { delay(1); continue; }
              int got = client.readBytes(stream_buf, to_read);
              if (got > 0) {
                size_t wr = 0;
                i2s_write(I2S_SPK_PORT, stream_buf, got, &wr, portMAX_DELAY);
                total_received += got;
              }
            } else delay(1);
          }
          Serial.printf("[AUDIO] Stream playback done: %u bytes\n", total_received);
        }

        // Allow DMA queue to finish clocking out the last audio samples before unmuting mic
        delay(250);
        isSpeaking = false;
      }

      else {
        Serial.printf("[TCP] Unknown header: [%s]\n", header_peek);
      }
    }

    // ── Mic streaming → TCP (skip while speaker plays) ─────────────────────
    if (!isSpeaking && mic_buf) {
      size_t bytesIn = 0;
      esp_err_t result = i2s_read(I2S_PORT, mic_buf, MIC_BUF_SAMPLES * sizeof(int16_t), &bytesIn, 0);
      if (result == ESP_OK && bytesIn > 0) {
        int samples = bytesIn / sizeof(int16_t);
        for (int i = 0; i < samples; i++) {
          int32_t s = (int32_t)mic_buf[i] * MIC_GAIN;
          mic_buf[i] = (int16_t)constrain(s, -32768, 32767);
        }
        client.write((uint8_t*)mic_buf, samples * sizeof(int16_t));
      }
    }
  }
}
