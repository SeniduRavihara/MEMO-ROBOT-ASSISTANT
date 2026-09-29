/*
 * ============================================================================
 *  MEMO AI Robot Assistant — ESP32-S3 N16R8 Firmware
 *  (Vector-Style Expressive Eye Engine + Local Voice Reactivity + Live Pipeline)
 * ============================================================================
 *  Features:
 *    1. Full-screen Vector-style procedural eyes (SSD1306 OLED via U8g2)
 *    2. LOCAL SOUND & VOICE REACTIVITY (Works 100% standalone, no PC needed!):
 *         - Voice Activity Detection (VAD) with adaptive room noise floor
 *         - Talks to MEMO  -> Eyes perk up into LISTENING or CURIOUS with real-time audio pulse
 *         - Finishes talking -> Cheerful smile (^ ^) and natural blink
 *         - Claps / Loud noise -> Startled SURPRISED eyes pop wide open!
 *         - Quiet room (30s)  -> Eyes slowly droop to SLEEPY (- -)
 *         - Make a sound      -> Snaps awake instantly!
 *    3. PC / GEMINI CLOUD INTEGRATION (When connected):
 *         - Seamlessly handles live voice conversations with LLM
 *         - Thinking... -> Glancing up-right & pulse (EMOTION_THINKING)
 *         - Speaking... -> Speech bounce + animated mouth (EMOTION_SPEAKING)
 *         - Post-speech -> Emotion based on AI reply sentiment
 *    4. MPU6050 Gyro/IMU integration:
 *         - Physically tracks room tilt with his gaze
 *         - Shaking MEMO triggers DIZZY spinning stars (EMOTION_DIZZY)
 *    5. Gapless 8MB PSRAM audio buffering (ps_malloc) for MAX98357A I2S speaker
 *    6. Chunked playback with non-blocking eye animation (~45 FPS)
 * ============================================================================
 */

#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "MemoEyes.h"

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

// I2C Pins (Shared by OLED and MPU6050)
#define I2C_SDA 8
#define I2C_SCL 9

// --- AUDIO CONFIGURATION ---
#define SAMPLE_RATE          16000
#define MIC_BITS_PER_SAMPLE  I2S_BITS_PER_SAMPLE_16BIT
#define MIC_GAIN             4

// PSRAM audio buffer (1MB = ~16s of 16kHz 16-bit stereo)
#define AUDIO_BUF_SIZE (1024 * 1024)
uint8_t* audio_psram_buf = nullptr;

// Mic read buffer (512 samples = 32ms of audio)
#define MIC_BUF_SAMPLES 512
int16_t* mic_buf = nullptr;

// --- DISPLAY & VECTOR EYES ---
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
MemoEyes eyes;

// --- OPTIONAL MPU6050 GYROSCOPE ---
Adafruit_MPU6050 mpu;
bool mpuAvailable = false;

// --- STATE MANAGEMENT ---
volatile bool isSpeaking = false;
EyeEmotion postSpeechEmotion = EMOTION_HAPPY;
unsigned long emotionHoldUntil = 0;
unsigned long lastEyeRender = 0;
unsigned long lastChunkTime = 0;

// --- LOCAL SOUND INTELLIGENCE STATE ---
float noiseFloor = 200.0f;
unsigned long lastSpeechTime = 0;
unsigned long speechStartTime = 0;
bool userSpeakingLocally = false;
bool isSleepy = false;

// ── RENDER EYES NON-BLOCKING (~45 FPS) ──────────────────────────────────────
void renderEyes() {
  unsigned long now = millis();
  if (now - lastEyeRender >= 22) { // 22ms = ~45 FPS
    lastEyeRender = now;
    eyes.update();
    u8g2.clearBuffer();
    eyes.render(u8g2);
    u8g2.sendBuffer();
  }
}

// ── TEXT DISPLAY HELPER (Boot & Errors Only) ────────────────────────────────
void showText(String text) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  int y = 14;
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

