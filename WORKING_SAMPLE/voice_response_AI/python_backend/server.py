import serial
import wave
import time
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import speech_recognition as sr

app = FastAPI(title="ESP32 Audio Transcription API")

# Configuration matching the ESP32
SERIAL_PORT = '/dev/ttyUSB0'  # Might need updating per user env
BAUD_RATE = 921600
SAMPLE_RATE = 16000
OUTPUT_FILENAME = "captured_audio.wav"

def record_audio(duration: int):
    print(f"Connecting to ESP32 on {SERIAL_PORT} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        ser.reset_input_buffer() 
        print(f"Recording for {duration} seconds...")
        
        bytes_to_read = SAMPLE_RATE * 2 * duration 
        audio_data = bytearray()
        
        start_time = time.time()
        while len(audio_data) < bytes_to_read:
            in_waiting = ser.in_waiting
            if in_waiting > 0:
                chunk = ser.read(in_waiting)
                audio_data.extend(chunk)
                
            if time.time() - start_time > duration + 2:
                print("Recording timed out.")
                break
                
        ser.close()
        print(f"Captured {len(audio_data)} bytes of audio data.")
        
        with wave.open(OUTPUT_FILENAME, 'wb') as wf:
            wf.setnchannels(1)       # Mono
            wf.setsampwidth(2)       # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data)
        
        return True
    
    except serial.SerialException as e:
        print(f"Serial port error: {e}")
        return False
    except Exception as e:
        print(f"Recording error: {e}")
        return False

def transcribe_file(filename: str):
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(filename) as source:
            audio = recognizer.record(source)
            
        text = recognizer.recognize_google(audio)
        return {"text": text, "status": "success"}
    
    except sr.UnknownValueError:
        return {"text": "Could not understand the audio.", "status": "error_unrecognized"}
    except sr.RequestError as e:
        return {"text": f"API Request Error: {e}", "status": "error_api"}
    except Exception as e:
        return {"text": f"Error: {str(e)}", "status": "error_general"}

@app.get("/")
def read_root():
    return {"message": "ESP32 Audio Transcription API is running."}

@app.post("/transcribe")
def transcribe_audio_endpoint(duration: int = 5):
    """
    Endpoint to trigger an audio recording from the ESP32 and then transcribe it.
    The duration parameter specifies how many seconds to record.
    """
    print(f"Received request to record for {duration} seconds.")
    # 1. Capture the audio over serial
    success = record_audio(duration)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to capture audio from the serial port. Is the ESP32 connected and streaming?")
        
    # 2. Transcribe the captured file
    result = transcribe_file(OUTPUT_FILENAME)
    
    return JSONResponse(content=result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
