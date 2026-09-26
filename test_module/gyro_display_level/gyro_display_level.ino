// Gyro + OLED Spirit Level (Bubble Level Tool)
// ESP32-S3 N16R8
// OLED (SSD1306/SH1106) — SDA=GPIO8, SCL=GPIO9
// MPU6050              — SDA=GPIO8, SCL=GPIO9 (shared I2C bus)
//
// Libraries needed:
//   - U8g2 (by olikraus)
//   - Adafruit MPU6050
//   - Adafruit Unified Sensor

#include <Wire.h>
#include <U8g2lib.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <math.h>

// --- Pins ---
#define I2C_SDA 8
#define I2C_SCL 9

// --- OLED ---
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// --- MPU6050 ---
Adafruit_MPU6050 mpu;

// --- Display center and boundary ---
#define DISP_W     128
#define DISP_H     64
#define CX         64    // Center X of level circle
#define CY         32    // Center Y of level circle
#define RADIUS     26    // Outer circle radius
#define BUBBLE_R   5     // Bubble dot radius

void setup() {
  Serial.begin(115200);

  // Init I2C (shared by OLED + MPU6050)
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  // Init OLED
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(10, 30, "Initializing...");
  u8g2.sendBuffer();

  // Init MPU6050
  if (!mpu.begin()) {
    u8g2.clearBuffer();
    u8g2.drawStr(0, 20, "MPU6050 ERROR!");
    u8g2.drawStr(0, 35, "Check wiring:");
    u8g2.drawStr(0, 48, "SDA=8 SCL=9");
    u8g2.sendBuffer();
    Serial.println("MPU6050 not found!");
    while (1) delay(500);
  }

  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  Serial.println("MPU6050 ready!");
  delay(500);
}

void loop() {
  sensors_event_t accel, gyro, temp;
  mpu.getEvent(&accel, &gyro, &temp);

  // Calculate pitch and roll from accelerometer (degrees)
  float ax = accel.acceleration.x;
  float ay = accel.acceleration.y;
  float az = accel.acceleration.z;

  float pitch = atan2(ay, sqrt(ax * ax + az * az)) * 180.0 / PI;
  float roll  = atan2(-ax, az) * 180.0 / PI;

  // Map angle to bubble pixel position (clamp to circle boundary)
  float maxAngle = 40.0; // degrees at edge of circle
  float bx_f = CX + (roll  / maxAngle) * (RADIUS - BUBBLE_R);
  float by_f = CY - (pitch / maxAngle) * (RADIUS - BUBBLE_R);

  // Clamp bubble inside the circle
  float dx = bx_f - CX;
  float dy = by_f - CY;
  float dist = sqrt(dx * dx + dy * dy);
  int maxDist = RADIUS - BUBBLE_R;
  if (dist > maxDist) {
    bx_f = CX + dx / dist * maxDist;
    by_f = CY + dy / dist * maxDist;
  }

  int bx = (int)bx_f;
  int by = (int)by_f;

  // Check if level (bubble near center)
  bool isLevel = (dist < 3.0);

  // --- Draw Display ---
  u8g2.clearBuffer();

  // Outer circle (boundary)
  u8g2.drawCircle(CX, CY, RADIUS, U8G2_DRAW_ALL);

  // Center crosshair
  u8g2.drawLine(CX - 4, CY, CX + 4, CY);
  u8g2.drawLine(CX, CY - 4, CX, CY + 4);

  // Bubble (filled circle)
  u8g2.drawDisc(bx, by, BUBBLE_R, U8G2_DRAW_ALL);

  // LEVEL indicator
  if (isLevel) {
    u8g2.setFont(u8g2_font_6x10_tf);
    u8g2.drawStr(98, 10, "LEVEL");
    u8g2.drawStr(99, 22, "  ✓");
  }

  // Angle readouts on the right side
  char buf[20];
  u8g2.setFont(u8g2_font_5x7_tf);

  snprintf(buf, sizeof(buf), "P:%4.1f", pitch);
  u8g2.drawStr(96, 38, buf);

  snprintf(buf, sizeof(buf), "R:%4.1f", roll);
  u8g2.drawStr(96, 50, buf);

  // Temp at bottom left
  snprintf(buf, sizeof(buf), "%.1fC", temp.temperature);
  u8g2.drawStr(0, 63, buf);

  u8g2.sendBuffer();

  // Serial output
  Serial.print("Pitch: "); Serial.print(pitch, 1);
  Serial.print("°  Roll: "); Serial.print(roll, 1);
  Serial.println("°");

  delay(50); // ~20fps
}
