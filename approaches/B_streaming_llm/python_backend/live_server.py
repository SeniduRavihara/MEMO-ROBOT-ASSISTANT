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
import numpy as np
import edge_tts
from pydub import AudioSegment
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from google.genai.types import HarmCategory, HarmBlockThreshold
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

load_dotenv()

# --- AI CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set! Please add it to the .env file.")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

ROBOT_SYSTEM_INSTRUCTION = """You are MEMO, a small AI robot with a tiny screen. You are having a live voice chat.
RULES:
- Reply in 1 SHORT sentence only (max 15 words). Never write long answers.
- You understand Sinhala, Singlish, and English. Always reply in English.
- Be warm and natural. Skip filler like "Sure!", "Of course!", "Great question!".
- NEVER say "How can I help you?" or "Is there anything else?" — just answer directly.
- NEVER claim you only understand English or refuse non-English input."""

# Models to try in order - fallback if one is rate-limited
MODELS_TO_TRY = [
    'gemini-flash-lite-latest',
    'gemini-3.1-flash-lite',
    'gemini-2.5-flash',
]

# --- NETWORK CONFIGURATION ---
TCP_PORT = 8005
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 200  # Lower = more sensitive mic detection
MAX_SILENCE_SECONDS = 0.35  # Seconds of silence before sending to Gemini (shorter = faster response)

app = FastAPI(title="Gemini AI Robot")

# Global state
connected_clients = set()
current_language = "en-US"
robot_socket = None
socket_lock = threading.Lock()
is_processing_ai = False
conversation_history = collections.deque(maxlen=6)

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

def apply_agc(audio_bytes, gain):
    """Apply dynamic Software AGC gain scaling to 16-bit PCM samples without clipping."""
    if gain == 1.0:
        return audio_bytes
    count = len(audio_bytes) // 2
    if count == 0:
        return audio_bytes
    shorts = struct.unpack(f"<{count}h", audio_bytes)
    scaled = []
    for s in shorts:
        val = int(s * gain)
        if val > 32767: val = 32767
        elif val < -32768: val = -32768
        scaled.append(val)
    return struct.pack(f"<{count}h", *scaled)

def trim_silence_pcm(audio_bytes, threshold=150, frame_size=640):
    """Strip leading/trailing silent frames from 16-bit PCM to reduce upload payload.
    frame_size=640 bytes = 320 samples = 20ms at 16kHz."""
    if len(audio_bytes) < frame_size:
        return audio_bytes
    total_frames = len(audio_bytes) // frame_size
    if total_frames == 0:
        return audio_bytes
    
    # Find first non-silent frame
    start_frame = 0
    for i in range(total_frames):
        frame = audio_bytes[i * frame_size : (i + 1) * frame_size]
        rms = calculate_rms(frame)
        if rms > threshold:
            start_frame = max(0, i - 2)  # Keep 2 frames (~40ms) before speech starts
            break
    else:
        return audio_bytes  # All silent — return as-is for "no speech" detection
    
    # Find last non-silent frame
    end_frame = total_frames - 1
    for i in range(total_frames - 1, -1, -1):
        frame = audio_bytes[i * frame_size : (i + 1) * frame_size]
        rms = calculate_rms(frame)
        if rms > threshold:
            end_frame = min(total_frames - 1, i + 2)  # Keep 2 frames (~40ms) after speech ends
            break
    
    trimmed = audio_bytes[start_frame * frame_size : (end_frame + 1) * frame_size]
    saved_pct = 100 - (len(trimmed) * 100 // len(audio_bytes))
    if saved_pct > 5:
        print(f"[Trim] Removed {saved_pct}% silence from audio ({len(audio_bytes)} → {len(trimmed)} bytes)")
    return trimmed

# ── LOCAL WHISPER STT MODEL ───────────────────────────────────────────────
print("⏳ Loading Whisper STT model...")
try:
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    print("✅ Whisper STT model loaded!")
except Exception as e:
    print(f"⚠️ Whisper load failed: {e}. Will use Gemini STT fallback.")
    whisper_model = None

# ── STEP 1: Speech-to-Text (audio → transcript) ──────────────────────────
def transcribe_audio(audio_bytes):
    """Fast local STT using Whisper. Falls back to Gemini if Whisper unavailable."""
    # Trim silence to reduce processing
    audio_bytes = trim_silence_pcm(audio_bytes)
    
    # Try local Whisper first (fast, free, no network)
    if whisper_model:
        try:
            t0 = time.time()
            # Convert 16-bit PCM bytes to float32 numpy array for Whisper
            pcm_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_float32 = pcm_int16.astype(np.float32) / 32768.0
            
            segments, info = whisper_model.transcribe(
                audio_float32,
                beam_size=1,
                language=None,  # Auto-detect (supports Sinhala + English)
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=200),
            )
            transcript = " ".join([seg.text.strip() for seg in segments]).strip()
            elapsed = int((time.time() - t0) * 1000)
            print(f"[STT] ({elapsed}ms, whisper-base) → \"{transcript}\"")
            
            if not transcript:
                return ""
            return transcript
        except Exception as e:
            print(f"[Whisper STT error]: {e}, falling back to Gemini...")
    
    # Fallback: Gemini cloud STT
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)
    wav_bytes = wav_io.getvalue()
    
    for model_name in MODELS_TO_TRY:
        try:
            t0 = time.time()
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type='audio/wav'),
                    "Transcribe the spoken words in this audio. The speaker may use Sinhala, Singlish, or English. "
                    "Output ONLY the transcription text, nothing else. If there is no speech, output exactly: [SILENCE]"
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=100,
                    safety_settings=[
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                    ]
                )
            )
            elapsed = int((time.time() - t0) * 1000)
            transcript = response.text.strip()
            print(f"[STT] ({elapsed}ms, {model_name}) → \"{transcript}\"")
            if not transcript or "[SILENCE]" in transcript:
                return ""
            return transcript
        except Exception as e:
            print(f"[STT {model_name}] error: {e}")
            if "429" not in str(e):
                time.sleep(0.2)
    return ""

