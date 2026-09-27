# 🤖 MEMO Robot — Future Upgrade Reminder (from July 2026)

## Current Setup (Working Now ✅)
- **Board:** ESP32-S3 N16R8 (16MB Flash, 8MB PSRAM)
- **Architecture:** ESP32 → WiFi → Python `live_server.py` on PC → Gemini AI → TTS → back to ESP32
- **PC Required:** YES — `live_server.py` must be running on your laptop

---

## Why We Chose ESP32-S3 N16R8

| Reason | Detail |
|--------|--------|
| 8MB PSRAM | Required for Opus audio buffers |
| 16MB Flash | Fits full firmware + assets |
| 2x I2S | Mic (I2S_NUM_0) + Speaker (I2S_NUM_1) simultaneously |
| 2x I2C | Display + Gyro on shared bus |
| Dual-core LX7 @ 240MHz | AI vector acceleration |
| Dual USB-C | UART debug + USB OTG |
| RGB LED on GPIO38 | Built-in NeoPixel for status |

---

## Boards We Rejected (Don't Buy These!)

| Board | Why NOT |
|-------|---------|
| ESP32-C3 SuperMini | Only 400KB RAM, NO PSRAM, single-core |
| BBC micro:bit | No WiFi, only 128KB RAM |
| Small ESP32-S3 SuperMini | 90% have 0MB PSRAM — must check for R8 variant |

---

## The Big Future Upgrade: Standalone Robot (No PC Needed!)

### Current Problem
Right now the ESP32 needs `live_server.py` running on your PC.
If you shut down your laptop → robot dies.

### Future Goal: Xiaozhi Firmware (ESP-IDF)
- ESP32-S3 connects **directly** to cloud AI servers over WiFi
- **No laptop needed** — plug into a powerbank and go anywhere
- **Opus compression** — 16x less bandwidth than raw PCM
- **Full-duplex** — speak over the robot while it's talking (Barge-In)

| Feature | Current (Python server) | Future (Xiaozhi) |
|---------|------------------------|------------------|
| PC needed? | YES | NO |
| Audio format | Raw PCM (256 kbps) | Opus (16 kbps) |
| Latency | ~1.2–1.4s | ~0.8s |
| Full-duplex | No | Yes (barge-in) |
| Portable? | No | Yes (powerbank) |

---

## Hardware Pin Reference (ESP32-S3 N16R8)

| Component | GPIO |
|-----------|------|
| Mic SCK (INMP441) | GPIO 4 |
| Mic WS (INMP441) | GPIO 5 |
| Mic SD (INMP441) | GPIO 6 |
| Speaker BCLK (MAX98357A) | GPIO 16 |
| Speaker LRC (MAX98357A) | GPIO 17 |
| Speaker DIN (MAX98357A) | GPIO 15 |
| OLED/Gyro SDA | GPIO 8 |
| OLED/Gyro SCL | GPIO 9 |
| **FORBIDDEN (OPI PSRAM)** | **GPIO 26–37** |

---

## Arduino IDE Settings

| Setting | Value |
|---------|-------|
| Board | ESP32S3 Dev Module |
| Flash Size | 16MB (128Mb) |
| PSRAM | OPI PSRAM |
| USB CDC On Boot | **Disabled** |
| Upload Port | COM (/dev/ttyUSB0) |
| CPU Frequency | 240MHz |
