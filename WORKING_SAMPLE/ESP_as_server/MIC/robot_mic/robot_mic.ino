/*
 * ESP_as_server / MIC Test
 * Copied from working voice_response_AI.
 * Shows IP on OLED so you know where to connect.
 * Robot Server on Port 8005.
 */
#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";

const uint16_t port = 8005;
WiFiServer server(port);
WiFiClient client;

#define I2S_WS  GPIO_NUM_25
#define I2S_SD  GPIO_NUM_32
#define I2S_SCK GPIO_NUM_26
#define I2S_PORT I2S_NUM_0

#define SAMPLE_RATE 16000
#define MIC_BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_16BIT
#define MIC_GAIN 4

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

void oled(String l1, String l2="", String l3="", String l4="") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  if(l1.length()) u8g2.drawStr(0, 12, l1.c_str());
  if(l2.length()) u8g2.drawStr(0, 26, l2.c_str());
  if(l3.length()) u8g2.drawStr(0, 40, l3.c_str());
  if(l4.length()) u8g2.drawStr(0, 54, l4.c_str());
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();
  oled("Connecting WiFi...", ssid);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(); delay(100);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }

  server.begin();

  String ip = WiFi.localIP().toString();
  Serial.println("\nIP: " + ip);
  Serial.println("Port: " + String(port));
  Serial.println("Waiting for PC to connect...");

  // Show IP clearly on OLED display
  oled("== MIC TEST ==",
       "IP: " + ip,
       "Port: " + String(port),
       "Waiting for PC...");

  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = MIC_BITS_PER_SAMPLE,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false
  };
  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };
  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
  i2s_start(I2S_PORT);
}

void loop() {
  if (!client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("PC Connected!");
      oled("== MIC ACTIVE ==",
           "Streaming audio...",
           "",
           "Speak now!");
    }
    return;
  }
  size_t bytesIn = 0;
  int16_t wave[512];
  if (i2s_read(I2S_PORT, &wave, sizeof(wave), &bytesIn, 0) == ESP_OK && bytesIn > 0) {
    int n = bytesIn / sizeof(wave[0]);
    for (int i = 0; i < n; i++) {
      int32_t s = (int32_t)wave[i] * MIC_GAIN;
      if (s > 32767) s = 32767;
      if (s < -32768) s = -32768;
      wave[i] = (int16_t)s;
    }
    client.write((uint8_t*)wave, n * sizeof(int16_t));
  }
}