// ── LOCAL VOICE ACTIVITY & SOUND INTELLIGENCE ───────────────────────────────
void processLocalAudio(float rms, int16_t peak, unsigned long now) {
  // 1. Update adaptive room noise floor during quiet periods
  if (rms < noiseFloor * 1.4f) {
    noiseFloor = 0.985f * noiseFloor + 0.015f * rms;
    if (noiseFloor < 80.0f)   noiseFloor = 80.0f;
    if (noiseFloor > 1000.0f) noiseFloor = 1000.0f;
  }

  // 2. Sudden Loud Noise (Clap, Snap, Shout, Desk Slap) -> SURPRISED!
  float clapThreshold = noiseFloor + 2200.0f;
  if (rms > clapThreshold || peak > 22000) {
    eyes.setEmotion(EMOTION_SURPRISED);
    emotionHoldUntil = now + 1600; // Hold wide surprised eyes for 1.6s
    lastSpeechTime = now;
    isSleepy = false;
    Serial.printf("[Local Audio] 💥 Loud noise detected! RMS: %.0f, Peak: %d\n", rms, peak);
    return;
  }

  // 3. Human Speech Detection
  float speechThreshold = max(350.0f, noiseFloor * 2.2f);
  if (rms > speechThreshold) {
    lastSpeechTime = now;
    eyes.setAudioLevel((uint16_t)rms); // Real-time pulse with voice volume!

    // If robot was asleep, wake up immediately!
    if (isSleepy) {
      isSleepy = false;
      eyes.setEmotion(EMOTION_HAPPY);
      emotionHoldUntil = now + 2000;
      eyes.blink();
      Serial.println("[Local Audio] ☀️ Heard voice! Snapping awake from sleep.");
      return;
    }

    // New utterance started
    if (!userSpeakingLocally) {
      userSpeakingLocally = true;
      speechStartTime = now;

      // Only change emotion if not in middle of server thinking/speaking
      if (eyes.getEmotion() != EMOTION_THINKING && eyes.getEmotion() != EMOTION_SPEAKING) {
        // Randomly choose between attentive listening and curious raised eyebrow
        if (random(100) < 65) {
          eyes.setEmotion(EMOTION_LISTENING);
        } else {
          eyes.setEmotion(EMOTION_CURIOUS);
        }
        eyes.center();
      }
      Serial.printf("[Local Audio] 🗣️ Speech detected! RMS: %.0f (Noise floor: %.0f)\n", rms, noiseFloor);
    }
  } 
  else {
    // 4. Silence Handling
    if (userSpeakingLocally) {
      // If user has stopped talking for > 850ms
      if (now - lastSpeechTime > 850) {
        userSpeakingLocally = false;
        unsigned long speechDuration = lastSpeechTime - speechStartTime;

        // If the utterance was longer than 200ms (ignoring brief mic clicks)
        if (speechDuration > 200) {
          Serial.printf("[Local Audio] ✅ Speech finished (%lums).\n", speechDuration);

          // If standalone (no PC connected to answer), acknowledge with a smile and blink!
          if (!client.connected() && eyes.getEmotion() != EMOTION_THINKING && eyes.getEmotion() != EMOTION_SPEAKING) {
            eyes.setEmotion(EMOTION_HAPPY);
            emotionHoldUntil = now + 3000;
            eyes.blink();
          }
        }
      }
    }

    // 5. Boredom / Sleepiness: If room is silent for > 30 seconds
    if (now - lastSpeechTime > 30000 && !isSleepy && !client.connected() && emotionHoldUntil == 0) {
      isSleepy = true;
      eyes.setEmotion(EMOTION_SLEEPY);
      Serial.println("[Local Audio] 💤 Room quiet for 30s. Going to sleep (- -)...");
    }
  }
}

