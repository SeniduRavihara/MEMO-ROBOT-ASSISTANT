// ROBOT AI ASSISTANT: PORT 0 MASTER SWITCH (SMOOTH OPTIMIZED)
#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- CONFIG ---
const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";
const uint16_t port  = 8006;
const char* pc_ip    = "192.168.43.32"; 

// I2S PORT (EVERYTHING ON PORT 0)
#define I2S_PORT I2S_NUM_0

// MIC PINS (Original)
#define I2S_MIC_SCK  GPIO_NUM_26
#define I2S_MIC_WS   GPIO_NUM_25
#define I2S_MIC_SD   GPIO_NUM_32

// SPK PINS (Original)
#define I2S_SPK_BCLK GPIO_NUM_14
#define I2S_SPK_LRC  GPIO_NUM_27
#define I2S_SPK_DOUT GPIO_NUM_33

#define MIC_SAMPLE_RATE 16000
#define SPK_SAMPLE_RATE 24000 
#define MIC_GAIN    4

// FreeRTOS Queues
QueueHandle_t micQueue;
QueueHandle_t spkQueue;

WiFiClient client;
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

struct AudioChunk {
  uint8_t data[1024];
  size_t len;
};

volatile bool isRobotSpeaking = false;
volatile bool isMicActive = false;
volatile bool isSpkActive = false;
volatile bool isHwSwitching = false; 
uint32_t lastVoiceTime = 0; // The Watchdog Timer

void showText(String t1, String t2 = "", String t3 = "") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 15, t1.c_str());
  u8g2.drawStr(0, 35, t2.c_str());
  u8g2.drawStr(0, 55, t3.c_str());
  u8g2.sendBuffer();
}

// --- OPTIMIZED HARDWARE SWITCHER ---
void startMicHardware() {
  if (isMicActive) return;
  isHwSwitching = true; // Signal tasks to pause hardware access
  vTaskDelay(100 / portTICK_PERIOD_MS); // Allow pending i2s_read/write to finish

  if (isSpkActive) { 
    i2s_stop(I2S_PORT); 
    i2s_driver_uninstall(I2S_PORT); 
    isSpkActive = false; 
    vTaskDelay(50 / portTICK_PERIOD_MS); // Hardware Breath
  }
  
  const i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = MIC_SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 12, // Increased for stability
    .dma_buf_len          = 1024,
    .use_apll             = false
  };
  i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
  const i2s_pin_config_t pins = { .bck_io_num = I2S_MIC_SCK, .ws_io_num = I2S_MIC_WS, .data_out_num = I2S_PIN_NO_CHANGE, .data_in_num = I2S_MIC_SD };
  i2s_set_pin(I2S_PORT, &pins);
  i2s_start(I2S_PORT);
  isMicActive = true;
  isHwSwitching = false; // Signal tasks to resume
  Serial.println("[HW] Mic On P0");
}

void startSpkHardware() {
  if (isSpkActive) return;
  isHwSwitching = true; // Signal tasks to pause hardware access
  vTaskDelay(100 / portTICK_PERIOD_MS); // Allow pending i2s_read/write to finish

  if (isMicActive) { 
    i2s_stop(I2S_PORT); 
    i2s_driver_uninstall(I2S_PORT); 
    isMicActive = false; 
    vTaskDelay(50 / portTICK_PERIOD_MS); // Hardware Breath
  }

  const i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SPK_SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 12, // Increased for stability
    .dma_buf_len          = 1024,
    .use_apll             = false,
    .tx_desc_auto_clear = true
  };
  i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
  const i2s_pin_config_t pins = { .bck_io_num = I2S_SPK_BCLK, .ws_io_num = I2S_SPK_LRC, .data_out_num = I2S_SPK_DOUT, .data_in_num = I2S_PIN_NO_CHANGE };
  i2s_set_pin(I2S_PORT, &pins);
  i2s_start(I2S_PORT);
  isSpkActive = true;
  isHwSwitching = false; // Signal tasks to resume
  Serial.println("[HW] Spk On P0");
}

