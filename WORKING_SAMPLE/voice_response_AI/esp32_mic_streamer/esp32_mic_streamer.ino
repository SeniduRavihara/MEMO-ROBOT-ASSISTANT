/*
 * ============================================================================
 *  MEMO AI Robot Assistant — Dual-Core Firmware
 *  (Core 1: Direct Non-Blocking Audio & TCP | Core 0: Expressive Robot Face)
 * ============================================================================
 *  Architecture:
 *    - Core 1 (Arduino loop — Dedicated Audio & TCP Engine):
 *        * 100% Dedicated to I2S Microphone (INMP441) and Speaker (MAX98357A)
 *        * Direct TCP streaming to Python (exact proven logic)
 *        * Direct instant streaming playback to speaker (zero PSRAM bottleneck)
 *        * ZERO display code on Core 1 -> Audio NEVER stutters, NEVER drops!
 *    - Core 0 (Background displayTask — Dedicated Face Animator):
 *        * Procedural robot eyes that blink naturally and look around
 *        * Animated talking mouth during speech (cycling speech frames)
 *        * Alert listening eyes when user talks, thinking glance when AI thinks
 *        * Completely decoupled from audio: 0% bottleneck!
 * ============================================================================
 */

#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

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

// I2C Pins (OLED Display & optional MPU6050)
#define I2C_SDA 8
#define I2C_SCL 9

// --- AUDIO CONFIGURATION ---
#define SAMPLE_RATE          16000
#define MIC_BITS_PER_SAMPLE  I2S_BITS_PER_SAMPLE_16BIT
#define MIC_GAIN             4
#define MIC_BUF_SAMPLES      512

// Static mic buffer (1024 bytes = 512 samples)
int16_t mic_buf[MIC_BUF_SAMPLES];

// --- DISPLAY (SSD1306 128x64 OLED) ---
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
TaskHandle_t displayTaskHandle = NULL;

// --- OPTIONAL MPU6050 GYROSCOPE ---
Adafruit_MPU6050 mpu;
bool mpuAvailable = false;

// --- ROBOT STATE MANAGEMENT ---
enum RobotState {
  STATE_SLEEPING,
  STATE_READY,
  STATE_LISTENING,
  STATE_THINKING
};

volatile RobotState robotState = STATE_SLEEPING;
volatile bool isSpeaking = false;
unsigned long lastChunkTime = 0;

