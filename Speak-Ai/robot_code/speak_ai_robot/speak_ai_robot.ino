#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- FINAL CONFIG (DUAL-PIPE) ---
const char* ssid = "Xperia XZ2";
const char* password = "senidu1234";

// Architecture:
// 1. Mic: Robot is Server (8005) -> PC connects here
// 2. Speaker: PC is Server (8006) -> Robot connects here
const uint16_t MIC_PORT = 8005;
const uint16_t SPK_PORT = 8006;

WiFiServer micServer(MIC_PORT);
WiFiClient micClient;
WiFiClient spkClient;
String pc_ip = ""; // Found by scanner

// I2S Microphone (INMP441) - Port 0
#define I2S_WS  25
#define I2S_SD  32
#define I2S_SCK 26
#define I2S_PORT I2S_NUM_0

// I2S Speaker (MAX98357) - Port 1
#define I2S_SPK_BCLK 14
#define I2S_SPK_LRC  27
#define I2S_SPK_DOUT 33
#define I2S_SPK_PORT I2S_NUM_1

#define SAMPLE_RATE 16000
#define MIC_GAIN    4

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
volatile bool isSpeaking = false;

void oled(String l1, String l2="", String l3="", String l4="") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 12, l1.c_str());
  u8g2.drawStr(0, 26, l2.c_str());
  u8g2.drawStr(0, 40, l3.c_str());
  u8g2.drawStr(0, 54, l4.c_str());
  u8g2.sendBuffer();
}

// --- MIC SERVER TASK (Core 0) ---
void micTask(void* param) {
  static int16_t wave[512];
  while(true) {
    if (micClient.connected() && !isSpeaking) {
      size_t bytesIn = 0;
      // 16-bit read from voice_response_AI (proven working)
      if (i2s_read(I2S_PORT, &wave, sizeof(wave), &bytesIn, 0) == ESP_OK && bytesIn > 0) {
        int samples = bytesIn / 2;
        for (int i = 0; i < samples; i++) {
          int32_t s = (int32_t)wave[i] * MIC_GAIN;
          if (s > 32767) s = 32767; if (s < -32768) s = -32768;
          wave[i] = (int16_t)s;
        }
        micClient.write((uint8_t*)wave, bytesIn);
      }
    } else {
      vTaskDelay(10 / portTICK_PERIOD_MS);
    }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();
  oled("BOOTING...", "Dual-Pipe Ready");

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nIP: " + WiFi.localIP().toString());

  // Init Speaker (Port 1) - simple_tts_test config
  const i2s_config_t spk_cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };
  i2s_driver_install(I2S_SPK_PORT, &spk_cfg, 0, NULL);
  const i2s_pin_config_t spk_pins = {I2S_SPK_BCLK, I2S_SPK_LRC, I2S_SPK_DOUT, I2S_PIN_NO_CHANGE};
  i2s_set_pin(I2S_SPK_PORT, &spk_pins);
  i2s_start(I2S_SPK_PORT);

  // Init Mic (Port 0) - voice_response_AI config
  const i2s_config_t mic_cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false
  };
  const i2s_pin_config_t mic_pins = {I2S_SCK, I2S_WS, I2S_PIN_NO_CHANGE, I2S_SD};
  i2s_driver_install(I2S_PORT, &mic_cfg, 0, NULL);
  i2s_set_pin(I2S_PORT, &mic_pins);
  i2s_start(I2S_PORT);

  micServer.begin();
  xTaskCreatePinnedToCore(micTask, "MicTask", 8192, NULL, 1, NULL, 0);
  
  oled("ROBOT ONLINE", WiFi.localIP().toString(), "Mic:8005 (Server)", "Spk:8006 (Scanner)");
}

void scanSubnet() {
  IPAddress local = WiFi.localIP();
  String base = String(local[0]) + "." + String(local[1]) + "." + String(local[2]) + ".";
  for (int i = 2; i < 255; i++) {
    if (i == local[3]) continue;
    String test = base + String(i);
    if (spkClient.connect(test.c_str(), SPK_PORT, 20)) {
      pc_ip = test;
      return;
    }
    if (i % 20 == 0) oled("SCANNING SPK...", "Trying: " + test);
  }
}

void loop() {
  // Mic Client (Incoming)
  if (!micClient.connected()) {
    WiFiClient newC = micServer.available();
    if (newC) { micClient = newC; Serial.println("Mic connected"); }
  }

  // Spk Client (Outgoing)
  if (!spkClient.connected()) {
    if (pc_ip == "") scanSubnet();
    else {
      if (!spkClient.connect(pc_ip.c_str(), SPK_PORT)) { pc_ip = ""; delay(1000); }
      else Serial.println("Spk connected");
    }
  }

  // Handle Audio/Text from PC (via Spk Pipe)
  if (spkClient.connected() && spkClient.available() >= 5) {
    char head[6]; spkClient.readBytes(head, 5); head[5] = '\0';
    if (strcmp(head, "TEXT:") == 0) {
      String msg = spkClient.readStringUntil('\n'); msg.trim();
      oled("AI SAYS:", msg);
    } 
    else if (strcmp(head, "AUDIO") == 0) {
      isSpeaking = true;
      uint8_t len_b[4]; while(spkClient.available()<4) delay(1); spkClient.readBytes(len_b, 4);
      uint32_t alen = ((uint32_t)len_b[0]<<24)|((uint32_t)len_b[1]<<16)|((uint32_t)len_b[2]<<8)|len_b[3];
      
      uint32_t got = 0; uint8_t buf[1024];
      while (got < alen && spkClient.connected()) {
        int av = spkClient.available();
        if (av > 0) {
          int tr = min((uint32_t)av, alen - got); tr = min(1024, tr); tr = (tr / 4) * 4;
          if (tr == 0 && av > 0) tr = min((uint32_t)av, alen - got);
          int r = spkClient.readBytes(buf, tr);
          if (r > 0) { size_t bw; i2s_write(I2S_SPK_PORT, buf, r, &bw, portMAX_DELAY); got += r; }
        } else delay(1);
      }
      isSpeaking = false;
    }
  }
  
  // Status Display
  static unsigned long lastUpd = 0;
  if (millis() - lastUpd > 5000 && !isSpeaking) {
    String mS = micClient.connected() ? "MIC: OK" : "MIC: WAIT";
    String sS = spkClient.connected() ? "SPK: OK" : "SPK: SCAN";
    oled("SYSTEM STATUS", mS, sS, WiFi.localIP().toString());
    lastUpd = millis();
  }
  delay(1);
}
