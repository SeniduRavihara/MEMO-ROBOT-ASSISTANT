import serial
import wave
import time
import os
import io
import struct
import math
import asyncio
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import speech_recognition as sr

app = FastAPI(title="Live Audio Transcription")

# Configuration matching the ESP32
SERIAL_PORT = '/dev/ttyUSB0'  
BAUD_RATE = 921600
SAMPLE_RATE = 16000

# VAD (Voice Activity Detection) Settings
CHUNK_DURATION = 0.5  # Read serial in chunks of 0.5 seconds
CHUNK_BYTES = int(SAMPLE_RATE * 2 * CHUNK_DURATION) 
SILENCE_THRESHOLD = 500  # Adjust this if it's too sensitive or not sensitive enough
MAX_SILENCE_CHUNKS = 2   # How many silent chunks before we decide the user stopped talking

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Live ESP32 Transcription</title>
        <style>
            body { font-family: sans-serif; padding: 20px; background-color: #f4f4f9; }
            h1 { color: #333; }
            #status { color: #666; font-style: italic; }
            #container { 
                margin-top: 20px; padding: 20px; 
                background: white; border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                min-height: 200px; max-height: 400px;
                overflow-y: auto; font-size: 1.2rem;
            }
            .transcription-line { border-bottom: 1px solid #eee; padding: 8px 0; }
        </style>
    </head>
    <body>
        <h1>Live Audio Transcription</h1>
        <p id="status">Connecting to server...</p>
        <div id="container"></div>
        <script>
            var ws = new WebSocket("ws://" + location.host + "/ws");
            var statusEl = document.getElementById("status");
            var container = document.getElementById("container");

            ws.onopen = function() {
                statusEl.innerText = "Connected! Speak into your ESP32 microphone.";
                statusEl.style.color = "green";
            };
            
            ws.onmessage = function(event) {
                if (event.data === "LISTENING_START") {
                    statusEl.innerText = "🎙️ Listening... (recording phrase)";
                } else if (event.data === "LISTENING_STOP") {
                    statusEl.innerText = "⚙️ Processing audio...";
                } else {
                    statusEl.innerText = "Connected! Speak into your ESP32 microphone.";
                    var div = document.createElement('div');
                    div.className = "transcription-line";
                    div.appendChild(document.createTextNode("🗣️ " + event.data));
                    container.appendChild(div);
                    container.scrollTop = container.scrollHeight;
                }
            };

            ws.onclose = function() {
                statusEl.innerText = "Disconnected from server.";
                statusEl.style.color = "red";
            };
        </script>
    </body>
</html>
"""

# Global list of connected websocket clients
connected_clients = set()

def calculate_rms(audio_bytes):
    """Calculates the Root Mean Square energy to detect volume/speaking."""
    count = len(audio_bytes) // 2
    if count == 0:
        return 0
    # Unpack bytes into 16-bit integers
    shorts = struct.unpack(f"<{count}h", audio_bytes)
    sum_squares = sum(int(s)*int(s) for s in shorts)
    return math.sqrt(sum_squares / count)

def transcribe_audio_bytes(audio_bytes):
    """Sends the raw WAV bytes to Google Speech recognition."""
    recognizer = sr.Recognizer()
    
    # Create an in-memory WAV file from the raw bytes
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)
        
    wav_io.seek(0)
    
    try:
        with sr.AudioFile(wav_io) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio)
        return text
    except sr.UnknownValueError:
        return "" # Audio was silent or unintelligible
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""

async def broadcast_message(message: str):
    for client in list(connected_clients):
        try:
            await client.send_text(message)
        except Exception:
            connected_clients.remove(client)

def audio_listener_loop(active_loop):
    """Background thread that continuously reads the serial port for audio."""
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        ser.reset_input_buffer()
        print("Live Listener Started. Waiting for voice...")
        
        is_speaking = False
        silence_count = 0
        phrase_buffer = bytearray()
        
        while True:
            # Read 0.5s chunks of audio
            chunk = ser.read(CHUNK_BYTES)
            if len(chunk) < CHUNK_BYTES:
                continue # Wait for a full chunk
                
            rms = calculate_rms(chunk)
            
            # Simple Voice Activity Detection (VAD)
            if rms > SILENCE_THRESHOLD:
                if not is_speaking:
                    is_speaking = True
                    # Let the UI know we started hearing something
                    asyncio.run_coroutine_threadsafe(broadcast_message("LISTENING_START"), active_loop)
                    print(f"[{rms:.0f}] User started speaking...")
                
                phrase_buffer.extend(chunk)
                silence_count = 0
            
            elif is_speaking:
                # Still buffer the quiet tail end of a word
                phrase_buffer.extend(chunk)
                silence_count += 1
                
                # If they've been quiet for a few chunks (e.g., 2 chunks = 1.0s)
                if silence_count >= MAX_SILENCE_CHUNKS:
                    print("User stopped speaking. Transcribing...")
                    asyncio.run_coroutine_threadsafe(broadcast_message("LISTENING_STOP"), active_loop)
                    is_speaking = False
                    
                    # Transcribe what we captured in the buffer asynchronously!
                    if len(phrase_buffer) > (CHUNK_BYTES * 2): # At least 1 second of audio
                        
                        # Copy buffer so we can reset the main one immediately
                        buffer_copy = bytearray(phrase_buffer) 
                        
                        def do_transcribe(buf):
                            txt = transcribe_audio_bytes(buf)
                            if txt:
                                print(f"Transcribed: {txt}")
                                asyncio.run_coroutine_threadsafe(broadcast_message(txt), active_loop)
                            else:
                                print("Transcription returned empty.")
                                # Let UI know we are done processing even if it failed
                                asyncio.run_coroutine_threadsafe(broadcast_message(""), active_loop) 

                        # Run the heavy, blocking Google API call in a background executor
                        active_loop.run_in_executor(None, do_transcribe, buffer_copy)
                        
                    # Reset buffer for the next phrase instantly so we don't miss words
                    phrase_buffer = bytearray()
                    
    except serial.SerialException as e:
        print(f"Serial port disconnected or unavailable: {e}")
        time.sleep(5)
    except Exception as e:
        print(f"Error in audio loop: {e}")

@app.get("/")
async def get():
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

# Start the background serial listener thread when FastAPI starts up
@app.on_event("startup")
async def startup_event():
    active_loop = asyncio.get_running_loop()
    thread = threading.Thread(target=audio_listener_loop, args=(active_loop,), daemon=True)
    thread.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
