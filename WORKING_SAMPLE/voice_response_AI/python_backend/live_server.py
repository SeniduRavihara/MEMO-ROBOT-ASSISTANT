import os
import io
import re
import time
import struct
import socket
import collections
import math
import asyncio
import threading
import concurrent.futures
import wave
import tempfile
import numpy as np
import edge_tts
from pydub import AudioSegment
import builtins
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from google.genai.types import HarmCategory, HarmBlockThreshold
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

load_dotenv()

# --- TIMESTAMP PRINT WRAPPER ---
_orig_print = builtins.print
turn_start_time = None

def tprint(*args, **kwargs):
    if not args:
        _orig_print(**kwargs)
        return
    if turn_start_time is not None:
        elapsed = time.time() - turn_start_time
        prefix = f"[+{elapsed:.2f}s] "
    else:
        prefix = f"[{time.strftime('%H:%M:%S')}] "

    sep = kwargs.pop("sep", " ")
    first = str(args[0])
    newlines = len(first) - len(first.lstrip("\n"))
    if newlines > 0:
        prefix = ("\n" * newlines) + prefix
        args = (first.lstrip("\n"),) + args[1:]

    msg = sep.join(str(a) for a in args)
    _orig_print(prefix + msg, **kwargs)

builtins.print = tprint

# --- AI CONFIGURATION ---
raw_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
all_keys = [k.strip() for k in raw_keys.split(",") if len(k.strip()) > 20]
if not all_keys:
    raise ValueError("No valid GEMINI_API_KEYS found in .env!")

# Prioritize direct AIzaSy keys first, secondary keys last
API_KEYS = sorted(all_keys, key=lambda k: 0 if k.startswith("AIzaSy") else 1)

CANDIDATE_MODELS = [
    'gemini-3.5-flash-lite',
    'gemini-flash-lite-latest',
    'gemini-3.6-flash',
    'gemini-2.5-flash',
]

verified_pool = []
key_lock = threading.Lock()
current_pool_idx = 0
key_cooldowns = {}  # {pool_index: cooldown_expiry_timestamp}

print(f"🔍 Pre-flight auditing {len(API_KEYS)} Gemini key(s) to verify active models...")

def audit_single_key(idx, key_str):
    client = genai.Client(api_key=key_str)
    for model in CANDIDATE_MODELS:
        try:
            client.models.generate_content(model=model, contents=["ping"])
            return {
                "idx": idx,
                "client": client,
                "model": model,
                "key_str": key_str,
                "label": f"Key #{idx + 1} ({key_str[:8]}...{key_str[-4:]})"
            }
        except Exception:
            continue
    return None

with concurrent.futures.ThreadPoolExecutor(max_workers=len(API_KEYS)) as executor:
    futures = [executor.submit(audit_single_key, i, k) for i, k in enumerate(API_KEYS)]
    for f in concurrent.futures.as_completed(futures):
        res = f.result()
        if res:
            verified_pool.append(res)
            print(f"   ✅ {res['label']} -> Locked to [{res['model']}]")
        else:
            print(f"   ⚠️ Key excluded: no compatible models found.")

verified_pool.sort(key=lambda item: item["idx"])

if not verified_pool:
    # Emergency fallback
    for i, k in enumerate(API_KEYS):
        verified_pool.append({
            "idx": i,
            "client": genai.Client(api_key=k),
            "model": "gemini-3.5-flash-lite",
            "key_str": k,
            "label": f"Key #{i + 1}"
        })

print(f"🚀 AI Pool ready: {len(verified_pool)} verified key(s) active!\n")

def get_next_healthy_entry(start_idx=None):
    """Select the next key in the pool that is not cooling down."""
    global current_pool_idx
    now = time.time()
    with key_lock:
        if start_idx is None:
            start_idx = current_pool_idx
            current_pool_idx = (current_pool_idx + 1) % len(verified_pool)
        for i in range(len(verified_pool)):
            candidate_idx = (start_idx + i) % len(verified_pool)
            if key_cooldowns.get(candidate_idx, 0) <= now:
                return verified_pool[candidate_idx], candidate_idx
        best_idx = min(key_cooldowns.keys(), key=lambda idx: key_cooldowns[idx]) if key_cooldowns else 0
        return verified_pool[best_idx], best_idx
