#include <driver/i2s.h>
#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>

// --- WIFI CONFIG ---
const char* ssid = "Xperia XZ2";
const char* password = "senidu1234";
const uint16_t port = 8006;

WiFiClient client;
String pc_ip = "192.168.43.32"; // Found automatically!

// I2S Speaker Pins (MAX98357)
#define I2S_SPK_BCLK GPIO_NUM_14
#define I2S_SPK_LRC GPIO_NUM_27
#define I2S_SPK_DOUT GPIO_NUM_33
#define I2S_SPK_PORT I2S_NUM_1

#define SAMPLE_RATE 16000

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

void showText(String text1, String text2, String text3 = "") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 15, text1.c_str());
  u8g2.drawStr(0, 35, text2.c_str());
  u8g2.drawStr(0, 55, text3.c_str());
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(4, 15);
  u8g2.begin();

  WiFi.begin(ssid, password);
  int timeout = 0;
  while (WiFi.status() != WL_CONNECTED && timeout < 40) {
    delay(500);
    showText("Connecting WiFi...", String(timeout/2) + "s");
    timeout++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    // Initialize Speaker I2S
    const i2s_config_t spk_i2s_config = {
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
    i2s_driver_install(I2S_SPK_PORT, &spk_i2s_config, 0, NULL);
    
    const i2s_pin_config_t pin_config = {
      .bck_io_num = I2S_SPK_BCLK,
      .ws_io_num = I2S_SPK_LRC,
      .data_out_num = I2S_SPK_DOUT,
      .data_in_num = I2S_PIN_NO_CHANGE
    };
    i2s_set_pin(I2S_SPK_PORT, &pin_config);
    i2s_start(I2S_SPK_PORT);
  } else {
    showText("WiFi ERROR!", "Check Credentials");
    while(1) delay(1);
  }
}

void scanSubnet() {
  IPAddress local = WiFi.localIP();
  String baseIP = String(local[0]) + "." + String(local[1]) + "." + String(local[2]) + ".";
  showText("SCANNING NETWORK", "Looking for PC...", baseIP + "X");
  
  for (int i = 2; i < 255; i++) {
    String testIP = baseIP + String(i);
    // Don't scan yourself
    if (i == local[3]) continue;
    
    Serial.printf("Trying %s...\n", testIP.c_str());
    if (client.connect(testIP.c_str(), port, 20)) { // 20ms timeout for fast scan
      pc_ip = testIP;
      return;
    }
    // Update progress every 10 IPs
    if (i % 10 == 0) showText("SCANNING NETWORK", "Progress: " + String(i) + "/254", "Found nothing yet");
  }
}

void loop() {
  if (!client.connected()) {
    if (pc_ip == "") {
      scanSubnet();
    } else {
      showText("FOUND PC!", "Connecting to:", pc_ip);
      if (client.connect(pc_ip.c_str(), port)) {
         showText("CONNECTED!", "Waiting for Audio...");
      } else {
        pc_ip = ""; // Reset and scan again if lost
        delay(1000);
      }
    }
  }

  if (client.connected() && client.available() >= 5) {
      char header[6];
      client.readBytes(header, 5);
      header[5] = '\0';
      
      if (strcmp(header, "AUDIO") == 0) {
        showText("Playing...", "Audio Stream");

        uint32_t audio_len = 0;
        uint8_t len_buf[4];
        while (client.connected() && client.available() < 4) { delay(1); } 
        client.readBytes(len_buf, 4);
        audio_len = ((uint32_t)len_buf[0] << 24) | ((uint32_t)len_buf[1] << 16) | ((uint32_t)len_buf[2] << 8) | (uint32_t)len_buf[3];
        
        uint32_t total_received = 0;
        uint8_t audio_buf[1024];
        while (total_received < audio_len && client.connected()) {
           int avail = client.available();
           if (avail > 0) {
             int to_read = min((uint32_t)avail, audio_len - total_received);
             to_read = min((uint32_t)1024, (uint32_t)to_read);
             to_read = (to_read / 4) * 4;
             if (to_read == 0 && avail > 0) to_read = min((uint32_t)avail, audio_len - total_received);
             if (to_read == 0) { delay(1); continue; }
             int read_now = client.readBytes(audio_buf, to_read);
             if (read_now > 0) {
               size_t bw = 0;
               i2s_write(I2S_SPK_PORT, audio_buf, read_now, &bw, portMAX_DELAY);
               total_received += read_now;
             }
           } else { delay(1); }
        }
        showText("FINISHED", "PC Waiting...");
        // client.stop(); // KEEP THE CONNECTION OPEN for more messages
      }
  }
}
