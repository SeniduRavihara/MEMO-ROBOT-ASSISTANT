# 🚀 MEMO AI Robot — Future Upgrade Roadmap

This document outlines the planned hardware and software upgrades for the MEMO AI Robot Assistant, organized by priority and implementation complexity.

---

## 📋 Current System (v1.0 — COMPLETED ✅)

| Component | Current Implementation |
|---|---|
| **Brain Board** | ESP-WROOM-32 (520 KB RAM, No PSRAM) |
| **Speech-to-Text** | Local Faster-Whisper (`base` model, ~500ms) |
| **LLM Response** | Gemini Flash-Lite (text-only, ~800ms) |
| **Audio Transport** | Raw 16-bit PCM over TCP Socket (256 kbps) |
| **Display** | SSD1306 128x64 OLED (I2C) |
| **Microphone** | INMP441 MEMS (I2S) |
| **Speaker** | MAX98357A DAC (I2S) |
| **Total Response Time** | **~1.2 – 1.5 seconds** |
| **PC Dependency** | Required (`python3 live_server.py` must be running) |

---

## ⚡ Phase 1: Token Streaming (Software Only — No New Hardware!)

### What It Does
Instead of waiting for Gemini to finish generating the full sentence (~800ms), stream each word to the ESP32 OLED screen **as it is generated** (~30ms per token).

### Speed Impact
| Metric | Before | After |
|---|---|---|
| **Time to first word on screen** | ~1,200ms | ⚡ **~200ms** |
| **Perceived response time** | ~1.2s | ⚡ **~0.2s** |

### Implementation Details
- Replace `generate_content()` with `generate_content_stream()` in `live_server.py`.
- Stream partial text chunks over TCP to ESP32 as each token arrives.
- ESP32 firmware needs minor update to handle incremental `TEXT:` messages and redraw OLED progressively.

### Code Pattern
```python
response_stream = gemini_client.models.generate_content_stream(
    model="gemini-flash-lite-latest",
    contents=[prompt],
    config=types.GenerateContentConfig(
        system_instruction=ROBOT_SYSTEM_INSTRUCTION,
        max_output_tokens=60
    )
)

accumulated_text = ""
for chunk in response_stream:
    if chunk.text:
        accumulated_text += chunk.text
        # Send partial text to ESP32 immediately
        socket_connection.sendall(f"TEXT:{accumulated_text}\n".encode('utf-8'))
```

### Status: 🟡 Ready to implement (no hardware changes needed)

---

## 🧠 Phase 2: ESP32-S3 Brain Upgrade (New Hardware Required)

### Board to Purchase
> **ESP32-S3 DevKitC-1 N16R8** — Rs. 1,850.00
> - 16MB Flash (`N16`) + 8MB PSRAM (`R8`)
> - Dual-core Xtensa LX7 @ 240MHz
> - 45 GPIO Pins, Dual USB-C, Built-in RGB LED (IO38)
> - Native Camera DVP Interface

### What This Unlocks

#### 2A. Opus Audio Compression (16x Bandwidth Reduction)
| Metric | Current (Raw PCM) | With Opus |
|---|---|---|
| **Audio Bandwidth** | 256 kbps | **16 kbps** |
| **Wi-Fi Stability** | Drops on weak Wi-Fi | Rock-solid streaming |
| **Full-Duplex Audio** | No (half-duplex) | **Yes (simultaneous mic + speaker)** |

#### 2B. WebSocket Protocol (Replace Raw TCP)
- Multiplex binary Opus audio frames and JSON control messages over a single WebSocket connection.
- Enables real-time control signals (VAD state, abort playback, screen updates).

#### 2C. Live Speech Interruption (Barge-In)
- When user speaks while robot is talking, the server sends `{"type": "abort"}` via WebSocket.
- ESP32-S3 immediately stops speaker playback in **<50ms**.
- Dual-core CPU runs network on Core 0 and audio hardware on Core 1.

#### 2D. Standalone Operation (No PC Required!)
- ESP32-S3 connects **directly to cloud AI servers** over Wi-Fi.
- No need for `live_server.py` running on a laptop.
- Power the robot from any USB phone charger or powerbank battery.

### Status: 🔴 Waiting for ESP32-S3 board delivery

---

