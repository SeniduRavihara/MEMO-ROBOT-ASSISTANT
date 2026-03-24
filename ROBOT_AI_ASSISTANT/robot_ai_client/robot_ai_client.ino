// ROBOT AI ASSISTANT: HARDWARE DIAGNOSTIC (SERVICE MODE)
#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- CONFIG ---
const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";
const uint16_t port  = 8006;
const char* pc_ip    = "192.168.43.32"; 

#define I2S_PORT I2S_NUM_0

// MIC PINS
#define I2S_MIC_SCK  GPIO_NUM_26
#define I2S_MIC_WS   GPIO_NUM_25
#define I2S_MIC_SD   GPIO_NUM_32

// SPK PINS
#define I2S_SPK_BCLK GPIO_NUM_14
#define I2S_SPK_LRC  GPIO_NUM_27
#define I2S_SPK_DOUT GPIO_NUM_33

#define MIC_SAMPLE_RATE 16000
#define SPK_SAMPLE_RATE 24000 

WiFiClient client;
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

enum HW_MODE { MODE_OFF, MODE_MIC, MODE_SPK, MODE_LOOPBACK };
HW_MODE currentMode = MODE_OFF;

void logMem(String label) {
  uint32_t free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  Serial.printf("[%s] Free Internal RAM: %u bytes\n", label.c_str(), free);
}

void showText(String t1, String t2 = "", String t3 = "") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 15, t1.c_str());
  u8g2.drawStr(0, 35, t2.c_str());
  u8g2.drawStr(0, 55, t3.c_str());
  u8g2.sendBuffer();
}

// --- HARDWARE CONTROLLERS ---
void stopEverything() {
  if (currentMode != MODE_OFF) {
    i2s_stop(I2S_PORT);
    i2s_driver_uninstall(I2S_PORT);
    currentMode = MODE_OFF;
    Serial.println("[SERVICE] Hardware Stopped.");
    logMem("STOP");
  }
}

bool startMic() {
  stopEverything();
  logMem("BEFORE_MIC");
  
  const i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = MIC_SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
  if (err != ESP_OK) { Serial.printf("[ERROR] Mic Install Fail: %d\n", err); return false; }
  
  const i2s_pin_config_t pins = { .bck_io_num = I2S_MIC_SCK, .ws_io_num = I2S_MIC_WS, .data_out_num = I2S_PIN_NO_CHANGE, .data_in_num = I2S_MIC_SD };
  i2s_set_pin(I2S_PORT, &pins);
  i2s_start(I2S_PORT);
  
  currentMode = MODE_MIC;
  Serial.println("[SERVICE] MIC MODE ACTIVE.");
  logMem("AFTER_MIC");
  return true;
}

bool startSpk() {
  stopEverything();
  logMem("BEFORE_SPK");

  const i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SPK_SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
  if (err != ESP_OK) { Serial.printf("[ERROR] Spk Install Fail: %d\n", err); return false; }

  const i2s_pin_config_t pins = { .bck_io_num = I2S_SPK_BCLK, .ws_io_num = I2S_SPK_LRC, .data_out_num = I2S_SPK_DOUT, .data_in_num = I2S_PIN_NO_CHANGE };
  i2s_set_pin(I2S_PORT, &pins);
  i2s_start(I2S_PORT);
  
  currentMode = MODE_SPK;
  Serial.println("[SERVICE] SPEAKER MODE ACTIVE.");
  logMem("AFTER_SPK");
  return true;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();
  
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  
  Serial.println("\n[DIAGNOSTIC] System Ready.");
  Serial.println("Commands: 'M' (Mic Only), 'S' (Spk Only), 'X' (Off)");
  showText("SERVICE MODE", "WiFi Connected", "Waiting for command...");
}

void loop() {
  if (Serial.available()) {
    char cmd = toupper(Serial.read());
    if (cmd == 'M') { startMic(); showText("DIAGNOSTIC", "MIC ONLY (Streaming)"); }
    else if (cmd == 'S') { startSpk(); showText("DIAGNOSTIC", "SPK ONLY (Listening)"); }
    else if (cmd == 'X') { stopEverything(); showText("DIAGNOSTIC", "Hard Reset / Off"); }
  }

  // --- MODE SPECIFIC LOGIC ---
  if (currentMode == MODE_MIC) {
    int16_t buf[512];
    size_t bi;
    if (i2s_read(I2S_PORT, buf, sizeof(buf), &bi, 0) == ESP_OK && bi > 0) {
      if (!client.connected()) client.connect(pc_ip, port);
      if (client.connected()) client.write((uint8_t*)buf, bi);
    }
  } 
  else if (currentMode == MODE_SPK) {
    if (!client.connected()) client.connect(pc_ip, port);
    if (client.connected() && client.available() > 0) {
      // Very simple: just write everything to I2S (Assuming server sends pure PCM header-less for diagnostic)
      uint8_t buf[1024];
      size_t br = client.read(buf, 1024);
      if (br > 0) {
        size_t bw;
        i2s_write(I2S_PORT, buf, br, &bw, portMAX_DELAY);
      }
    }
  }

  vTaskDelay(1);
}