// ── ROBOT FACE ANIMATION (Runs on Core 0) ───────────────────────────────────
void drawRobotFace() {
  unsigned long now = millis();

  // 0. Sleeping Face (Peaceful eye slits, calm breath, and animated Zzz)
  if (robotState == STATE_SLEEPING && !isSpeaking) {
    int breath = ((now / 1200) % 2 == 0) ? 0 : 1;
    int leftEyeX  = 22;
    int rightEyeX = 74;
    int eyeY      = 24 + breath;

    // Peaceful thin closed eye arcs
    u8g2.drawRBox(leftEyeX,  eyeY, 32, 5, 2);
    u8g2.drawRBox(rightEyeX, eyeY, 32, 5, 2);

    // Peaceful sleeping smile
    u8g2.drawHLine(58, 54, 12);
    u8g2.drawPixel(57, 53);
    u8g2.drawPixel(70, 53);

    // Floating animated "Zzz"
    int zStep = (now / 700) % 3;
    u8g2.setFont(u8g2_font_6x10_tf);
    if (zStep >= 0) u8g2.drawStr(108, 20, "z");
    if (zStep >= 1) u8g2.drawStr(115, 14, "z");
    if (zStep >= 2) u8g2.drawStr(121, 8,  "Z");
    return;
  }

  // 1. Saccades (Casual eye glance around room every 3-4s)
  static unsigned long lastSaccade = 0;
  static int gazeOffsetX = 0;
  static int gazeOffsetY = 0;
  if (!isSpeaking && robotState == STATE_READY && (now - lastSaccade > 3200)) {
    lastSaccade = now;
    int r = random(100);
    if (r < 55) {
      gazeOffsetX = 0;
      gazeOffsetY = 0;
    } else if (r < 78) {
      gazeOffsetX = -4; // Look slightly left
      gazeOffsetY = 0;
    } else {
      gazeOffsetX = 4;  // Look slightly right
      gazeOffsetY = 0;
    }
  }

  // Thinking state: glance up-right
  if (robotState == STATE_THINKING) {
    gazeOffsetX = 5;
    gazeOffsetY = -4;
  }

  // 2. Autonomic Blinking (Smooth squash & stretch every ~3.5s)
  static unsigned long lastBlinkTime = 0;
  static bool isBlinking = false;
  static unsigned long blinkStart = 0;

  if (!isBlinking && (now - lastBlinkTime > 3600)) {
    if (random(100) < 85) {
      isBlinking = true;
      blinkStart = now;
    } else {
      lastBlinkTime = now - 1800;
    }
  }

  int eyeH = 34;
  int eyeW = 32;
  int eyeR = 8;
  int eyeY = 10;

  if (isBlinking) {
    unsigned long elapsed = now - blinkStart;
    if (elapsed < 70) {
      eyeH = map(elapsed, 0, 70, 34, 4);
    } else if (elapsed < 120) {
      eyeH = 4;
    } else if (elapsed < 190) {
      eyeH = map(elapsed, 120, 190, 4, 34);
    } else {
      isBlinking = false;
      lastBlinkTime = now;
      eyeH = 34;
    }
    eyeR = min(eyeH / 2, 8);
  }

  // Listening state: alert wide eyes
  if (robotState == STATE_LISTENING && !isBlinking) {
    eyeH = 38;
    eyeW = 34;
    eyeY = 8;
  }

  // Speaking state: subtle rhythmic eye bounce
  int bounceY = 0;
  if (isSpeaking && !isBlinking) {
    bounceY = ((now / 130) % 2 == 0) ? -2 : 0;
  }

  // Compute eye positions
  int leftEyeX  = 22 + gazeOffsetX;
  int rightEyeX = 74 + gazeOffsetX;
  int curEyeY   = eyeY + gazeOffsetY + bounceY;

  // Draw Left and Right Eyes (Smooth rounded filled rectangles)
  u8g2.drawRBox(leftEyeX, curEyeY + (34 - eyeH) / 2, eyeW, eyeH, eyeR);
  u8g2.drawRBox(rightEyeX, curEyeY + (34 - eyeH) / 2, eyeW, eyeH, eyeR);

  // 3. Draw Mouth (Impressions of Talking!)
  if (isSpeaking) {
    // 4-frame talking mouth animation (cycles every 110ms)
    int mouthFrame = (now / 110) % 4;
    int mcX = 64;
    int mcY = 54;

    switch (mouthFrame) {
      case 0: // Small open
        u8g2.drawRBox(mcX - 6, mcY - 2, 12, 4, 2);
        break;
      case 1: // Medium open
        u8g2.drawRBox(mcX - 9, mcY - 4, 18, 8, 3);
        break;
      case 2: // Wide open speech
        u8g2.drawRBox(mcX - 11, mcY - 6, 22, 12, 4);
        break;
      case 3: // Medium open
        u8g2.drawRBox(mcX - 9, mcY - 4, 18, 8, 3);
        break;
    }
  } else if (robotState == STATE_THINKING) {
    // Thinking dots below eyes
    int dotFrame = (now / 220) % 3;
    u8g2.drawDisc(58, 54, 2);
    if (dotFrame >= 1) u8g2.drawDisc(64, 54, 2);
    if (dotFrame >= 2) u8g2.drawDisc(70, 54, 2);
  } else if (robotState == STATE_LISTENING) {
    // Attentive smile
    u8g2.drawHLine(58, 54, 12);
    u8g2.drawPixel(57, 53);
    u8g2.drawPixel(70, 53);
  } else {
    // Calm resting smile
    u8g2.drawHLine(58, 54, 12);
  }
}

// ── CORE 0 DISPLAY TASK (Dedicated Face Animator) ───────────────────────────
void displayTask(void* pvParameters) {
  TickType_t xLastWakeTime = xTaskGetTickCount();
  const TickType_t xFrequency = pdMS_TO_TICKS(35); // ~28 FPS (smooth & zero ripple)

  while (true) {
    u8g2.clearBuffer();
    drawRobotFace();
    u8g2.sendBuffer();
    vTaskDelayUntil(&xLastWakeTime, xFrequency);
  }
}

