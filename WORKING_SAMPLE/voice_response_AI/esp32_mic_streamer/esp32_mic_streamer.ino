// ============================================================
//  🧪 TEST 2: MPU-6050 Gyroscope Live Reading & Steering Test
//  No extra external libraries needed! Uses standard Wire.h
//
//  What this test does:
//   1. Initializes MPU-6050 at 0x68 via I2C (SDA=8, SCL=9)
//   2. Calibrates Z-axis gyro on startup (keep sensor still!)
//   3. Reads Accel & Gyro rate in real-time
//   4. Calculates Steering Angle (° degrees)
//   5. Displays a visual ASCII steering bar in Serial Monitor!
// ============================================================

#include <Wire.h>

#define SDA_PIN       8
#define SCL_PIN       9
#define MPU_ADDR      0x68

#define RAD_TO_DEG    57.2957795f
#define COMP_ALPHA    0.98f

float gyroZBias     = 0.0f;
float steeringAngle = 0.0f;
unsigned long lastTime = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n==============================================");
  Serial.println("   MPU-6050 Live Gyroscope & Steering Test");
  Serial.println("==============================================");

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000); // 400kHz

  // Power management: wake up MPU-6050
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); // PWR_MGMT_1 register
  Wire.write(0x00); // Set to 0 to wake up
  byte err = Wire.endTransmission();

  if (err != 0) {
    Serial.println("❌ ERROR: Could not connect to MPU-6050!");
    Serial.println("Please run Test 01 (I2C Scanner) to check wiring.");
    while (1) delay(100);
  }

  // Set Gyro range to ±250 deg/s
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B); // GYRO_CONFIG
  Wire.write(0x00);
  Wire.endTransmission();

  Serial.println("✅ MPU-6050 Connected successfully!");
  Serial.println("----------------------------------------------");
  Serial.println("⚠️ CALIBRATING: Keep sensor COMPLETELY STILL for 2 seconds...");

  // Calibrate Gyro Z-axis bias
  float sumZ = 0;
  int samples = 500;
  for (int i = 0; i < samples; i++) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x47); // GYRO_ZOUT_H register
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)2);
    int16_t rawZ = (Wire.read() << 8) | Wire.read();
    sumZ += (rawZ / 131.0f); // 131 LSB / (deg/s)
    delay(4);
  }
  gyroZBias = sumZ / samples;

  Serial.print("✅ Calibration Complete! Gyro Z Bias = ");
  Serial.print(gyroZBias);
  Serial.println(" deg/s");
  Serial.println("----------------------------------------------");
  Serial.println("Rotate your gyro module to test steering!");
  Serial.println("==============================================\n");

  lastTime = millis();
}

void loop() {
  unsigned long now = millis();
  float dt = (now - lastTime) / 1000.0f;
  lastTime = now;

  // Read Accel (X, Y, Z) and Gyro (Z) registers
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B); // ACCEL_XOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)14);

  int16_t rawAX = (Wire.read() << 8) | Wire.read();
  int16_t rawAY = (Wire.read() << 8) | Wire.read();
  int16_t rawAZ = (Wire.read() << 8) | Wire.read();
  Wire.read(); Wire.read(); // Skip temperature
  int16_t rawGX = (Wire.read() << 8) | Wire.read();
  int16_t rawGY = (Wire.read() << 8) | Wire.read();
  int16_t rawGZ = (Wire.read() << 8) | Wire.read();

  // Convert raw values
  float ax = rawAX / 16384.0f;
  float az = rawAZ / 16384.0f;
  float gyroZ_deg = (rawGZ / 131.0f) - gyroZBias; // °/s

  // Accel angle calculation (yaw/pitch reference)
  float accelAngle = atan2f(ax, az) * RAD_TO_DEG;

  // Complementary filter for steering angle
  steeringAngle = COMP_ALPHA * (steeringAngle + gyroZ_deg * dt) + (1.0f - COMP_ALPHA) * accelAngle;

  // Visual Bar Indicator in Serial Output
  int barPos = map((int)steeringAngle, -180, 180, 0, 30);
  barPos = constrain(barPos, 0, 30);

  char barBuf[32];
  for (int i = 0; i <= 30; i++) {
    if (i == 15) barBuf[i] = '|';       // Center mark
    else if (i == barPos) barBuf[i] = 'O'; // Wheel position
    else barBuf[i] = '-';
  }
  barBuf[31] = '\0';

  Serial.printf("Angle: %6.1f°  |  GyroRate: %6.1f°/s  |  [%s]\n", steeringAngle, gyroZ_deg, barBuf);

  delay(30); // ~33Hz update rate for smooth serial monitor printing
}
