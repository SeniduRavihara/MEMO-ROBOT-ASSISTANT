#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- CONFIG ---
const char* ssid     = "Xperia XZ2";
const char* password = "senidu1234";
const char* pc_ip    = "192.168.43.32";
const uint16_t port  = 8006;

#define I2S_PORT I2S_NUM_0

// MIC PINS
#define I2S_MIC_SCK  26
#define I2S_MIC_WS   25
#define I2S_MIC_SD   32

// SPK PINS
#define I2S_SPK_BCLK 14
#define I2S_SPK_LRC  27
#define I2S_SPK_DOUT 33

WiFiClient client;
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

bool isSpeaking = false;

void showText(const char* t1, const char* t2 = "") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  
  // Wrap text simply if too long (Quick fix for 128px)
  u8g2.drawStr(0, 15, t1);
  if (strlen(t2) > 20) {
    char line1[21]; strncpy(line1, t2, 20); line1[20] = '\0';
    u8g2.drawStr(0, 35, line1);
    u8g2.drawStr(0, 55, t2 + 20);
  } else {
    u8g2.drawStr(0, 35, t2);
  }
  u8g2.sendBuffer();
}

void switchToMic() {
  i2s_stop(I2S_PORT);
  const i2s_pin_config_t pins = { .bck_io_num = I2S_MIC_SCK, .ws_io_num = I2S_MIC_WS, .data_out_num = -1, .data_in_num = I2S_MIC_SD };
  i2s_set_pin(I2S_PORT, &pins);
  i2s_set_clk(I2S_PORT, 16000, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
  i2s_start(I2S_PORT);
  Serial.println("HW: Switched to MIC");
}

void switchToSpk() {
  i2s_stop(I2S_PORT);
  const i2s_pin_config_t pins = { .bck_io_num = I2S_SPK_BCLK, .ws_io_num = I2S_SPK_LRC, .data_out_num = I2S_SPK_DOUT, .data_in_num = -1 };
  i2s_set_pin(I2S_PORT, &pins);
  i2s_set_clk(I2S_PORT, 24000, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_STEREO);
  i2s_start(I2S_PORT);
  Serial.println("HW: Switched to SPEAKER");
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Wire.begin(4, 15);
  u8g2.begin();
  showText("BOOTING...", "Connecting WiFi");

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  showText("STABLE READY", WiFi.localIP().toString().c_str());

  const i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_RX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 12,
    .dma_buf_len = 512,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };
  i2s_driver_install(I2S_PORT, &cfg, 0, NULL);
  switchToMic();
}

void loop() {
  if (!client.connected()) client.connect(pc_ip, port);

  if (!isSpeaking) {
    // 1. MIC MODE
    int16_t samples[256];
    size_t br;
    if (i2s_read(I2S_PORT, samples, sizeof(samples), &br, 0) == ESP_OK && br > 0) {
      if (client.connected()) client.write((uint8_t*)samples, br);
    }

    // Check for "AUDIO" or "TEXT" header
    if (client.available() >= 8) { // Min header size is 8 - b'TEXT' + length
      char header[5];
      client.readBytes(header, 4); header[4] = '\0';
      
      uint32_t len;
      client.readBytes((char*)&len, 4); 
      // Note: PC sends big-endian, ESP32 is little-endian. Need swap if using struct.pack('>I')
      len = __builtin_bswap32(len); 

      if (strcmp(header, "TEXT") == 0) {
        char* text = (char*)malloc(len + 1);
        client.readBytes(text, len);
        text[len] = '\0';
        Serial.printf("[TEXT] Received: %s\n", text);
        showText("VOICE:", text);
        free(text);
      } 
      else if (strcmp(header, "AUDI") == 0) { // PC sends b'AUDIO' (5 bytes), but we read 4
        // Trash the 'O'
        client.read(); 
        isSpeaking = true;
        switchToSpk();
        // showText is already done by TEXT header if provided
      }
    }
  } else {
    // 2. SPEAKER MODE
    if (client.available() > 0) {
      uint8_t buf[512];
      int r = client.read(buf, 512);
      if (r > 0) {
        size_t bw;
        i2s_write(I2S_PORT, buf, r, &bw, portMAX_DELAY);
      }
    } else {
      static uint32_t lastData = 0;
      if (client.available() > 0) lastData = millis();
      if (millis() - lastData > 1000 && !client.available()) {
        isSpeaking = false;
        switchToMic();
        showText("READY", "Listening...");
      }
    }
  }
}
