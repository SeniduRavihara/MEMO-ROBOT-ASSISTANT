/*
 * ============================================================================
 *  MEMO AI Robot — Vector-Style Expressive Eye Engine (SSD1306 OLED)
 * ============================================================================
 *  Hardware:
 *    - ESP32-S3 N16R8
 *    - OLED SSD1306 128x64 I2C  -> SDA: GPIO 8, SCL: GPIO 9
 *    - (Optional) MPU6050 IMU   -> Shared I2C (SDA: 8, SCL: 9)
 *
 *  Libraries:
 *    - U8g2 (by olikraus)
 *    - Adafruit MPU6050 (optional, auto-detected)
 *
 *  Interactive Serial Monitor Commands (115200 baud):
 *    'h' -> Happy (Pixar smiling crescent eyes)
 *    'a' -> Angry / Determined (\ / furrowed brows)
 *    's' -> Sad / Worried (/ \ droop)
 *    'z' -> Sleepy / Low Battery
 *    'c' -> Curious / Cocked Head (asymmetric raised eye)
 *    'p' -> Surprised / Shocked (tall wide pop)
 *    't' -> Thinking (glance up-right & pulse)
 *    'l' -> Listening (attentive wide eyes)
 *    'v' -> Speaking (speech bounce & animated mouth)
 *    'd' -> Dizzy / Knocked Out (spinning crosses)
 *    '<' -> Hearts in love (<3 <3)
 *    'n' -> Neutral / Normal resting state
 *    'b' -> Instant blink!
 *    'auto' or 'demo' -> Auto-cycle through all emotions
 * ============================================================================
 */

#include <Wire.h>
#include <U8g2lib.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "MemoEyes.h"

// --- I2C Pins for ESP32-S3 N16R8 ---
#define I2C_SDA 8
#define I2C_SCL 9

// --- OLED Display Object ---
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// --- Vector Eye Engine ---
MemoEyes eyes;

// --- Optional MPU6050 Gyro/Accelerometer ---
Adafruit_MPU6050 mpu;
bool mpuAvailable = false;

// --- Demo Mode State ---
bool demoMode = true; // Starts in demo mode cycling emotions, disables when user sends a command
unsigned long lastDemoSwitch = 0;
int demoIndex = 0;

const EyeEmotion DEMO_EMOTIONS[] = {
  EMOTION_NEUTRAL,
  EMOTION_HAPPY,
  EMOTION_CURIOUS,
  EMOTION_LISTENING,
  EMOTION_THINKING,
  EMOTION_SPEAKING,
  EMOTION_SURPRISED,
  EMOTION_ANGRY,
  EMOTION_SAD,
  EMOTION_SLEEPY,
  EMOTION_DIZZY,
  EMOTION_HEARTS
};
const int NUM_DEMO_EMOTIONS = sizeof(DEMO_EMOTIONS) / sizeof(DEMO_EMOTIONS[0]);

const char* emotionName(EyeEmotion e) {
  switch (e) {
    case EMOTION_NEUTRAL:   return "Neutral (Normal)";
    case EMOTION_HAPPY:     return "Happy (^ ^)";
    case EMOTION_ANGRY:     return "Angry (\\ /)";
    case EMOTION_SAD:       return "Sad (/ \\)";
    case EMOTION_SLEEPY:    return "Sleepy (- -)";
    case EMOTION_CURIOUS:   return "Curious (Cocked Head)";
    case EMOTION_SURPRISED: return "Surprised (Wide Pop)";
    case EMOTION_THINKING:  return "Thinking (Up-Right)";
    case EMOTION_LISTENING: return "Listening (Attentive)";
    case EMOTION_SPEAKING:  return "Speaking (Mouth Animate)";
    case EMOTION_DIZZY:     return "Dizzy (Knocked Out)";
    case EMOTION_HEARTS:    return "Hearts (<3 <3)";
    default:                return "Unknown";
  }
}

void printHelp() {
  Serial.println("\n==============================================");
  Serial.println("🤖 MEMO Vector Eyes - Interactive Commands:");
  Serial.println("==============================================");
  Serial.println("  'n' -> Neutral resting state");
  Serial.println("  'h' -> Happy (Pixar smiling crescent eyes)");
  Serial.println("  'a' -> Angry / Determined");
  Serial.println("  's' -> Sad / Worried");
  Serial.println("  'z' -> Sleepy / Tired");
  Serial.println("  'c' -> Curious (Asymmetric cocked eye)");
  Serial.println("  'p' -> Surprised (Pop wide)");
  Serial.println("  't' -> Thinking (Glance up-right)");
  Serial.println("  'l' -> Listening");
  Serial.println("  'v' -> Speaking (animated bounce + mouth)");
  Serial.println("  'd' -> Dizzy (Spinning crosses)");
  Serial.println("  '<' -> Hearts in love (<3 <3)");
  Serial.println("  'b' -> Force blink now");
  Serial.println("  'auto' -> Toggle automatic demo cycle");
  Serial.println("==============================================\n");
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("🤖 Initializing MEMO Vector Eyes...");

  // 1. Initialize Fast I2C (400kHz)
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  // 2. Initialize OLED
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(16, 32, "MEMO Vector Eyes");
  u8g2.sendBuffer();
  delay(800);

  // 3. Initialize Eye Engine
  eyes.begin();
  eyes.setEmotion(EMOTION_NEUTRAL);

  // 4. Try initializing MPU6050 (non-blocking if not attached)
  if (mpu.begin()) {
    mpuAvailable = true;
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("✅ MPU6050 IMU detected: Tilt tracking active!");
  } else {
    mpuAvailable = false;
    Serial.println("ℹ️ MPU6050 not detected: Proceeding with autonomous saccades.");
  }

  printHelp();
  lastDemoSwitch = millis();
}

void handleSerialCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();
  if (cmd.length() == 0) return;

  demoMode = false; // Disable auto-cycle when manually commanded

  if (cmd == "auto" || cmd == "demo") {
    demoMode = true;
    lastDemoSwitch = millis();
    Serial.println("▶️ Auto Demo Cycle ENABLED");
    return;
  }

  char c = cmd.charAt(0);
  switch (c) {
    case 'n':
      eyes.setEmotion(EMOTION_NEUTRAL);
      eyes.center();
      Serial.println("Emotion: Neutral");
      break;

    case 'h':
      eyes.setEmotion(EMOTION_HAPPY);
      Serial.println("Emotion: Happy (^ ^)");
      break;

    case 'a':
      eyes.setEmotion(EMOTION_ANGRY);
      Serial.println("Emotion: Angry (\\ /)");
      break;

    case 's':
      eyes.setEmotion(EMOTION_SAD);
      Serial.println("Emotion: Sad (/ \\)");
      break;

    case 'z':
      eyes.setEmotion(EMOTION_SLEEPY);
      Serial.println("Emotion: Sleepy (- -)");
      break;

    case 'c':
      eyes.setEmotion(EMOTION_CURIOUS);
      Serial.println("Emotion: Curious");
      break;

    case 'p':
      eyes.setEmotion(EMOTION_SURPRISED);
      Serial.println("Emotion: Surprised");
      break;

    case 't':
      eyes.setEmotion(EMOTION_THINKING);
      Serial.println("Emotion: Thinking");
      break;

    case 'l':
      eyes.setEmotion(EMOTION_LISTENING);
      Serial.println("Emotion: Listening");
      break;

    case 'v':
      eyes.setEmotion(EMOTION_SPEAKING);
      Serial.println("Emotion: Speaking");
      break;

    case 'd':
      eyes.setEmotion(EMOTION_DIZZY);
      Serial.println("Emotion: Dizzy");
      break;

    case '<':
      eyes.setEmotion(EMOTION_HEARTS);
      Serial.println("Emotion: Hearts (<3 <3)");
      break;

    case 'b':
      eyes.blink();
      Serial.println("Action: Blink!");
      break;

    default:
      Serial.printf("Unknown command '%s'. Press '?' or type 'help'.\n", cmd.c_str());
      printHelp();
      break;
  }
}

void loop() {
  unsigned long now = millis();

  // 1. Process Serial Commands
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    handleSerialCommand(cmd);
  }

  // 2. Demo Mode Auto-Cycle (Cycles every 3.2 seconds)
  if (demoMode) {
    if (now - lastDemoSwitch > 3200) {
      lastDemoSwitch = now;
      demoIndex = (demoIndex + 1) % NUM_DEMO_EMOTIONS;
      EyeEmotion nextEmo = DEMO_EMOTIONS[demoIndex];
      eyes.setEmotion(nextEmo);
      Serial.printf("[Demo] Emotion: %s\n", emotionName(nextEmo));
    }
  }

  // 3. MPU6050 Physical Tilt & Shake Interaction
  if (mpuAvailable && !demoMode) {
    static unsigned long lastImuRead = 0;
    if (now - lastImuRead > 30) { // 33Hz IMU update
      lastImuRead = now;
      sensors_event_t a, g, temp;
      mpu.getEvent(&a, &g, &temp);

      // Detect vigorous shake -> trigger Dizzy
      float totalAccel = sqrtf(a.acceleration.x * a.acceleration.x +
                               a.acceleration.y * a.acceleration.y +
                               a.acceleration.z * a.acceleration.z);
      if (totalAccel > 22.0f && eyes.getEmotion() != EMOTION_DIZZY) {
        eyes.setEmotion(EMOTION_DIZZY);
        Serial.println("💥 Shaken! Emotion: Dizzy");
      }

      // If neutral or happy, allow physical tilt gaze tracking
      if (eyes.getEmotion() == EMOTION_NEUTRAL || eyes.getEmotion() == EMOTION_HAPPY) {
        // Map Y tilt to gazeX (-16 to +16) and X tilt to gazeY (-10 to +10)
        int8_t gazeX = constrain((int)(-a.acceleration.y * 2.2f), -14, 14);
        int8_t gazeY = constrain((int)(a.acceleration.x * 2.2f), -8, 8);
        eyes.look(gazeX, gazeY);
      }
    }
  }

  // 4. Update Eye Physics & Autonomics (at ~50 FPS)
  static unsigned long lastFrameTime = 0;
  if (now - lastFrameTime >= 20) { // 50Hz frame timing
    lastFrameTime = now;

    // Advance animation state
    eyes.update();

    // Render frame
    u8g2.clearBuffer();
    eyes.render(u8g2);
    u8g2.sendBuffer();
  }
}