// ── SERVER COMMAND PARSER (When PC is Connected) ────────────────────────────
void handleServerText(String text) {
  text.trim();
  Serial.println(">>> SERVER TEXT: " + text);

  if (text.startsWith("Listening")) {
    eyes.setEmotion(EMOTION_LISTENING);
    emotionHoldUntil = 0;
  } 
  else if (text.startsWith("Thinking")) {
    eyes.setEmotion(EMOTION_THINKING);
    emotionHoldUntil = 0;
  } 
  else if (text.startsWith("AI Robot Active")) {
    eyes.setEmotion(EMOTION_HAPPY);
    emotionHoldUntil = millis() + 2500;
  } 
  else {
    // AI response text -> analyze sentiment to pick post-speech reaction
    String lower = text;
    lower.toLowerCase();

    if (lower.indexOf("sorry") >= 0 || lower.indexOf("sad") >= 0 || lower.indexOf("bad") >= 0) {
      postSpeechEmotion = EMOTION_SAD;
    } else if (lower.indexOf("happy") >= 0 || lower.indexOf("great") >= 0 || lower.indexOf("love") >= 0 ||
               lower.indexOf("glad") >= 0 || lower.indexOf("awesome") >= 0 || lower.indexOf("haha") >= 0 ||
               lower.indexOf("nice") >= 0 || lower.indexOf("sure") >= 0 || lower.indexOf("welcome") >= 0) {
      postSpeechEmotion = EMOTION_HAPPY;
    } else if (lower.indexOf("?") >= 0 || lower.indexOf("why") >= 0 || lower.indexOf("curious") >= 0 || lower.indexOf("how") >= 0) {
      postSpeechEmotion = EMOTION_CURIOUS;
    } else if (lower.indexOf("wow") >= 0 || lower.indexOf("whoa") >= 0 || lower.indexOf("really") >= 0) {
      postSpeechEmotion = EMOTION_SURPRISED;
    } else {
      postSpeechEmotion = EMOTION_HAPPY;
    }
  }
}

// ── SETUP ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // 1. Initialize I2C (400kHz Fast Mode)
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  // 2. Initialize OLED Display
  u8g2.begin();
  showText("MEMO Booting...");

  // 3. Initialize PSRAM (8MB Octal PSRAM)
  if (psramInit()) {
    Serial.println("[PSRAM] ✅ Initialized!");
    Serial.printf("[PSRAM] Free: %u KB\n", heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024);
  } else {
    Serial.println("[PSRAM] ❌ Failed to initialize!");
  }

  // 4. Allocate audio buffers in PSRAM
  audio_psram_buf = (uint8_t*) heap_caps_malloc(AUDIO_BUF_SIZE, MALLOC_CAP_SPIRAM);
  if (audio_psram_buf) {
    Serial.printf("[PSRAM] Audio buffer: %u KB allocated\n", AUDIO_BUF_SIZE / 1024);
  } else {
    Serial.println("[PSRAM] ❌ Audio buffer allocation failed!");
  }

  mic_buf = (int16_t*) heap_caps_malloc(MIC_BUF_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM);
  if (!mic_buf) {
    mic_buf = (int16_t*) malloc(MIC_BUF_SAMPLES * sizeof(int16_t));
    Serial.println("[RAM] Mic buffer in internal RAM (fallback)");
  }

  // 5. Connect to Wi-Fi
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
      Serial.println("\n[WiFi] Connection timeout. Proceeding in Autonomous Standalone mode...");
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

  // 6. Initialize I2S Microphone (INMP441 — Port 0)
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

  // 7. Initialize I2S Speaker (MAX98357A — Port 1)
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

  // 8. Try initializing MPU6050 (optional)
  if (mpu.begin()) {
    mpuAvailable = true;
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("[MPU6050] ✅ IMU detected: Tilt tracking active!");
  } else {
    mpuAvailable = false;
    Serial.println("[MPU6050] ℹ️ IMU not detected (optional).");
  }

  // 9. Initialize Vector Eye Engine
  eyes.begin();
  eyes.setEmotion(EMOTION_HAPPY);
  emotionHoldUntil = millis() + 2500;
  lastSpeechTime = millis();

  Serial.println("[Setup] Complete — MEMO is alive and listening!");
}

