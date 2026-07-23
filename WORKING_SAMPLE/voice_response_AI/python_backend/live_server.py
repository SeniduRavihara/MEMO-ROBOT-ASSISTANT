import os
import io
import time
import struct
import socket
import collections
import math
import asyncio
import threading
import wave
import tempfile
import edge_tts
from pydub import AudioSegment
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.types import HarmCategory, HarmBlockThreshold
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json
from pydantic import BaseModel

load_dotenv()

# --- AI CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set! Please add it to the .env file.")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

ROBOT_SYSTEM_INSTRUCTION = """You are MEMO, a friendly AI robot assistant.
Always reply in ENGLISH ONLY. 
Be warm, friendly, and concise. 
NEVER use Sinhala characters or Singlish. Just plain English."""

# Models to try in order - fallback if one is rate-limited
MODELS_TO_TRY = [
    'gemini-3.1-flash-lite',
    'gemini-flash-lite-latest',
    'gemini-2.5-flash',
]

# --- NETWORK CONFIGURATION ---
TCP_PORT = 8005
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 200  # Lower = more sensitive mic detection
MAX_SILENCE_SECONDS = 0.5  # Seconds of silence before sending to Gemini (shorter = faster response)

app = FastAPI(title="Gemini AI Robot")

# Global state
connected_clients = set()
current_language = "en-US"
robot_socket = None
socket_lock = threading.Lock()
is_processing_ai = False

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Gemini AI Robot Control</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; background-color: #0f172a; color: #f8fafc; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { color: #38bdf8; text-align: center; margin-bottom: 30px; }
            #status { background: #1e293b; padding: 10px 20px; border-radius: 50px; text-align: center; font-weight: bold; margin-bottom: 20px; border: 1px solid #334155; }
            #chat-box { 
                background: #1e293b; border-radius: 12px; padding: 20px;
                min-height: 400px; max-height: 600px; overflow-y: auto;
                border: 1px solid #334155; display: flex; flex-direction: column; gap: 10px;
            }
            .message { padding: 12px 16px; border-radius: 18px; max-width: 80%; line-height: 1.4; }
            .user-msg { background: #0369a1; align-self: flex-end; border-bottom-right-radius: 4px; }
            .ai-msg { background: #334155; align-self: flex-start; border-bottom-left-radius: 4px; color: #38bdf8; }
            .lang-area { margin-bottom: 20px; display: flex; justify-content: center; gap: 15px; align-items: center; }
            select { background: #1e293b; color: white; border: 1px solid #334155; padding: 8px; border-radius: 6px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Gemini AI Robot</h1>
            <div class="lang-area">
                <label>Language:</label>
                <select id="lang-select">
                    <option value="en-US">English (US)</option>
                    <option value="si-LK">Sinhala (Sri Lanka)</option>
                </select>
            </div>
            <div id="status">Connecting to Robot...</div>
            <div id="chat-box"></div>
        </div>

        <script>
            var ws = new WebSocket("ws://" + location.host + "/ws");
            var chatBox = document.getElementById("chat-box");
            var statusEl = document.getElementById("status");
            var langSelect = document.getElementById("lang-select");

            langSelect.addEventListener('change', () => ws.send("LANG:" + langSelect.value));

            function addMessage(text, role) {
                var div = document.createElement("div");
                div.className = "message " + (role === 'user' ? 'user-msg' : 'ai-msg');
                div.innerText = (role === 'user' ? '👤 ' : '🤖 ') + text;
                chatBox.appendChild(div);
                chatBox.scrollTop = chatBox.scrollHeight;
            }

            ws.onmessage = (event) => {
                const data = event.data;
                if (data === "LISTENING_START") {
                    statusEl.innerText = "🎙️ Robot is listening...";
                    statusEl.style.color = "#38bdf8";
                } else if (data === "LISTENING_STOP") {
                    statusEl.innerText = "🧠 Thinking...";
                    statusEl.style.color = "#fbbf24";
                } else if (data.startsWith("USER:")) {
                    addMessage(data.replace("USER:", ""), "user");
                } else if (data.startsWith("AI:")) {
                    statusEl.innerText = "✅ Resting...";
                    statusEl.style.color = "#4ade80";
                    addMessage(data.replace("AI:", ""), "ai");
                } else if (data.startsWith("STATUS:")) {
                    statusEl.innerText = data.replace("STATUS:", "");
                }
            };
        </script>
    </body>
</html>
"""

def calculate_rms(audio_bytes):
    count = len(audio_bytes) // 2
    if count == 0: return 0
    shorts = struct.unpack(f"<{count}h", audio_bytes)
    sum_sq = sum(int(s)**2 for s in shorts)
    return math.sqrt(sum_sq / count)

class RobotResponse(BaseModel):
    user_transcript: str
    ai_response: str

def ask_gemini(audio_bytes):
    """Convert PCM bytes to WAV in memory and send directly to Gemini with structured output."""
    last_error = None
    
    # Wrap PCM bytes in a WAV header
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)
    wav_bytes = wav_io.getvalue()
    
    for model_name in MODELS_TO_TRY:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(
                        data=wav_bytes,
                        mime_type='audio/wav'
                    ),
                    "Listen to this audio. If you hear someone speaking, transcribe their speech exactly in 'user_transcript' and reply to them in 'ai_response'. If there is no speech (only silence, noise, or static), set 'user_transcript' to an empty string and set 'ai_response' to a polite message saying you didn't hear anything."
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RobotResponse,
                    system_instruction=ROBOT_SYSTEM_INSTRUCTION,
                    max_output_tokens=1024,
                    safety_settings=[
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                    ]
                )
            )
            print(f"[Gemini OK] model={model_name}")
            data = json.loads(response.text)
            return data.get("user_transcript", "").strip(), data.get("ai_response", "").strip()
        except Exception as e:
            print(f"[Model {model_name}] failed: {e}")
            last_error = e
            time.sleep(1)
    raise last_error

async def broadcast(msg):
    # Also include the robot_socket if we want to log to robot Serial
    for client in list(connected_clients):
        try: await client.send_text(msg)
        except: connected_clients.discard(client)

def text_to_pcm(text):
    """Convert text to raw 16kHz 16-bit mono PCM using edge-tts."""
    async def run():
        communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
        mp3_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])
        mp3_buf.seek(0)
        audio = AudioSegment.from_mp3(mp3_buf)
        # Boost volume by 10dB and ensure Stereo 16-bit
        audio = audio + 10 
        audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2)
        return audio.raw_data
    return asyncio.run(run())

def speak_on_socket(pcm_data):
    """Send a 4-byte length header + raw PCM data to the shared robot socket."""
    global robot_socket
    with socket_lock:
        if not robot_socket:
            print("[TTS] No robot connected to speak to.")
            return
        try:
            length = len(pcm_data)
            # Big-endian length header
            header = b'AUDIO' + struct.pack('>I', length)
            robot_socket.sendall(header)
            robot_socket.sendall(pcm_data)
            print(f"[TTS] Sent {length} PCM bytes to robot speaker.")
        except Exception as e:
            print(f"[TTS] Send error: {e}")
            robot_socket = None

def audio_listener_loop(active_loop, target_ip):
    """TCP Client logic to connect to the Robot."""
    print(f"Connecting to Robot at {target_ip}:{TCP_PORT}...")
    global robot_socket
    
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((target_ip, TCP_PORT))
            sock.settimeout(None)
            with socket_lock:
                robot_socket = sock
            print("Connected to Robot Wi-Fi!")
            asyncio.run_coroutine_threadsafe(broadcast("STATUS:✅ Connected! Speak."), active_loop)
            
            is_speaking = False
            silence_start = 0
            phrase_buffer = bytearray()
            # 300ms Pre-Roll Ring Buffer (10 chunks * ~32ms = ~320ms)
            pre_roll_buffer = collections.deque(maxlen=10)
            # Adaptive Noise Floor (Exponential Moving Average)
            noise_floor_rms = 100.0
            
            while True:
                chunk = sock.recv(1024)
                if not chunk: break
                
                if is_processing_ai:
                    # Discard audio data while AI is processing to prevent overlapping requests
                    phrase_buffer.clear()
                    pre_roll_buffer.clear()
                    is_speaking = False
                    silence_start = 0
                    continue
                
                rms = calculate_rms(chunk)
                
                # Update adaptive noise floor when silent (EMA smoothing factor = 0.05)
                if not is_speaking:
                    noise_floor_rms = 0.95 * noise_floor_rms + 0.05 * rms
                
                # Dynamic VAD Threshold: 1.8x the noise floor (minimum 150)
                dynamic_threshold = max(150.0, noise_floor_rms * 1.8)
                
                if rms > dynamic_threshold:
                    if not is_speaking:
                        is_speaking = True
                        # Include 300ms pre-roll buffer so initial quiet syllables aren't cut off
                        phrase_buffer.extend(b"".join(pre_roll_buffer))
                        pre_roll_buffer.clear()
                        # Instant display feedback on ESP32 screen
                        with socket_lock:
                            if robot_socket:
                                try: robot_socket.sendall(b"TEXT:Listening...\n")
                                except: pass
                        asyncio.run_coroutine_threadsafe(broadcast("LISTENING_START"), active_loop)
                    phrase_buffer.extend(chunk)
                    silence_start = 0
                else:
                    if not is_speaking:
                        pre_roll_buffer.append(chunk)
                    else:
                        phrase_buffer.extend(chunk)
                        if silence_start == 0: silence_start = time.time()
                        elif time.time() - silence_start > MAX_SILENCE_SECONDS:
                            is_speaking = False
                            silence_start = 0
                            # Instant status update on ESP32 screen when speech finishes
                            with socket_lock:
                                if robot_socket:
                                    try: robot_socket.sendall(b"TEXT:Thinking...\n")
                                    except: pass
                            asyncio.run_coroutine_threadsafe(broadcast("LISTENING_STOP"), active_loop)
                            
                            buffer_copy = bytearray(phrase_buffer)
                            phrase_buffer = bytearray()
                            lang_now = current_language
                            
                            def handle_ai(buf, lang, s):
                                global is_processing_ai
                                is_processing_ai = True
                                
                                try:
                                    user_transcript, ai_text = ask_gemini(buf)
                                    
                                    if not user_transcript:
                                        print("[Skip] No speech detected, ignoring.")
                                        return
                                    
                                    print(f"You said: {user_transcript}")
                                    asyncio.run_coroutine_threadsafe(broadcast(f"USER:{user_transcript}"), active_loop)
                                    
                                    print(f"Gemini: {ai_text}")
                                    # 1. Send text to OLED (use lock — same socket is being recv'd on main thread)
                                    clean_text = ai_text.replace('\n', ' ').strip()
                                    with socket_lock:
                                        s.sendall(("TEXT:" + clean_text + "\n").encode('utf-8'))
                                    print(f"[TCP] Sent TEXT to ESP32: {clean_text}")
                                    asyncio.run_coroutine_threadsafe(broadcast(f"AI:{ai_text}"), active_loop)
                                    # 2. Generate and send speech audio (DISABLED FOR BEEP TEST)
                                    # asyncio.run_coroutine_threadsafe(broadcast("STATUS:🔊 Speaking..."), active_loop)
                                    # pcm = text_to_pcm(clean_text)
                                    # speak_on_socket(pcm)
                                except Exception as e:
                                    print("Gemini voice pipeline failed:", e)
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:❌ AI Error"), active_loop)
                                    with socket_lock:
                                        robot_socket = None
                                finally:
                                    is_processing_ai = False
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:✅ Speak."), active_loop)

                            active_loop.run_in_executor(None, handle_ai, buffer_copy, lang_now, sock)
            
        except Exception as e:
            print(f"Connection error: {e}")
            with socket_lock:
                robot_socket = None
            asyncio.run_coroutine_threadsafe(broadcast("STATUS:❌ Searching for Robot..."), active_loop)
            time.sleep(3)
        finally:
            with socket_lock:
                robot_socket = None
            if 'sock' in locals(): sock.close()

@app.get("/")
async def get(): return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global current_language
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data.startswith("LANG:"):
                current_language = data.split(":")[1]
                print(f"Language: {current_language}")
    except WebSocketDisconnect:
        connected_clients.discard(websocket)

@app.on_event("startup")
async def startup_event():
    print("\n" + "="*40)
    print("🤖 GEMINI AI ROBOT INITIALIZING")
    print("="*40)
    robot_ip = input("Enter the IP shown on Robot's screen: ").strip()
    
    loop = asyncio.get_running_loop()
    threading.Thread(target=audio_listener_loop, args=(loop, robot_ip), daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
