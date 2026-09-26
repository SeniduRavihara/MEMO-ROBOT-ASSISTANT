// MPU6050 Gyroscope + Accelerometer Test
// ESP32-S3 N16R8 — I2C on GPIO 8 (SDA) and GPIO 9 (SCL)
// Library needed: "Adafruit MPU6050" (install via Library Manager)

#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#define I2C_SDA 8
#define I2C_SCL 9

Adafruit_MPU6050 mpu;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("=== MPU6050 Gyro Test ===");

  // Initialize I2C with custom pins
  Wire.begin(I2C_SDA, I2C_SCL);

  // Initialize MPU6050
  if (!mpu.begin()) {
    Serial.println("ERROR: MPU6050 not found!");
    Serial.println("Check wiring: SDA=GPIO8, SCL=GPIO9, VCC=3.3V, GND=GND");
    while (1) delay(500); // Stop here
  }

  Serial.println("MPU6050 found! ✓");

  // Set ranges
  mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  Serial.println("Starting readings...\n");
  delay(500);
}

void loop() {
  sensors_event_t accel, gyro, temp;
  mpu.getEvent(&accel, &gyro, &temp);

  // Accelerometer (m/s²)
  Serial.print("Accel X: "); Serial.print(accel.acceleration.x, 2);
  Serial.print("  Y: ");     Serial.print(accel.acceleration.y, 2);
  Serial.print("  Z: ");     Serial.print(accel.acceleration.z, 2);
  Serial.println(" m/s²");

  // Gyroscope (rad/s)
  Serial.print("Gyro  X: "); Serial.print(gyro.gyro.x, 2);
  Serial.print("  Y: ");     Serial.print(gyro.gyro.y, 2);
  Serial.print("  Z: ");     Serial.print(gyro.gyro.z, 2);
  Serial.println(" rad/s");

  // Temperature
  Serial.print("Temp:  "); Serial.print(temp.temperature, 1);
  Serial.println(" °C\n");

  delay(500);
}