// ── MAIN LOOP ────────────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // 1. Accept new TCP connection from PC (if Wi-Fi is connected)
  if (WiFi.status() == WL_CONNECTED && !client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("[TCP] PC Connected!");
      eyes.setEmotion(EMOTION_HAPPY);
      emotionHoldUntil = now + 2500;
      isSleepy = false;
    }
  }

  // 2. Handle Incoming TCP Commands from PC
  if (client.connected()) {
    if (client.available() >= 5) {
      char header_peek[6];
      client.readBytes(header_peek, 5);
      header_peek[5] = '\0';

      // ── TEXT COMMAND ───────────────────────────────────────────────────────
      if (strcmp(header_peek, "TEXT:") == 0) {
        String text = client.readStringUntil('\n');
        handleServerText(text);
      }

      // ── CHUNK COMMAND (Real-time Streaming TTS Audio from PC) ─────────────
      else if (strcmp(header_peek, "CHUNK") == 0) {
        unsigned long startWaitLen = millis();
        while (client.connected() && client.available() < 4) {
          renderEyes();
          delay(1);
          if (millis() - startWaitLen > 2000) break;
        }

        if (client.available() >= 4) {
          uint8_t len_buf[4];
          client.readBytes(len_buf, 4);
          uint32_t chunk_len = ((uint32_t)len_buf[0] << 24) |
                               ((uint32_t)len_buf[1] << 16) |
                               ((uint32_t)len_buf[2] << 8)  |
                                (uint32_t)len_buf[3];

          lastChunkTime = millis();

          if (chunk_len > 0) {
            isSpeaking = true;
            eyes.setEmotion(EMOTION_SPEAKING);

            uint32_t total_received = 0;
            uint8_t stream_buf[2048];
            unsigned long start_recv = millis();

            while (total_received < chunk_len && client.connected()) {
              int avail = client.available();
              if (avail > 0) {
                int to_read = min((uint32_t)avail, chunk_len - total_received);
                to_read = min((uint32_t)2048, (uint32_t)to_read);
                to_read = (to_read / 4) * 4;
                if (to_read == 0) { delay(1); continue; }
                int got = client.readBytes((char*)stream_buf, to_read);
                if (got > 0) {
                  size_t wr = 0;
                  i2s_write(I2S_SPK_PORT, stream_buf, got, &wr, portMAX_DELAY);
                  total_received += got;
                  start_recv = millis();
                  lastChunkTime = millis();
                }
              } else {
                delay(1);
                if (millis() - start_recv > 3000) {
                  Serial.println("[CHUNK] ⚠️ Timeout waiting for chunk data!");
                  break;
                }
              }
              renderEyes();
            }
          } else {
            // chunk_len == 0 signals End of Audio Stream
            // Smoothly push zeros through DMA to flush remaining audio and prevent speaker pop/radio clicks
            uint8_t zero_flush[2048] = {0};
            for (int z = 0; z < 4; z++) {
              size_t zwr = 0;
              i2s_write(I2S_SPK_PORT, zero_flush, sizeof(zero_flush), &zwr, portMAX_DELAY);
            }
            delay(250); // Allow hardware DMA to clock out the zero tail cleanly
            isSpeaking = false;
            eyes.setEmotion(postSpeechEmotion);
            emotionHoldUntil = millis() + 3500;
            lastSpeechTime = millis();
            Serial.println("[CHUNK] Streaming audio finished.");
          }
        }
      }

      // ── AUDIO COMMAND (Download into PSRAM & play with animated eyes) ──────
      else if (strcmp(header_peek, "AUDIO") == 0) {
        while (client.connected() && client.available() < 4) {
          renderEyes();
          delay(1);
        }

        uint8_t len_buf[4];
        client.readBytes(len_buf, 4);
        uint32_t audio_len = ((uint32_t)len_buf[0] << 24) |
                             ((uint32_t)len_buf[1] << 16) |
                             ((uint32_t)len_buf[2] << 8)  |
                              (uint32_t)len_buf[3];
        Serial.printf("[AUDIO] Receiving %u bytes into PSRAM...\n", audio_len);

        isSpeaking = true;
        eyes.setEmotion(EMOTION_SPEAKING);

        bool use_psram = (audio_psram_buf != nullptr && audio_len <= AUDIO_BUF_SIZE);

        if (use_psram) {
          uint32_t total_received = 0;
          uint8_t* play_buf = audio_psram_buf;
          unsigned long start_recv = millis();

          // High-speed ingest directly into PSRAM (no I2C screen blocking during download)
          while (total_received < audio_len && client.connected()) {
            int avail = client.available();
            if (avail > 0) {
              int to_read = min((uint32_t)avail, audio_len - total_received);
              int got = client.read(play_buf + total_received, to_read);
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

          Serial.printf("[AUDIO] Downloaded %u / %u bytes into PSRAM. Playing...\n", total_received, audio_len);

          // Play in 2048-byte chunks (32ms of 16kHz stereo) so eyes bounce during speech!
          uint32_t offset = 0;
          while (offset < total_received) {
            size_t chunk = min((uint32_t)2048, total_received - offset);
            size_t written = 0;
            i2s_write(I2S_SPK_PORT, play_buf + offset, chunk, &written, portMAX_DELAY);
            offset += written;
            renderEyes();
          }
          Serial.printf("[AUDIO] Playback finished: %u bytes\n", offset);

        } else {
          // Direct streaming fallback
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
            renderEyes();
          }
        }

        // Push silence zeros to cleanly settle DAC and allow DMA queue to finish clocking out
        uint8_t zero_flush[2048] = {0};
        for (int z = 0; z < 4; z++) {
          size_t zwr = 0;
          i2s_write(I2S_SPK_PORT, zero_flush, sizeof(zero_flush), &zwr, portMAX_DELAY);
        }
        delay(250);
        isSpeaking = false;

        // Transition to post-speech emotion (e.g. Happy ^ ^)
        eyes.setEmotion(postSpeechEmotion);
        emotionHoldUntil = millis() + 3500;
        lastSpeechTime = millis();
      }

      else {
        Serial.printf("[TCP] Unknown header: [%s]\n", header_peek);
      }
    }
  }

  // 3. CONTINUOUS MICROPHONE CAPTURE & LOCAL INTELLIGENCE
  // Runs whether PC is connected or disconnected!
  if (!isSpeaking && mic_buf) {
    size_t bytesIn = 0;
    esp_err_t result = i2s_read(I2S_PORT, mic_buf, MIC_BUF_SAMPLES * sizeof(int16_t), &bytesIn, 0);
    if (result == ESP_OK && bytesIn > 0) {
      int samples = bytesIn / sizeof(int16_t);

      int64_t sum_squares = 0;
      int16_t peak = 0;

      for (int i = 0; i < samples; i++) {
        int32_t s = (int32_t)mic_buf[i] * MIC_GAIN;
        s = constrain(s, -32768, 32767);
        mic_buf[i] = (int16_t)s;

        int16_t abs_s = abs(mic_buf[i]);
        if (abs_s > peak) peak = abs_s;
        sum_squares += (int32_t)mic_buf[i] * (int32_t)mic_buf[i];
      }

      float rms = sqrtf((float)(sum_squares / samples));

      // Forward to TCP server if connected
      if (client.connected()) {
        client.write((uint8_t*)mic_buf, samples * sizeof(int16_t));
      }

      // Run Local Sound Intelligence on the ESP32!
      processLocalAudio(rms, peak, now);
    }
  }

  // 4. Emotion Hold Timer (reverts to Neutral after reactions)
  if (emotionHoldUntil > 0 && now > emotionHoldUntil && !isSpeaking) {
    if (!isSleepy) {
      eyes.setEmotion(EMOTION_NEUTRAL);
    }
    emotionHoldUntil = 0;
  }

  // Safety watchdog: reset speaking state if no chunk received for 6 seconds
  if (isSpeaking && (now - lastChunkTime > 6000)) {
    isSpeaking = false;
    eyes.setEmotion(EMOTION_NEUTRAL);
    Serial.println("[CHUNK] ⚠️ Safety watchdog: reset speaking state");
  }

  // 5. MPU6050 Gyro Tilt & Shake Handling
  if (mpuAvailable && !isSpeaking && (eyes.getEmotion() == EMOTION_NEUTRAL || eyes.getEmotion() == EMOTION_HAPPY)) {
    static unsigned long lastImuRead = 0;
    if (now - lastImuRead > 35) {
      lastImuRead = now;
      sensors_event_t a, g, temp;
      mpu.getEvent(&a, &g, &temp);

      float totalAccel = sqrtf(a.acceleration.x * a.acceleration.x +
                               a.acceleration.y * a.acceleration.y +
                               a.acceleration.z * a.acceleration.z);
      if (totalAccel > 22.0f && eyes.getEmotion() != EMOTION_DIZZY) {
        eyes.setEmotion(EMOTION_DIZZY);
        emotionHoldUntil = now + 3000;
        isSleepy = false;
        lastSpeechTime = now;
      } else {
        int8_t gazeX = constrain((int)(-a.acceleration.y * 2.2f), -14, 14);
        int8_t gazeY = constrain((int)(a.acceleration.x * 2.2f), -8, 8);
        eyes.look(gazeX, gazeY);
      }
    }
  }

  // 6. Always Keep Eyes Animating at ~45 FPS
  renderEyes();
}
