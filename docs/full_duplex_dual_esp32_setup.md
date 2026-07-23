# MEMO Robot — Full Duplex Dual ESP32 Setup

> **Status:** Planned / Future Upgrade  
> **Goal:** Enable real-time two-way voice conversation (like a phone call) between the user and the MEMO AI robot.

---

## Overview

The current MEMO implementation uses a **single ESP32** in a **half-duplex (walkie-talkie)** mode:
1. User speaks → ESP32 streams mic audio to Python backend
2. Python backend queries Gemini → sends text reply back to ESP32 OLED

This upgrade replaces that with a **full-duplex dual ESP32** architecture where:
- **ESP32 #1 (Input Node)** — Continuously streams microphone audio to the backend
- **ESP32 #2 (Output Node)** — Receives AI voice audio and displays text on the OLED screen simultaneously

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python Backend (PC / Server)                  │
│                                                                  │
│   ┌──────────────┐    ┌───────────────┐    ┌─────────────────┐  │
│   │  TCP Server  │    │  Gemini Live  │    │  Audio Encoder  │  │
│   │  Port 8005   │    │  WebSocket    │    │  (PCM → I2S)    │  │
│   │  (mic input) │    │  API Client   │    │                 │  │
│   └──────┬───────┘    └───────┬───────┘    └────────┬────────┘  │
│          │ raw PCM             │ streaming            │ PCM chunks│
└──────────┼─────────────────────┼──────────────────────┼──────────┘
           │                     │                      │
           │ Wi-Fi TCP           │ Internet             │ Wi-Fi TCP
           │                     │                      │ Port 8006
┌──────────▼──────────┐          │          ┌───────────▼──────────┐
│   ESP32 #1          │          │          │   ESP32 #2           │
│   (INPUT NODE)      │          │          │   (OUTPUT NODE)      │
│                     │          │          │                      │
│  ┌───────────────┐  │          │          │  ┌────────────────┐  │
│  │ INMP441       │  │          │          │  │ MAX98357A      │  │
│  │ I2S Mic       │  │          │          │  │ I2S Speaker    │  │
│  │ 16kHz, 16-bit │  │          │          │  │ Amp + Speaker  │  │
│  └───────────────┘  │          │          │  └────────────────┘  │
│                     │          │          │                      │
│  ┌───────────────┐  │          │          │  ┌────────────────┐  │
│  │ Status LED    │  │          │          │  │ OLED Display   │  │
│  │ (listening    │  │          │          │  │ 128x64 (U8g2)  │  │
│  │  indicator)   │  │          │          │  │ Shows AI reply │  │
│  └───────────────┘  │          │          │  └────────────────┘  │
└─────────────────────┘          │          └──────────────────────┘
                                 │
                     ┌───────────▼──────────────┐
                     │  Google Gemini Live API   │
                     │  (Multimodal WebSocket)   │
                     │                          │
                     │  Input:  Raw audio stream │
                     │  Output: Raw audio stream │
                     │          + text transcript│
                     └──────────────────────────┘
```

---

## Hardware Requirements

### ESP32 #1 — Input Node (Microphone)
Already built! This is the current `esp32_mic_streamer` firmware.

| Component | Model | Pins |
|---|---|---|
| Microcontroller | ESP32 (any variant) | — |
| Microphone | INMP441 (I2S MEMS) | WS=25, SD=32, SCK=26 |
| Status LED | Any LED | GPIO 2 (optional) |

### ESP32 #2 — Output Node (Speaker + Display)
**New hardware to purchase/wire:**

| Component | Model | Estimated Cost | Pins |
|---|---|---|---|
| Microcontroller | ESP32 (any variant) | Already owned | — |
| I2S Amplifier | MAX98357A | ~$2–5 | BCLK=26, LRC=25, DIN=22 |
| Speaker | 3W, 4Ω or 8Ω | ~$2–4 | Connected to MAX98357A |
| OLED Display | SSD1306/SH1106 128x64 | Already owned | SDA=21, SCL=22 |
| Power Supply | 5V 2A USB | — | USB or external |

> **Note:** The MAX98357A is a breakout board that takes I2S digital audio in and outputs amplified analog audio to a speaker directly. No separate amplifier needed.

---

## Wiring Diagrams

### ESP32 #2 — MAX98357A Speaker Amplifier

```
ESP32 #2          MAX98357A
─────────         ─────────
GPIO 26  ────────  BCLK
GPIO 25  ────────  LRC (LRCLK / WS)
GPIO 22  ────────  DIN
3.3V     ────────  VIN
GND      ────────  GND
                   Speaker+ ── [Speaker]
                   Speaker- ── [Speaker]

GAIN pin:
  Float (disconnected) = 9dB gain (recommended)
  GND = 6dB gain
  3.3V = 12dB gain
```

### ESP32 #2 — OLED Display (I2C)

```
ESP32 #2          OLED SSD1306
─────────         ─────────────
GPIO 21  ────────  SDA
GPIO 22  ────────  SCL   (shared with DIN if using SPI OLED — use I2C OLED instead)
3.3V     ────────  VCC
GND      ────────  GND
```

> ⚠️ **Pin Conflict Warning:** If your OLED uses I2C (SDA/SCL = GPIO 21/22), it shares GPIO 22 with the MAX98357A DIN pin. In this case, move the MAX98357A DIN to GPIO 23.

---

## Software Architecture

### Python Backend Changes

The backend needs to maintain **two separate TCP connections**:

```python
# Conceptual structure
mic_socket    = None  # TCP connection from ESP32 #1 (port 8005)
speaker_socket = None  # TCP connection to ESP32 #2 (port 8006)