## 📷 Phase 3: Camera Vision (ESP32-CAM Module)

### Hardware Available
> **ESP32-CAM Module** — Already owned! ✅
> - OV2640 2MP Camera
> - Has its own ESP32 chip and Wi-Fi
> - Runs independently as a Wi-Fi camera server

### What It Does
When the user asks MEMO to "look at something", the Python backend (or ESP32-S3) fetches a JPEG snapshot from the ESP32-CAM's HTTP endpoint and sends it to **Gemini Vision** for multimodal analysis.

### How It Works
```
User: "MEMO, what am I holding?"
         │
         ▼
┌─────────────────┐     HTTP GET /capture     ┌─────────────────┐
│  MEMO Main Brain │ ◄──────────────────────── │   ESP32-CAM     │
│  (ESP32-S3)      │       JPEG Image          │   (Wi-Fi Eye)   │
└────────┬────────┘                            └─────────────────┘
         │
         ▼ Send JPEG to Gemini Vision API
         │
    "I see a blue coffee cup on your desk!"
```

### Voice Commands to Implement
| Voice Command | Action |
|---|---|
| *"MEMO, what do you see?"* | Capture photo → Gemini Vision → Describe scene |
| *"MEMO, read this for me"* | Capture photo → Gemini Vision → OCR text extraction |
| *"MEMO, who is this?"* | Capture photo → Gemini Vision → Describe person |
| *"MEMO, what color is this?"* | Capture photo → Gemini Vision → Color identification |

### Status: 🟡 Hardware ready, software integration pending

---

## 🦇 Phase 4: Table Edge Detection (Ultrasonic / IR Sensors)

### Hardware Needed
> **2x IR Cliff Sensors** or **HC-SR04 Ultrasonic Sensors** — ~Rs. 150 each

### What It Does
Two downward-facing sensors on the front of the robot chassis detect the table edge. When the distance reading suddenly increases (air gap detected), the robot immediately stops its motors to prevent falling off the desk.

### Wiring
```
ESP32-S3 GPIO Pin  →  Trigger Pin (HC-SR04)
ESP32-S3 GPIO Pin  ←  Echo Pin (HC-SR04)
```

### Logic
```cpp
if (distance_cm > 15) {  // No surface detected = cliff!
    stop_motors();
    display_warning("Edge detected!");
}
```

### Status: 🔴 Needs sensor purchase + chassis design

---

## 👂 Phase 5: Sound Direction Detection (Dual Mic Array)

### Hardware Needed
> **1x additional INMP441 MEMS Microphone** — ~Rs. 450

### What It Does
By placing one mic on the **left side** and one on the **right side** of the robot head, the ESP32-S3 compares the volume (amplitude) of incoming sound between both mics.

### Direction Detection Logic
| Left Mic Volume | Right Mic Volume | Robot Action |
|---|---|---|
| **Loud** | Quiet | Turn head **LEFT** toward speaker |
| Quiet | **Loud** | Turn head **RIGHT** toward speaker |
| Equal | Equal | Speaker is **directly in front** |

### Advanced: Time Difference of Arrival (TDOA)
For more precise angle detection, measure the **time delay** between when sound hits the left mic vs the right mic. At 16kHz sample rate, a 1-sample delay ≈ 2.1 cm distance difference, which translates to a specific angle.

### Status: 🔴 Needs 2nd mic purchase + servo motor for head rotation

---

## 🗺️ Implementation Priority & Timeline

| Priority | Phase | What | Hardware Cost | Difficulty |
|---|---|---|---|---|
| **1st** | ⚡ Phase 1 | Token Streaming | **Rs. 0** (software only!) | 🟢 Easy |
| **2nd** | 🧠 Phase 2 | ESP32-S3 Brain Upgrade | **Rs. 1,850** | 🟡 Medium |
| **3rd** | 📷 Phase 3 | Camera Vision | **Rs. 0** (already have ESP32-CAM!) | 🟡 Medium |
| **4th** | 🦇 Phase 4 | Table Edge Detection | **Rs. 300** (2x sensors) | 🟢 Easy |
| **5th** | 👂 Phase 5 | Sound Direction | **Rs. 450** (1x extra mic) | 🟡 Medium |

### Total Future Hardware Cost: **~Rs. 2,600** (for ALL upgrades combined!)
