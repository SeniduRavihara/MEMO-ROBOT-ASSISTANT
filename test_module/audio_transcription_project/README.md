# Audio Transcription Project

This project streams audio data from an I2S microphone (INMP441) connected to an ESP32 over a serial connection to a Python backend, which then transcribes the audio into text using SpeechRecognition (and optionally Whisper).

## ESP32 Hardware Pinouts

Below are the custom ESP32 pin configurations used across this project and related test modules.

### 1. I2S Microphone (INMP441)
*   **SCK (Serial Clock):** GPIO 26
*   **WS (Word Select / L/R Clock):** GPIO 25
*   **SD (Serial Data / Output):** GPIO 32
*   **L/R Channel Setup:** Connect to GND for Left Channel (or VCC for Right).

### 2. I2S Amplifier (MAX98357A)
*   **BCLK (Bit Clock):** GPIO 14
*   **LRC (Left/Right Clock):** GPIO 27
*   **DIN (Data Input):** GPIO 33

### 3. I2C OLED Display (SSD1306)
*   **SDA (Data):** GPIO 4
*   **SCL (Clock):** GPIO 15

## Project Structure
*   **`esp32_mic_streamer/`**: Contains the Arduino sketch (`.ino`) that reads audio from the INMP441 microphone and streams the raw bytes over the Serial port at a high baud rate (921600).
*   **`python_backend/`**: Contains the Python scripts to capture the serial audio stream, save it as a `.wav` file, and perform Speech-to-Text transcription.

## Usage Instructions
1.  Upload the `esp32_mic_streamer.ino` sketch to your ESP32.
2.  **Close the Arduino Serial Monitor** so it doesn't block the Python script from reading the data.
3.  Navigate to the `python_backend` directory: `cd python_backend`
4.  Install the required dependencies: `pip install -r requirements.txt`
5.  Run the transcription test script: `python transcribe_test.py`
6.  Speak clearly into the microphone when prompted!
