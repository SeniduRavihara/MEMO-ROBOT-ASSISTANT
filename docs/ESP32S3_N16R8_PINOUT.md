# ESP32-S3 N16R8 — MEMO Robot Pin Assignments

## 🖥️ Display (SSD1306 OLED — I2C)
| Module Pin | GPIO |
|------------|------|
| SDA        | **8** |
| SCL        | **9** |
| VCC        | 3.3V |
| GND        | GND  |

---

## 🌀 Gyroscope MPU6050 (I2C — Shared with Display)
| Module Pin | GPIO |
|------------|------|
| SDA        | **8** |
| SCL        | **9** |
| INT        | **7** *(optional)* |
| AD0        | GND *(address = 0x68)* |
| VCC        | 3.3V |
| GND        | GND  |

---

## 🎤 Microphone INMP441 (I2S — Port 0)
| Module Pin | GPIO |
|------------|------|
| SCK        | **4** |
| WS         | **5** |
| SD         | **6** |
| L/R        | GND  |
| VDD        | 3.3V |
| GND        | GND  |

---

## 🔊 Speaker Amplifier MAX98357A (I2S — Port 1)
| Module Pin | GPIO |
|------------|------|
| BCLK       | **16** |
| LRC        | **17** |
| DIN        | **15** |
| VIN        | **5V (VBUS)** |
| GND        | GND  |
| GAIN       | *Disconnected = 9dB* |

---

## ⚠️ Forbidden Pins (Do NOT use)
| Pin Range | Reason |
|-----------|--------|
| GPIO 26–32 | Internal Flash |
| GPIO 33–37 | OPI PSRAM (8MB) |
| GPIO 19–20 | Native USB |
| GPIO 0, 45, 46 | Boot strapping |

---

## 🗺️ Quick Reference
```
GPIO 4  → Mic SCK        GPIO 8  → SDA (Display + Gyro)
GPIO 5  → Mic WS         GPIO 9  → SCL (Display + Gyro)
GPIO 6  → Mic SD         GPIO 7  → Gyro INT (optional)
GPIO 15 → Speaker DIN
GPIO 16 → Speaker BCLK
GPIO 17 → Speaker LRC
```

---

## 🛠️ Arduino IDE Board Settings (Keep These Always)

| Setting | Value |
|---------|-------|
| Board | ESP32S3 Dev Module |
| Flash Size | 16MB (128Mb) |
| Partition Scheme | 16MB Flash (3MB APP/9.9MB FATFS) |
| PSRAM | OPI PSRAM |
| USB Mode | **Hardware CDC and JTAG** ← important! |
| USB CDC On Boot | Enabled |
| Upload Mode | UART0 / Hardware CDC |
| CPU Frequency | 240MHz (WiFi) |

---

## 🔌 USB Port vs COM Port — Serial Monitor Truth

Your ESP32-S3 N16R8 board has **two USB ports**:

| Port Label | Hardware | Shows as on PC |
|------------|----------|----------------|
| **COM** | CH340 USB-to-UART chip | `/dev/ttyUSB0` |
| **USB** | ESP32-S3 native USB (GPIO 19/20) | `/dev/ttyACM0` |

### Which port `Serial.println()` uses depends on one setting:

| USB CDC On Boot | `Serial` goes to | Upload & Monitor port |
|-----------------|------------------|-----------------------|
| **Disabled** ✅ | COM port (ttyUSB0) | **Use COM port** |
| Enabled | USB port (ttyACM0) | Use USB port |

### ✅ Recommended Setup (what works for MEMO robot)

```
USB CDC On Boot → Disabled
Upload port     → COM port (/dev/ttyUSB0)
Serial Monitor  → COM port (/dev/ttyUSB0)
```

This is the most reliable setup. The COM port (CH340 chip) always works 
for both uploading and Serial Monitor with zero extra configuration.

### Full Working Arduino IDE Settings

| Setting | Value |
|---------|-------|
| Board | ESP32S3 Dev Module |
| Flash Size | 16MB (128Mb) |
| Partition Scheme | 16MB Flash (3MB APP/9.9MB FATFS) |
| PSRAM | OPI PSRAM |
| USB Mode | Hardware CDC and JTAG |
| **USB CDC On Boot** | **Disabled** ← key setting |
| Upload Mode | UART0 / Hardware CDC |
| CPU Frequency | 240MHz (WiFi) |
| Upload & Monitor Port | COM port (/dev/ttyUSB0) |
