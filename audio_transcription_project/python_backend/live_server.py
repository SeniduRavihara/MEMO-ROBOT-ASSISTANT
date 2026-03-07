import serial
import wave
import time
import os
import io
import struct
import socket
import math
import asyncio
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import speech_recognition as sr

app = FastAPI(title="Live Audio Transcription")

# Configuration matching the ESP32
# SERIAL_PORT = '/dev/ttyUSB0'  
# BAUD_RATE = 921600
SAMPLE_RATE = 16000

# --- TCP SERVER CONFIGURATION ---
TCP_IP = '0.0.0.0' # Listen on all network interfaces
TCP_PORT = 8002    # Port for ESP32 to connect to

# VAD (Voice Activity Detection) Settings
CHUNK_DURATION = 0.5  # Read serial in chunks of 0.5 seconds
CHUNK_BYTES = int(SAMPLE_RATE * 2 * CHUNK_DURATION) 
SILENCE_THRESHOLD = 500  # Adjust this if it's too sensitive or not sensitive enough
MAX_SILENCE_CHUNKS = 2   # How many silent chunks before we decide the user stopped talking
MAX_SILENCE_SECONDS = MAX_SILENCE_CHUNKS * CHUNK_DURATION # Derived from above

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Live Audio Transcription</title>
        <style>
            body { font-family: sans-serif; padding: 20px; background-color: #f4f4f9; }
            h1 { color: #333; }
            #controls { margin-top: 20px; }
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
        <h1>Live Audio Transcription (Wi-Fi)</h1>
        <div id="controls">
            <label for="lang-select"><strong>Transcription Language:</strong></label>
            <select id="lang-select">
                <option value="en-US">English (US)</option>
                <option value="si-LK">Sinhala (Sri Lanka)</option>
            </select>
        </div>
        <p id="status">Waiting for ESP32 to connect over Wi-Fi...</p>
        <div id="container"></div>
        <script>
            var ws = new WebSocket("ws://" + location.host + "/ws");
            var statusEl = document.getElementById("status");
            var container = document.getElementById("container");
            var langSelect = document.getElementById("lang-select");

            langSelect.addEventListener('change', function() {
                // Tell the server we changed the language
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send("LANG:" + this.value);
                }
            });

            ws.onopen = function() {
                statusEl.innerText = "Web Connected. Waiting for ESP32 Wi-Fi audio stream...";
                ws.send("LANG:" + langSelect.value);
            };
            
            ws.onmessage = function(event) {
                if (event.data === "LISTENING_START") {
                    statusEl.innerText = "🎙️ Listening... (recording phrase)";
                    statusEl.style.color = "blue";
                } else if (event.data === "LISTENING_STOP") {
                    statusEl.innerText = "⚙️ Processing audio...";
                    statusEl.style.color = "orange";
                } else if (event.data.startsWith("ESP32_CONNECTED")) {
                    statusEl.innerText = "✅ ESP32 Connected over Wi-Fi! Speak now.";
                    statusEl.style.color = "green";
                } else {
                    statusEl.innerText = "✅ ESP32 Connected over Wi-Fi! Speak now.";
                    statusEl.style.color = "green";
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

# The current language to transcribe in
current_language = "en-US"

def calculate_rms(audio_bytes):
    """Calculates the Root Mean Square energy to detect volume/speaking."""
    count = len(audio_bytes) // 2
    if count == 0:
        return 0
    # Unpack bytes into 16-bit integers
    shorts = struct.unpack(f"<{count}h", audio_bytes)
    sum_squares = sum(int(s)*int(s) for s in shorts)
    return math.sqrt(sum_squares / count)

def transcribe_audio_bytes(audio_bytes, lang):
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
        # Pass the desired language directly to the API
        text = recognizer.recognize_google(audio, language=lang)
        return text
    except sr.UnknownValueError:
        return "" # Audio was silent or unintelligible
    except sr.RequestError as e:
        print(f"Could not request results from Google Speech Recognition service; {e}")
        return ""

async def broadcast_message(message: str):
    """Sends a message to all connected webpage clients."""
    disconnected = set()
    for client in connected_clients:
        try:
            await client.send_text(message)
        except WebSocketDisconnect:
            disconnected.add(client)
        except Exception:
            disconnected.add(client)
    for client in disconnected:
        connected_clients.remove(client)

def audio_listener_loop(active_loop):
    """Runs a TCP server to receive audio from the ESP32 and streams it to Google."""
    print(f"Starting TCP Server on port {TCP_PORT} for ESP32...")
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((TCP_IP, TCP_PORT))
        server_socket.listen(1)
        print("Waiting for ESP32 TCP connection...")
        
        while True:
            client_socket, addr = server_socket.accept()
            print(f"ESP32 Connected from {addr}!")
            asyncio.run_coroutine_threadsafe(broadcast_message("ESP32_CONNECTED"), active_loop)
            
            is_speaking = False
            silence_start_time = 0
            phrase_buffer = bytearray()
            
            try:
                # Keep receiving data from the active ESP32 connection
                while True:
                    # Read chunks from the TCP stream (ESP32 sends 1024 bytes per chunk)
                    chunk = client_socket.recv(1024)
                    
                    if not chunk:
                        print("ESP32 connection closed.")
                        break # Break inner loop, wait for a new connection
                        
                    # Calculate volume of this tiny chunk
                    rms = calculate_rms(chunk)
                    
                    # Voice Activity Detection (VAD) logic
                    if rms > SILENCE_THRESHOLD:
                        if not is_speaking:
                            print(f"[{int(rms)}] User started speaking...")
                            is_speaking = True
                            asyncio.run_coroutine_threadsafe(broadcast_message("LISTENING_START"), active_loop)
                        phrase_buffer.extend(chunk)
                        silence_start_time = 0 # Reset silence timer
                    else:
                        if is_speaking:
                            phrase_buffer.extend(chunk) # Still buffer the quiet tail end
                            if silence_start_time == 0:
                                silence_start_time = time.time()
                            elif time.time() - silence_start_time > MAX_SILENCE_SECONDS:
                                print("User stopped speaking. Transcribing...")
                                is_speaking = False
                                silence_start_time = 0
                                
                                asyncio.run_coroutine_threadsafe(broadcast_message("LISTENING_STOP"), active_loop)
                                
                                # Process the audio buffer completely asynchronously!
                                if len(phrase_buffer) > (SAMPLE_RATE * 2 * 0.5): # At least 0.5 seconds of audio
                                    buffer_copy = bytearray(phrase_buffer) 
                                    
                                    def do_transcribe(buf, lang_to_use, sock):
                                        txt = transcribe_audio_bytes(buf, lang_to_use)
                                        if txt:
                                            print(f"Transcribed [{lang_to_use}]: {txt}")
                                            try:
                                                # Send text back to ESP32 over TCP so it can display it!
                                                sock.sendall((txt + "\n").encode('utf-8'))
                                            except Exception as e:
                                                print("TCP write error:", e)
                                            asyncio.run_coroutine_threadsafe(broadcast_message(txt), active_loop)
                                        else:
                                            print(f"Transcription [{lang_to_use}] returned empty.")
                                            asyncio.run_coroutine_threadsafe(broadcast_message(""), active_loop) 

                                    lang_snapshot = current_language
                                    # Run the heavy, blocking Google API call in a background executor
                                    active_loop.run_in_executor(None, do_transcribe, buffer_copy, lang_snapshot, client_socket)
                                
                                # Reset buffer for the next phrase instantly so we don't miss words
                                phrase_buffer = bytearray()
            except Exception as e:
                print(f"TCP client error: {e}")
            finally:
                client_socket.close()
                print("Waiting for ESP32 to reconnect...")
    except Exception as e:
        print(f"TCP server error: {e}")
    finally:
        server_socket.close()

@app.get("/")
async def get():
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global current_language
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data.startswith("LANG:"):
                new_lang = data.split(":")[1]
                print(f"Client changed language to: {new_lang}")
                current_language = new_lang
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