# ── STEP 2: Text-to-Response (transcript → AI reply) ─────────────────────
def ask_gemini_stream(user_transcript, robot_sock):
    """⚡ STREAMING LLM: sends each word to OLED as Gemini generates it."""
    context = ""
    if conversation_history:
        context = "Recent conversation:\n" + "\n".join(
            [f"{role}: {msg}" for role, msg in conversation_history]
        ) + "\n\n"
    prompt = f"{context}User said: \"{user_transcript}\"\nReply in 1 short sentence (max 15 words)."
    
    full_text = ""
    t0 = time.time()
    
    for model_name in MODELS_TO_TRY:
        try:
            stream = gemini_client.models.generate_content_stream(
                model=model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    system_instruction=ROBOT_SYSTEM_INSTRUCTION,
                    max_output_tokens=60,
                    safety_settings=[
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                    ]
                )
            )
            for chunk in stream:
                if chunk.text:
                    full_text += chunk.text
            # Stream collected — return text (typewriter handled in caller)
            elapsed = int((time.time() - t0) * 1000)
            print(f"[LLM STREAM] ({elapsed}ms, {model_name}) → \"{full_text[:80]}\"")
            conversation_history.append(("User", user_transcript))
            conversation_history.append(("MEMO", full_text))
            return full_text.strip()
        except Exception as e:
            print(f"[LLM {model_name}] error: {e}")
            if "429" not in str(e): time.sleep(0.2)
    return ""

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
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(None)
            with socket_lock:
                robot_socket = sock
            # Instantly trigger ESP32 server.available() and update screen
            try: sock.sendall(b"TEXT:AI Robot Active! Speak now...\n")
            except: pass
            print("Connected to Robot Wi-Fi!")
            asyncio.run_coroutine_threadsafe(broadcast("STATUS:✅ Connected! Speak."), active_loop)
            
            is_speaking = False
            silence_start = 0
            phrase_buffer = bytearray()
            # 300ms Pre-Roll Ring Buffer (10 chunks * ~32ms = ~320ms)
            pre_roll_buffer = collections.deque(maxlen=10)
            # Adaptive Noise Floor (Exponential Moving Average)
            noise_floor_rms = 100.0
            
            # Software AGC (Automatic Gain Control) state
            agc_gain = 1.0
            TARGET_SPEECH_RMS = 3000.0
            
            while True:
                chunk = sock.recv(1024)
                if not chunk: break
                
                if is_processing_ai:
                    # Discard audio data while AI is processing to prevent overlapping requests
                    phrase_buffer.clear()
                    pre_roll_buffer.clear()
                    is_speaking = False
                    silence_start = 0
                    agc_gain = 1.0
                    continue
                
                rms = calculate_rms(chunk)
                
                # Calculate dynamic AGC gain during speech
                if rms > 0 and is_speaking:
                    ideal_gain = TARGET_SPEECH_RMS / rms
                    ideal_gain = max(1.0, min(ideal_gain, 4.0))
                    agc_gain = 0.9 * agc_gain + 0.1 * ideal_gain
                elif not is_speaking:
                    agc_gain = 0.95 * agc_gain + 0.05 * 1.0  # Reset gain smoothly when silent

                scaled_chunk = apply_agc(chunk, agc_gain)
                
                # Update adaptive noise floor when silent (EMA smoothing factor = 0.05)
                if not is_speaking:
                    noise_floor_rms = 0.95 * noise_floor_rms + 0.05 * rms
                
                # Dynamic VAD Threshold for Far-Field Listening (1.5x noise floor, minimum floor 250.0)
                dynamic_threshold = max(250.0, noise_floor_rms * 1.5)
                
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
                    phrase_buffer.extend(scaled_chunk)
                    silence_start = 0
                else:
                    if not is_speaking:
                        pre_roll_buffer.append(scaled_chunk)
                    else:
                        phrase_buffer.extend(scaled_chunk)
                        if silence_start == 0: silence_start = time.time()
                        elif time.time() - silence_start > MAX_SILENCE_SECONDS:
                            is_speaking = False
                            silence_start = 0
                            pre_roll_buffer.clear() # Clear pre-roll buffer to prevent repeating previous phrase
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
                                t_start = time.time()
                                
                                try:
                                    # STEP 1: Fast STT (audio → text)
                                    user_transcript = transcribe_audio(buf)
                                    
                                    if not user_transcript:
                                        print("[Skip] No speech detected, ignoring.")
                                        return
                                    
                                    # Deduplication filter
                                    if conversation_history and len(conversation_history) >= 2:
                                        last_user = conversation_history[-2][1]
                                        if user_transcript.lower() == last_user.lower():
                                            print(f"[Filter] Duplicate transcript '{user_transcript}' - skipping.")
                                            return
                                    
                                    print(f"You said: {user_transcript}")
                                    asyncio.run_coroutine_threadsafe(broadcast(f"USER:{user_transcript}"), active_loop)
                                    
                                    # ⚡ STREAMING: Gemini streams, returns text
                                    ai_text = ask_gemini_stream(user_transcript, s)
                                    
                                    total_ms = int((time.time() - t_start) * 1000)
                                    print(f"Gemini: {ai_text}  [{total_ms}ms total]")
                                    asyncio.run_coroutine_threadsafe(broadcast(f"AI:{ai_text}"), active_loop)

                                    # ⚡ PARALLEL: Start TTS generation NOW while typewriter plays
                                    pcm_result = []
                                    tts_ready = threading.Event()
                                    def _gen_tts():
                                        pcm_result.append(text_to_pcm(ai_text))
                                        tts_ready.set()
                                    threading.Thread(target=_gen_tts, daemon=True).start()

                                    # ⌨️ Typewriter: send word-by-word to OLED
                                    words = ai_text.replace('\n', ' ').strip().split()
                                    displayed = ""
                                    for word in words:
                                        displayed += (" " if displayed else "") + word
                                        with socket_lock:
                                            try: s.sendall(("TEXT:" + displayed + "\n").encode('utf-8'))
                                            except: pass
                                        time.sleep(0.05)  # 50ms per word

                                    # Wait for TTS (usually already done by now!)
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:🔊 Speaking..."), active_loop)
                                    tts_ready.wait(timeout=10)
                                    if pcm_result:
                                        speak_on_socket(pcm_result[0])
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
    robot_ip = "192.168.43.186"  # hardcoded ESP32 IP (HUAWEI nova 3i hotspot)
    # robot_ip = input("Enter the IP shown on Robot's screen: ").strip()  # uncomment to type manually
    
    loop = asyncio.get_running_loop()
    threading.Thread(target=audio_listener_loop, args=(loop, robot_ip), daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