ROBOT_SYSTEM_INSTRUCTION = """You are MEMO, a friendly little AI robot with a tiny screen. You are having a live voice chat.
RULES:
- Reply in 1 SHORT sentence only (max 12 words). Never write long answers.
- Speak naturally and warmly in plain words only.
- NEVER use asterisks (*), underscores (_), markdown formatting, emojis, or sound actions like *beep boop* or *zoom*. Output plain spoken English words only.
- You understand Sinhala, Singlish, and English. Always reply in English.
- Skip filler like "Sure!", "Of course!", "Great question!".
- NEVER say "How can I help you?" or "Is there anything else?" — just answer directly.
- NEVER claim you only understand English or refuse non-English input."""

# --- NETWORK CONFIGURATION ---
TCP_PORT = 8005
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 200  # Lower = more sensitive mic detection
MAX_SILENCE_SECONDS = 0.65  # Seconds of silence before sending to Gemini (0.65s gives natural pause)

app = FastAPI(title="Gemini AI Robot")

# Global state
connected_clients = set()
current_language = "en-US"
robot_socket = None
socket_lock = threading.Lock()
is_processing_ai = False
mic_ignore_until = 0
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

def trim_silence_pcm(audio_bytes, threshold=220, frame_size=640):
    """Strip leading/trailing silent frames from 16-bit PCM without cutting spoken words.
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

# ── LOCAL PIPER TTS MODEL ─────────────────────────────────────────────────
PIPER_MODEL = os.path.expanduser("~/.local/share/piper/en_US-amy-medium.onnx")
piper_voice = None
try:
    from piper import PiperVoice
    if os.path.exists(PIPER_MODEL):
        piper_voice = PiperVoice.load(PIPER_MODEL)
        print("✅ Piper TTS loaded! (local, fast)")
    else:
        print("⚠️ Piper model not found. Will use edge-tts fallback.")
except Exception as e:
    print(f"⚠️ Piper TTS not available: {e}. Will use edge-tts fallback.")

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
            
            lang_code = "si" if "si" in current_language else "en"
            segments, info = whisper_model.transcribe(
                audio_float32,
                beam_size=1,
                language=lang_code,
                condition_on_previous_text=False,
                temperature=0.0,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=200),
            )
            transcript = " ".join([seg.text.strip() for seg in segments]).strip()
            elapsed = int((time.time() - t0) * 1000)
            print(f"[STT] ({elapsed}ms, whisper-tiny, lang={lang_code}) → \"{transcript}\"")
            
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
    
    for entry in verified_pool:
        try:
            t0 = time.time()
            response = entry["client"].models.generate_content(
                model=entry["model"],
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
            print(f"[STT] ({elapsed}ms, {entry['model']}, {entry['label']}) → \"{transcript}\"")
            if not transcript or "[SILENCE]" in transcript:
                return ""
            return transcript
        except Exception as e:
            print(f"[STT {entry['label']}] error: {e}")
            if "429" not in str(e):
                time.sleep(0.2)
    return ""

# ── UPGRADE: Audio → AI (skip Whisper, STT+LLM in ONE Gemini call) ────────
def ask_gemini_audio(audio_bytes):
    """Sends raw audio directly to Gemini Flash → gets AI reply in 1 call.
    Combines STT + LLM → saves ~600ms vs separate Whisper + LLM."""
    audio_bytes = trim_silence_pcm(audio_bytes)
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)
    wav_bytes = wav_io.getvalue()

    prompt = (ROBOT_SYSTEM_INSTRUCTION +
              "\n\nListen to what the user said and reply directly as MEMO. "
              "If there is no speech or only background noise, reply: [SILENCE]")

    for model_name in MODELS_TO_TRY:
        try:
            t0 = time.time()
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type='audio/wav'),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=60,
                    safety_settings=[
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                    ]
                )
            )
            elapsed = int((time.time() - t0) * 1000)
            ai_text = response.text.strip() if response.text else ""
            print(f"[AUDIO→AI] ({elapsed}ms, {model_name}) → \"{ai_text[:60]}\"")
            if not ai_text or "[SILENCE]" in ai_text:
                return ""
            return ai_text
        except Exception as e:
            print(f"[AUDIO→AI {model_name}] error: {e}")
            if "429" not in str(e):
                time.sleep(0.2)
    return ""


# ── STEP 2: Text-to-Response (transcript → AI reply) ─────────────────────
def ask_gemini_text(user_transcript):
    """Fast text-only LLM call using verified key & model pool with instant failover."""
    last_error = None
    
    # Build conversation context for continuity
    context = ""
    if conversation_history:
        context = "Recent conversation:\n" + "\n".join(
            [f"{role}: {msg}" for role, msg in conversation_history]
        ) + "\n\n"
    
    prompt = f"{context}User said: \"{user_transcript}\"\nReply in 1 short sentence (max 15 words)."
    
    entry, pool_idx = get_next_healthy_entry()
    
    def do_call(c, m):
        return c.models.generate_content(
            model=m,
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
    
    for _ in range(len(verified_pool)):
        client = entry["client"]
        model_name = entry["model"]
        label = entry["label"]
        try:
            t0 = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(do_call, client, model_name)
                response = future.result(timeout=6.0)
            
            elapsed = int((time.time() - t0) * 1000)
            ai_text = response.text.strip() if response.text else "I hear you."
            print(f"[LLM] ({elapsed}ms, {model_name}, {label}) → \"{ai_text[:80]}\"")
            
            conversation_history.append(("User", user_transcript))
            conversation_history.append(("MEMO", ai_text))
            return ai_text
        except concurrent.futures.TimeoutError:
            print(f"[LLM Timeout] {label} took >6.0s! Putting on 60s cooldown...")
            key_cooldowns[pool_idx] = time.time() + 60
            entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
        except Exception as e:
            err_str = str(e)
            last_error = e
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                print(f"[KeyManager] ⚠️ {label} quota limit reached. Switching to next key...")
                key_cooldowns[pool_idx] = time.time() + 60
                entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
            elif "503" in err_str:
                print(f"[KeyManager] ⚠️ {label} Google high demand (503). Switching to next key...")
                entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
            else:
                print(f"[LLM Error] {label}: {e}. Switching to next key...")
                entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
                time.sleep(0.05)
                
    print(f"[LLM] ⚠️ All Gemini keys failed or timed out: {last_error}. Using fallback response.")
    return "I had a connection delay, could you say that again?"

async def broadcast(msg):
    # Also include the robot_socket if we want to log to robot Serial
    for client in list(connected_clients):
        try: await client.send_text(msg)
        except: connected_clients.discard(client)

def text_to_pcm(text):
    """Convert text to raw 16kHz 16-bit stereo PCM using edge-tts (cloud fallback)."""
    async def run():
        communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
        mp3_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])
        mp3_buf.seek(0)
        audio = AudioSegment.from_mp3(mp3_buf)
        audio = audio + 10
        audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2)
        return audio.raw_data
    return asyncio.run(run())

def text_to_pcm_fast(text):
    """Local piper-tts TTS (~300-500ms). Natural Amy voice."""
    if piper_voice:
        try:
            t0 = time.time()
            raw_bytes = bytearray()
            for chunk in piper_voice.synthesize(text):
                raw_bytes.extend(chunk.audio_int16_bytes)
            audio = AudioSegment(
                data=bytes(raw_bytes),
                sample_width=2,
                frame_rate=piper_voice.config.sample_rate,
                channels=1
            )
            audio = (audio + 10).set_frame_rate(16000).set_channels(2).set_sample_width(2)
            elapsed = int((time.time() - t0) * 1000)
            print(f"[TTS-Piper] ({elapsed}ms) {len(audio.raw_data)} bytes")
            return audio.raw_data
        except Exception as e:
            print(f"[TTS-Piper] Error: {e} — falling back to edge-tts")
    return text_to_pcm(text)



def speak_on_socket(pcm_data):
    """Send a 4-byte length header + raw PCM data to the shared robot socket in one combined packet."""
    global robot_socket
    with socket_lock:
        if not robot_socket:
            print("[TTS] No robot connected to speak to.")
            return
        try:
            length = len(pcm_data)
            # Big-endian length header combined with payload to avoid packet fragmentation
            header = b'AUDIO' + struct.pack('>I', length)
            robot_socket.sendall(header + pcm_data)
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
            
            loud_chunk_count = 0
            
            while True:
                chunk = sock.recv(1024)
                if not chunk: break
                
                if is_processing_ai or time.time() < mic_ignore_until:
                    # Discard audio data while AI is processing or during post-speech acoustic cooldown
                    phrase_buffer.clear()
                    pre_roll_buffer.clear()
                    is_speaking = False
                    silence_start = 0
                    loud_chunk_count = 0
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
                
                # Dynamic VAD Threshold for Intentional Speech (sensitive to human voice, speaker echo blocked by cooldown)
                dynamic_threshold = max(380.0, noise_floor_rms * 1.6)
                
                if not is_speaking:
                    if rms > dynamic_threshold:
                        loud_chunk_count += 1
                        # Require 2 consecutive loud chunks (~64ms) to debounce clicks
                        if loud_chunk_count >= 2:
                            is_speaking = True
                            # Include 300ms pre-roll buffer so initial quiet syllables aren't cut off
                            phrase_buffer.extend(b"".join(pre_roll_buffer))
                            pre_roll_buffer.clear()
                            phrase_buffer.extend(scaled_chunk)
                            silence_start = 0
                            # Instant display feedback on ESP32 screen
                            with socket_lock:
                                if robot_socket:
                                    try: robot_socket.sendall(b"TEXT:Listening...\n")
                                    except: pass
                            asyncio.run_coroutine_threadsafe(broadcast("LISTENING_START"), active_loop)
                    else:
                        loud_chunk_count = 0
                        pre_roll_buffer.append(scaled_chunk)
                else:
                    # DURING SPEECH: Never drop chunks! Record every syllable smoothly!
                    phrase_buffer.extend(scaled_chunk)
                    if rms > dynamic_threshold:
                        silence_start = 0
                    else:
                        if silence_start == 0:
                            silence_start = time.time()
                        elif time.time() - silence_start > MAX_SILENCE_SECONDS:
                            global turn_start_time
                            turn_start_time = time.time()
                            is_speaking = False
                            silence_start = 0
                            loud_chunk_count = 0
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
                                global is_processing_ai, turn_start_time
                                is_processing_ai = True
                                if turn_start_time is None:
                                    turn_start_time = time.time()
                                t_start = turn_start_time
                                
                                try:
                                    # Discard noise blips under 0.35s (less than 11,000 bytes)
                                    if len(buf) < 11000:
                                        return
                                    
                                    # STEP 1: Fast Local STT (audio → text via Whisper)
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

                                    # STEP 2: Fast text-only LLM (text → response)
                                    ai_text = ask_gemini_text(user_transcript)

                                    total_ms = int((time.time() - t_start) * 1000)
                                    print(f"MEMO: {ai_text}  [{total_ms}ms total]")

                                    # Strip asterisks (*), markdown formatting, and emojis so Piper never says 'asterisk'
                                    clean_text = re.sub(r'[*_#~`]', '', ai_text)
                                    clean_text = clean_text.encode('ascii', 'ignore').decode('ascii')
                                    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                                    
                                    # Send clean text to OLED
                                    with socket_lock:
                                        s.sendall(("TEXT:" + clean_text + "\n").encode('utf-8'))
                                    asyncio.run_coroutine_threadsafe(broadcast(f"AI:{clean_text}"), active_loop)

                                    # STEP 3: FAST Local TTS (Piper TTS ~300-500ms on CPU, no cloud)
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:🔊 Speaking..."), active_loop)
                                    pcm = text_to_pcm_fast(clean_text)
                                    speak_on_socket(pcm)

                                    # Prevent acoustic feedback: keep mic muted until speaker completes playback!
                                    # 16kHz 16-bit stereo = 64,000 bytes/sec
                                    if pcm:
                                        audio_duration = len(pcm) / 64000.0
                                        # Extra buffer for large speaker cone decay & acoustic reverberation
                                        time.sleep(audio_duration + 0.65)
                                except Exception as e:
                                    print("Gemini voice pipeline failed:", e)
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:❌ AI Error"), active_loop)
                                finally:
                                    # Set acoustic cooldown: discard residual large speaker echo from socket
                                    global mic_ignore_until
                                    mic_ignore_until = time.time() + 0.5
                                    is_processing_ai = False
                                    turn_start_time = None
                                    with socket_lock:
                                        if robot_socket:
                                            try: robot_socket.sendall(b"TEXT:MEMO Ready! Speak...\n")
                                            except: pass
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