# Thread 1: Receive mic audio from ESP32 #1
#   → Stream to Gemini Live WebSocket

# Thread 2: Receive audio chunks from Gemini Live WebSocket
#   → Forward to ESP32 #2 speaker socket

# Thread 3: Receive text from Gemini transcript
#   → Send to ESP32 #2 OLED display
```

### Key Python Dependencies to Add

```
google-genai>=1.0.0  # already installed, needs Live API support
websockets           # for persistent Gemini Live WebSocket
numpy                # already installed
```

### Gemini Live API Flow

```python
import asyncio
from google import genai

client = genai.Client(api_key=GEMINI_API_KEY)

# Open a persistent bidirectional session
async with client.aio.live.connect(model='gemini-2.5-flash-native-audio-latest') as session:
    # Send mic audio chunks as they arrive
    await session.send_realtime_input(audio=mic_chunk_bytes)
    
    # Receive AI audio response chunks
    async for response in session.receive():
        if response.data:          # raw audio PCM bytes
            send_to_speaker_esp32(response.data)
        if response.text:          # transcript text
            send_to_oled_esp32(response.text)
```

---

## ESP32 #2 Firmware Outline

```cpp
// esp32_output_node.ino

#include <WiFi.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <driver/i2s.h>

// --- I2S Speaker (MAX98357A) ---
#define SPEAKER_BCLK  26
#define SPEAKER_LRC   25
#define SPEAKER_DIN   22  // or 23 if OLED conflict

// --- OLED ---
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// --- Network ---
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverIP = "192.168.x.x";  // Python backend IP
const uint16_t port = 8006;

WiFiClient client;

void setup() {
  Serial.begin(115200);
  setupI2SSpeaker();
  setupOLED();
  connectWiFi();
  connectToBackend();
}

void loop() {
  // Read incoming data from Python backend
  // Format: "TEXT:<message>\n" or "AUDIO:<4-byte-length><pcm-bytes>"
  
  if (client.available()) {
    String header = client.readStringUntil(':');
    
    if (header == "TEXT") {
      String msg = client.readStringUntil('\n');
      displayOnOLED(msg);
    } else if (header == "AUDIO") {
      uint32_t length = readUint32();
      playAudioChunk(length);
    }
  }
}

void playAudioChunk(uint32_t length) {
  uint8_t buffer[512];
  size_t written;
  uint32_t remaining = length;
  
  while (remaining > 0) {
    int toRead = min((uint32_t)sizeof(buffer), remaining);
    int bytesRead = client.readBytes(buffer, toRead);
    i2s_write(I2S_NUM_0, buffer, bytesRead, &written, portMAX_DELAY);
    remaining -= bytesRead;
  }
}
```

---

## Step-by-Step Implementation Plan

### Phase 1 — Hardware Setup
- [ ] Purchase MAX98357A I2S amplifier module
- [ ] Purchase 3W 4Ω speaker (or 8Ω)
- [ ] Wire MAX98357A to ESP32 #2 as per wiring diagram above
- [ ] Confirm OLED still works alongside the speaker

### Phase 2 — ESP32 #2 Firmware
- [ ] Write `esp32_output_node.ino` (speaker + OLED)
- [ ] Test TCP connection from Python to ESP32 #2
- [ ] Test text display on OLED via TCP
- [ ] Test audio playback via I2S from raw PCM bytes

### Phase 3 — Python Backend Update
- [ ] Add second TCP server (port 8006) for ESP32 #2
- [ ] Integrate Gemini Live API WebSocket session
- [ ] Pipe mic audio from ESP32 #1 → Gemini Live
- [ ] Pipe Gemini audio response → ESP32 #2 speaker
- [ ] Pipe Gemini text transcript → ESP32 #2 OLED

### Phase 4 — Testing
- [ ] Test end-to-end: speak → hear Gemini reply from speaker
- [ ] Test OLED displays the correct AI transcript
- [ ] Tune audio quality (sample rate, buffer size)
- [ ] Test interrupting the AI mid-sentence

---

## Expected Latency After Upgrade

| Stage | Current | After Upgrade |
|---|---|---|
| Voice detection trigger | ~500ms (0.5s silence wait) | **~0ms** (streaming, no wait) |
| Speech-to-text | ~1.5s (Google STT roundtrip) | **~0ms** (Gemini Live processes in real-time) |
| AI thinking | ~1–2s | **~0.5s** (streaming generation) |
| First word heard | **~3–4s** | **~1s** |

---

## Resources

- [Gemini Live API Documentation](https://ai.google.dev/api/multimodal-live)
- [MAX98357A Datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf)
- [ESP32 I2S Driver Reference](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/i2s.html)
- [U8g2 Library for OLED](https://github.com/olikraus/u8g2)
- [INMP441 Microphone Datasheet](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf)