// --- TASK 1: NETWORK HANDLER (Core 0) ---
void networkTask(void *pvParameters) {
  while (true) {
    if (!client.connected()) {
      if (client.connect(pc_ip, port)) {
        Serial.println("Net: Connected!");
      } else { vTaskDelay(2000 / portTICK_PERIOD_MS); continue; }
    }

    // 1. Send Mic Data (Streaming if allowed)
    AudioChunk micChunk;
    if (xQueueReceive(micQueue, &micChunk, 0) == pdTRUE) {
      if (client.connected()) {
        client.write(micChunk.data, micChunk.len);
      }
    }

    // 2. Receive Speaker Data
    if (client.available() >= 5) {
      char header[6];
      client.readBytes(header, 5); header[5] = '\0';

      if (strcmp(header, "AUDIO") == 0) {
        isRobotSpeaking = true;
        xQueueReset(micQueue); // Flush old mic data immediately
        
        uint8_t len_buf[4];
        while (client.connected() && client.available() < 4) { vTaskDelay(1); }
        client.readBytes(len_buf, 4);
        uint32_t audio_len = ((uint32_t)len_buf[0] << 24) | ((uint32_t)len_buf[1] << 16) | ((uint32_t)len_buf[2] << 8) | (uint32_t)len_buf[3];
        
        uint32_t received = 0;
        while (received < audio_len && client.connected()) {
          int avail = client.available();
          if (avail > 0) {
            AudioChunk spkChunk;
            int to_read = min((uint32_t)avail, (uint32_t)1024);
            to_read = min((uint32_t)to_read, audio_len - received);
            to_read = (to_read / 4) * 4;
            spkChunk.len = client.readBytes(spkChunk.data, to_read);
            if (spkChunk.len > 0) {
              xQueueSend(spkQueue, &spkChunk, portMAX_DELAY);
              received += spkChunk.len;
            }
          } else { vTaskDelay(1); }
        }
      }
    }
    vTaskDelay(1);
  }
}

// --- TASK 2: AUDIO ENGINE (Core 1) ---
void audioEngineTask(void *pvParameters) {
  int16_t mic_buf_raw[512]; 
  size_t bytesIn;

  while (true) {
    if (isRobotSpeaking) {
      startSpkHardware();
      if (isHwSwitching) { vTaskDelay(1); continue; } // Wait for Handoff

      AudioChunk spkChunk;
      if (xQueueReceive(spkQueue, &spkChunk, 0) == pdTRUE) {
        size_t bw;
        // Use a timeout of 100ms instead of portMAX_DELAY to prevent "stuck"
        if (i2s_write(I2S_PORT, spkChunk.data, spkChunk.len, &bw, 100 / portTICK_PERIOD_MS) != ESP_OK) {
           Serial.println("[WARN] Spk Blocked!");
        }
        lastVoiceTime = millis();
        if (uxQueueMessagesWaiting(spkQueue) == 0) {
          vTaskDelay(400 / portTICK_PERIOD_MS); // End-of-speech gap
          isRobotSpeaking = false;
        }
      }
    } else {
      startMicHardware();
      if (isHwSwitching) { vTaskDelay(1); continue; } 

      if (i2s_read(I2S_PORT, mic_buf_raw, sizeof(mic_buf_raw), &bytesIn, 0) == ESP_OK && bytesIn > 0) {
        lastVoiceTime = millis(); // Refresh watchdog
        int samples = bytesIn / 2;
        for (int i = 0; i < samples; i++) {
          int32_t val = (int32_t)mic_buf_raw[i] * MIC_GAIN;
          mic_buf_raw[i] = (val > 32767) ? 32767 : (val < -32768) ? -32768 : (int16_t)val;
        }
        AudioChunk micChunk; micChunk.len = bytesIn;
        memcpy(micChunk.data, mic_buf_raw, bytesIn);
        xQueueSend(micQueue, &micChunk, 0); 
      }
    }

    // --- SMART RESET WATCHDOG (CUTOFF) ---
    if (millis() - lastVoiceTime > 5000 && (isMicActive || isSpkActive)) {
      Serial.println("[CRITICAL] STUCK DETECTED! Resetting hardware...");
      isRobotSpeaking = false; 
      isMicActive = false;
      isSpkActive = false;
      i2s_stop(I2S_PORT);
      i2s_driver_uninstall(I2S_PORT);
      lastVoiceTime = millis();
    }
    vTaskDelay(1);
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();
  showText("OPTIMIZED SWITCH", "Smoothing Hardware Transitions...");

  micQueue = xQueueCreate(10, sizeof(AudioChunk));
  spkQueue = xQueueCreate(20, sizeof(AudioChunk));

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); }

  xTaskCreatePinnedToCore(networkTask, "NetTask", 8192, NULL, 5, NULL, 0); 
  xTaskCreatePinnedToCore(audioEngineTask, "AudioTask", 8192, NULL, 10, NULL, 1); 

  showText("STABLE READY", WiFi.localIP().toString(), "Optimized Switch");
}

void loop() {
  static uint32_t lastUpd = 0;
  if (millis() - lastUpd > 1000) {
    if (client.connected()) {
      showText(isRobotSpeaking ? "AI: SPEAKING" : "YOU: LISTENING", isRobotSpeaking ? "Hw Speaker" : "Hw Microphone", "Buffered Core 1");
    } else {
      showText("OFFLINE", ssid);
    }
    lastUpd = millis();
  }
}
