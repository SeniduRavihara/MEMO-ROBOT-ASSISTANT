// Dead simple serial test for ESP32-S3 N16R8 via USB CDC (/dev/ttyACM0)

void setup() {
  Serial.begin(115200);
  delay(3000); // Give USB CDC 3 seconds to connect — no while(!Serial)
  Serial.println("==== SERIAL TEST ====");
  Serial.println("If you see this, Serial is working!");
}

void loop() {
  Serial.println("Hello from ESP32-S3 loop!");
  delay(1000);
}
