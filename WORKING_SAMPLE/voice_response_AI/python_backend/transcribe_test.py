import serial
import wave
import time
import os
try:
    import speech_recognition as sr
except ImportError:
    print("Please install SpeechRecognition: pip install SpeechRecognition")
    exit(1)

# Configuration
# MAC/LINUX Example: '/dev/ttyUSB0' or '/dev/ttyACM0'
# WINDOWS Example: 'COM3'
SERIAL_PORT = '/dev/ttyUSB0'  # Change this to match your ESP32's port!
BAUD_RATE = 921600
RECORD_SECONDS = 5            # How long each recording chunk should be
SAMPLE_RATE = 16000           # Must match ESP32
OUTPUT_FILENAME = "captured_audio.wav"

def record_audio_from_serial(port, baud, duration, output_filename):
    print(f"Connecting to ESP32 on {port} at {baud} baud...")
    
    try:
        ser = serial.Serial(port, baud, timeout=1)
        # Flush any old data
        ser.reset_input_buffer() 
        print(f"Recording for {duration} seconds... Please speak now.")
        
        # We need (SAMPLE_RATE * 2 bytes_per_sample) bytes per second
        bytes_to_read = SAMPLE_RATE * 2 * duration 
        audio_data = bytearray()
        
        start_time = time.time()
        while len(audio_data) < bytes_to_read:
            # Read in chunks
            in_waiting = ser.in_waiting
            if in_waiting > 0:
                chunk = ser.read(in_waiting)
                audio_data.extend(chunk)
                
            # Failsafe timeout
            if time.time() - start_time > duration + 2:
                break
                
        ser.close()
        print(f"Captured {len(audio_data)} bytes of audio data.")
        
        # Save to WAV file
        with wave.open(output_filename, 'wb') as wf:
            wf.setnchannels(1)       # Mono
            wf.setsampwidth(2)       # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data)
        
        print(f"Saved recording to {output_filename}")
        return True
    
    except Exception as e:
        print(f"Error during recording: {e}")
        return False

def transcribe_audio(filename):
    print("\n--- Transcribing ---")
    recognizer = sr.Recognizer()
    
    with sr.AudioFile(filename) as source:
        audio = recognizer.record(source)
    try:
        # We use Google's free web Speech-to-Text for this quick demo
        text = recognizer.recognize_google(audio)
        print("Transcription Result:")
        print("=======================")
        print(f"\"{text}\"")
        print("=======================")
        
    except sr.UnknownValueError:
        print("Could not understand the audio. It might be too quiet, too noisy, or silent.")
    except sr.RequestError as e:
        print(f"Could not request results; {e}")

if __name__ == "__main__":
    success = record_audio_from_serial(SERIAL_PORT, BAUD_RATE, RECORD_SECONDS, OUTPUT_FILENAME)
    if success:
        transcribe_audio(OUTPUT_FILENAME)