// ── TEXT DISPLAY HELPER (Boot Only) ─────────────────────────────────────────
void showBootText(String text) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  int y = 16;
  int startIdx = 0;
  while (startIdx < (int)text.length()) {
    String line = text.substring(startIdx, startIdx + 21);
    u8g2.drawStr(0, y, line.c_str());
    y += 13;
    startIdx += 21;
    if (y > 60) break;
  }
  u8g2.sendBuffer();
}

// ── SETUP ───────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // 1. Initialize I2C (400kHz Fast Mode)
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  // 2. Initialize OLED Display
  u8g2.begin();
  showBootText("MEMO Booting...");

  // 3. Connect to Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);
  WiFi.begin(ssid, password);

  showBootText("Connecting WiFi:\n" + String(ssid));

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++attempts > 25) {
      Serial.println("\n[WiFi] Connection timeout.");
      showBootText("WiFi Timeout!");
      delay(1200);
      break;
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    server.begin();
    Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    showBootText("WiFi Connected!\nIP: " + WiFi.localIP().toString());
    delay(1000);
  }

  // 4. Initialize I2S Microphone (INMP441 — Port 0)
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
    showBootText("Mic I2S Fail!");
    return;
  }
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);

  // 5. Initialize I2S Speaker (MAX98357A — Port 1)
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

  // 6. Optional MPU6050
  if (mpu.begin()) {
    mpuAvailable = true;
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("[MPU6050] ✅ IMU detected.");
  } else {
    mpuAvailable = false;
    Serial.println("[MPU6050] ℹ️ IMU not detected (optional).");
  }

  // 7. Launch Face Animator on Core 0
  xTaskCreatePinnedToCore(
    displayTask,
    "displayTask",
    4096,
    NULL,
    1,
    &displayTaskHandle,
    0
  );

  Serial.println("[SYSTEM] ✅ MEMO Robot Face and Audio Engine Ready!");
}

// ── CORE 1 AUDIO & TCP LOOP ─────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // 1. ACCEPT TCP CONNECTION
  if (!client || !client.connected()) {
    client = server.available();
    if (client) {
      client.setNoDelay(true);
      Serial.println("[TCP] Client connected!");
      robotState = STATE_SLEEPING;
      isSpeaking = false;
    }
  }

  // 2. PROCESS INCOMING COMMANDS FROM PYTHON SERVER
  if (client && client.connected() && client.available() >= 5) {
    char header_peek[6];
    client.readBytes(header_peek, 5);
    header_peek[5] = '\0';

    // ── TEXT COMMAND ─────────────────────────────────────────────────────────
    if (strcmp(header_peek, "TEXT:") == 0) {
      String text = client.readStringUntil('\n');
      text.trim();
      Serial.println(">>> SERVER TEXT: " + text);

      if (text.startsWith("Listening")) {
        robotState = STATE_LISTENING;
      } else if (text.startsWith("Thinking")) {
        robotState = STATE_THINKING;
      } else if (text.startsWith("Sleeping") || text.startsWith("Sleep")) {
        robotState = STATE_SLEEPING;
      } else if (text.startsWith("AI Robot Active") || text.startsWith("MEMO Ready")) {
        robotState = STATE_READY;
      }
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
        if (robotState != STATE_SLEEPING) {
          robotState = STATE_READY;
        }
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
      if (robotState != STATE_SLEEPING) {
        robotState = STATE_READY;
      }
    }
  }

  // 3. CONTINUOUS MICROPHONE CAPTURE & DIRECT STREAMING TO PC
  // (Zero display interference -> mic audio is pristine!)
  if (!isSpeaking) {
    size_t bytesIn = 0;
    esp_err_t result = i2s_read(I2S_PORT, mic_buf, sizeof(mic_buf), &bytesIn, 0);
    if (result == ESP_OK && bytesIn > 0) {
      int samples = bytesIn / sizeof(int16_t);

      for (int i = 0; i < samples; i++) {
        int32_t s = (int32_t)mic_buf[i] * MIC_GAIN;
        mic_buf[i] = (int16_t)constrain(s, -32768, 32767);
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
    if (robotState != STATE_SLEEPING) {
      robotState = STATE_READY;
    }
  }
}
