/* 
 * ==========================================
 * PROJECT: PC_as_server / MICROPHONE
 * MODE:    Robot is CLIENT. PC is SERVER.
 * PORT:    8007
 * ==========================================
 */
#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";
const uint16_t port  = 8007; // PC Server Port

#define I2S_WS   GPIO_NUM_25
#define I2S_SCK  GPIO_NUM_26
#define I2S_SD   GPIO_NUM_32
#define I2S_PORT I2S_NUM_0
#define SAMPLE_RATE 16000
#define MIC_GAIN    4

WiFiClient client;
String pc_ip = ""; 
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

void showText(String t1, String t2="", String t3="") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  if(t1.length()) u8g2.drawStr(0, 15, t1.c_str());
  if(t2.length()) u8g2.drawStr(0, 35, t2.c_str());
  if(t3.length()) u8g2.drawStr(0, 55, t3.c_str());
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();
  showText("MIC CLIENT BOOT", ssid);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(); delay(100);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); }

  const i2s_config_t mic_cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 1024,
    .use_apll             = false
  };
  i2s_driver_install(I2S_PORT, &mic_cfg, 0, NULL);
  const i2s_pin_config_t mic_pins = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };
  i2s_set_pin(I2S_PORT, &mic_pins);
  i2s_start(I2S_PORT);
}

void scanSubnet() {
  IPAddress local = WiFi.localIP();
  String base = String(local[0]) + "." + String(local[1]) + "." + String(local[2]) + ".";
  showText("SCANNING FOR PC", "Port: 8007", base + "X");
  
  for (int i = 2; i < 255; i++) {
    if (i == local[3]) continue;
    String testIP = base + String(i);
    if (client.connect(testIP.c_str(), port, 20)) {
       pc_ip = testIP;
       return;
    }
  }
}

void loop() {
  if (!client.connected()) {
    if (pc_ip == "") {
      scanSubnet();
    } else {
      if (client.connect(pc_ip.c_str(), port)) {
         showText("== MIC CONNECTED! ==", "PC: " + pc_ip, "Streaming Audio...");
      } else {
        pc_ip = ""; delay(1000);
      }
    }
    return;
  }

  size_t bytesIn = 0;
  int16_t wave[512]; 
  // Blocking read ensure data alignment and stability
  if (i2s_read(I2S_PORT, &wave, sizeof(wave), &bytesIn, portMAX_DELAY) == ESP_OK && bytesIn > 0) {
    int samples = bytesIn / 2;
    for (int i = 0; i < samples; i++) {
      int32_t val = (int32_t)wave[i] * MIC_GAIN;
      if (val > 32767) val = 32767; if (val < -32768) val = -32768;
      wave[i] = (int16_t)val; 
    }
    client.write((uint8_t*)wave, samples * 2);
  }
}
