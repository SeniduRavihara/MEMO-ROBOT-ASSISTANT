import os
import io
import time
import struct
import socket
import math
import asyncio
import threading
import wave
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.types import HarmCategory, HarmBlockThreshold
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import speech_recognition as sr

load_dotenv()

# --- AI CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set! Please add it to the .env file.")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

ROBOT_SYSTEM_INSTRUCTION = """You are MEMO, a friendly AI robot assistant.
Reply conversationally and helpfully. Be concise but give complete sentences.
You can understand English and Sinhala."""

# Models to try in order - fallback if one is rate-limited
MODELS_TO_TRY = [
    'gemini-3-flash-preview',
    'gemini-2.0-flash',
    'gemini-1.5-flash',
]

# --- NETWORK CONFIGURATION ---
TCP_PORT = 8002
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 500
MAX_SILENCE_SECONDS = 0.8

app = FastAPI(title="Gemini AI Robot")

# Global state
connected_clients = set()
current_language = "en-US"

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

def transcribe_audio(audio_bytes, lang):
    recognizer = sr.Recognizer()
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
        return recognizer.recognize_google(audio, language=lang)
    except:
        return ""

def ask_gemini(text):
    """Try each model in the fallback list until one works."""
    last_error = None
    for model_name in MODELS_TO_TRY:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=text,
                config=types.GenerateContentConfig(
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
            # response.text can be None if safety-filtered
            return (response.text or "").strip() or "Hmm, I could not reply."
        except Exception as e:
            print(f"[Model {model_name}] failed: {e}")
            last_error = e
            time.sleep(1)  # pause before trying next model
    raise last_error

async def broadcast(msg):
    for client in list(connected_clients):
        try: await client.send_text(msg)
        except: connected_clients.discard(client)

def audio_listener_loop(active_loop, target_ip):
    """TCP Client logic to connect to the Robot."""
    print(f"Connecting to Robot at {target_ip}:{TCP_PORT}...")
    
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((target_ip, TCP_PORT))
            sock.settimeout(None)
            print("Connected to Robot Wi-Fi!")
            asyncio.run_coroutine_threadsafe(broadcast("STATUS:✅ Connected! Speak."), active_loop)
            
            is_speaking = False
            silence_start = 0
            phrase_buffer = bytearray()
            
            while True:
                chunk = sock.recv(1024)
                if not chunk: break
                
                rms = calculate_rms(chunk)
                if rms > SILENCE_THRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        asyncio.run_coroutine_threadsafe(broadcast("LISTENING_START"), active_loop)
                    phrase_buffer.extend(chunk)
                    silence_start = 0
                else:
                    if is_speaking:
                        phrase_buffer.extend(chunk)
                        if silence_start == 0: silence_start = time.time()
                        elif time.time() - silence_start > MAX_SILENCE_SECONDS:
                            is_speaking = False
                            silence_start = 0
                            asyncio.run_coroutine_threadsafe(broadcast("LISTENING_STOP"), active_loop)
                            
                            buffer_copy = bytearray(phrase_buffer)
                            phrase_buffer = bytearray()
                            lang_now = current_language
                            
                            def handle_ai(buf, lang, s):
                                text = transcribe_audio(buf, lang)
                                if not text:
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:✅ Speak."), active_loop)
                                    return
                                
                                print(f"You said: {text}")
                                asyncio.run_coroutine_threadsafe(broadcast(f"USER:{text}"), active_loop)
                                
                                try:
                                    ai_text = ask_gemini(text)
                                    print(f"Gemini: {ai_text}")
                                    s.sendall((ai_text + "\n").encode('utf-8'))
                                    asyncio.run_coroutine_threadsafe(broadcast(f"AI:{ai_text}"), active_loop)
                                except Exception as e:
                                    print("All Gemini models failed:", e)
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:❌ AI Error"), active_loop)

                            active_loop.run_in_executor(None, handle_ai, buffer_copy, lang_now, sock)
            
        except Exception as e:
            print(f"Connection error: {e}")
            asyncio.run_coroutine_threadsafe(broadcast("STATUS:❌ Searching for Robot..."), active_loop)
            time.sleep(3)
        finally:
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
