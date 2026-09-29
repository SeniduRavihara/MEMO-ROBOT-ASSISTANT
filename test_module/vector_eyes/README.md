# 🤖 MEMO Vector Eyes — Procedural Animation Engine

Inspired by **Anki Vector & Cozmo**, this procedural eye animation engine brings MEMO's **SSD1306 128x64 OLED display** to life using classical Pixar animation principles.

---

## ✨ Features

- **Pixar Squash & Stretch Physics**: Every movement (blinking, smiling, squinting) interpolates smoothly with organic easing instead of rigid linear jumps.
- **Autonomic Micro-Saccades**: Random biological micro-darts every 1.5–3.5s simulate awareness even when idle.
- **Dynamic Blinking**: Natural asymmetric blinks (~50ms close, ~90ms ease-out open) with an 18% probability of double-blinking.
- **12 Expressive Emotional States**:
  - `EMOTION_NEUTRAL`: Clean rounded-capsule resting eyes.
  - `EMOTION_HAPPY`: Lower eyelids cut into upward smiling crescents (`^ ^`).
  - `EMOTION_ANGRY`: Furrowed brow with sharp inward downward angle (`\ /`).
  - `EMOTION_SAD`: Drooping brows with outward angle (`/ \`).
  - `EMOTION_SLEEPY`: Upper eyelids droop down with relaxed slow blinks.
  - `EMOTION_CURIOUS`: Asymmetric cocked-head expression (one eye raised high & wide, the other squinting).
  - `EMOTION_SURPRISED`: Tall, wide pop-out eyes.
  - `EMOTION_THINKING`: Eyes glance up-right with gentle pulse.
  - `EMOTION_LISTENING`: Attentive wide eyes.
  - `EMOTION_SPEAKING`: Speech oscillation bounce + animated mouth.
  - `EMOTION_DIZZY`: Spinning crosses / stars (triggers when robot is shaken).
  - `EMOTION_HEARTS`: Vector in love (`<3 <3`).
- **Physical Tilt & Shake Integration**: If an **MPU6050 IMU** is connected to the shared I2C bus, the eyes physically track room tilt and trigger dizziness when shaken.

---

## 🛠️ Hardware Wiring (ESP32-S3 N16R8)

| Module Pin | ESP32-S3 GPIO | Note |
|---|---|---|
| **OLED SDA** | **GPIO 8** | Shared I2C Data |
| **OLED SCL** | **GPIO 9** | Shared I2C Clock |
| **MPU6050 SDA** *(Optional)* | **GPIO 8** | Shared I2C Data |
| **MPU6050 SCL** *(Optional)* | **GPIO 9** | Shared I2C Clock |
| **VCC / GND** | 3.3V / GND | |

---

## 🚀 How to Run in Arduino IDE

1. Open `test_module/vector_eyes/vector_eyes.ino` in **Arduino IDE**.
2. Select **Board**: `ESP32S3 Dev Module`.
3. Set **PSRAM**: `OPI PSRAM`.
4. Upload sketch to your ESP32-S3.
5. Open **Serial Monitor** at **`115200 baud`**.
6. The eyes will automatically start in **Demo Mode**, cycling through all emotions.

### ⌨️ Interactive Serial Commands

Type any of these keys into the Serial Monitor and press Enter:

| Key | Emotion / Action |
|---|---|
| `n` | **Neutral** (resting face) |
| `h` | **Happy** (Pixar smiling eyes) |
| `a` | **Angry** / Determined |
| `s` | **Sad** / Worried |
| `z` | **Sleepy** / Tired |
| `c` | **Curious** (cocked eyebrow) |
| `p` | **Surprised** (wide pop) |
| `t` | **Thinking** (glance up-right) |
| `l` | **Listening** |
| `v` | **Speaking** (animated bounce + mouth) |
| `d` | **Dizzy** (spinning stars) |
| `<` | **Hearts** in love (`<3 <3`) |
| `b` | **Force Blink** immediately |
| `auto` | Toggle automatic demo cycle |

---

## 🔌 Integrating into Main Voice Assistant (`esp32_mic_streamer.ino`)

To have MEMO automatically show these eyes during voice chats:

1. Copy [MemoEyes.h](file:///home/senu/PROJECTS/MEMO/test_module/vector_eyes/MemoEyes.h) into `WORKING_SAMPLE/voice_response_AI/esp32_mic_streamer/`.
2. Include `#include "MemoEyes.h"` and declare `MemoEyes eyes;`.
3. In `setup()`, call `eyes.begin();`.
4. Map incoming TCP commands:
   ```cpp
   if (text == "Listening...") {
       eyes.setEmotion(EMOTION_LISTENING);
   } else if (text == "Thinking...") {
       eyes.setEmotion(EMOTION_THINKING);
   }
   ```
5. When the `AUDIO` command starts playing, set `eyes.setEmotion(EMOTION_SPEAKING);`.
6. When playback finishes, set `eyes.setEmotion(EMOTION_HAPPY);` or `EMOTION_NEUTRAL`.
