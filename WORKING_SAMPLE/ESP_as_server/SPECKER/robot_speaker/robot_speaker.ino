#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";

WiFiServer server(8005);
WiFiClient client;

#define I2S_SPK_BCLK 14
#define I2S_SPK_LRC  27
#define I2S_SPK_DOUT 33
#define I2S_SPK_PORT I2S_NUM_1
#define SAMPLE_RATE  16000

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// --- SHARED AUDIO BUFFER ---
QueueHandle_t audioQueue;

void oled(String l1, String l2="", String l3="", String l4="") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  if(l1.length()) u8g2.drawStr(0, 12, l1.c_str());
  if(l2.length()) u8g2.drawStr(0, 26, l2.c_str());
  if(l3.length()) u8g2.drawStr(0, 40, l3.c_str());
  if(l4.length()) u8g2.drawStr(0, 54, l4.c_str());
  u8g2.sendBuffer();
}

// --- SPEAKER TASK (RUNS ON CORE 1 - PROTECTED FROM WIFI) ---
void spkTask(void* p) {
  uint8_t packet[512];
  while(1) {
    if (xQueueReceive(audioQueue, &packet, portMAX_DELAY)) {
      size_t bw;
      // Write to hardware with absolute priority
      i2s_write(I2S_SPK_PORT, packet, 512, &bw, portMAX_DELAY);
    }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();
  oled("BOOTING (CORE FIX)...", ssid);

  audioQueue = xQueueCreate(40, 512); // Buffer 20kb of audio

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); }

  server.begin();
  
  const i2s_config_t spk_cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL3, // HIGH PRIORITY INTERRUPT
    .dma_buf_count = 16,                      // 16 buffers (More cushion)
    .dma_buf_len = 512,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };
  i2s_driver_install(I2S_SPK_PORT, &spk_cfg, 0, NULL);
  const i2s_pin_config_t spk_pins = {I2S_SPK_BCLK, I2S_SPK_LRC, I2S_SPK_DOUT, I2S_PIN_NO_CHANGE};
  i2s_set_pin(I2S_SPK_PORT, &spk_pins);
  i2s_start(I2S_SPK_PORT);

  // START SPEAKER TASK ON CORE 1
  xTaskCreatePinnedToCore(spkTask, "SpkTask", 4096, NULL, 10, NULL, 1);

  oled("== SPK CORE FIX ==", WiFi.localIP().toString(), "Port: 8005", "Waiting...");
}

void loop() {
  if (!client.connected()) {
    client = server.available();
    return;
  }

  if (client.available() >= 5) {
    char head[6]; client.readBytes(head, 5); head[5] = '\0';
    if (strcmp(head, "AUDIO") == 0) {
      oled("== PLAYING (C1) ==");
      
      uint8_t lb[4];
      while (client.connected() && client.available() < 4) delay(1);
      client.readBytes(lb, 4);
      uint32_t alen = ((uint32_t)lb[0]<<24)|((uint32_t)lb[1]<<16)|((uint32_t)lb[2]<<8)|lb[3];
      
      uint32_t got = 0;
      uint8_t buf[512];
      while (got < alen && client.connected()) {
        if (client.available() >= 512) {
          client.readBytes(buf, 512);
          xQueueSend(audioQueue, &buf, portMAX_DELAY);
          got += 512;
        } else {
          delay(1);
        }
      }
      oled("== DONE ==");
    }
  }
}
