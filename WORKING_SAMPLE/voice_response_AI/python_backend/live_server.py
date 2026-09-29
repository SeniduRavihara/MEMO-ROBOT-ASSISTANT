import socket
# Force IPv4 across all network operations to prevent mobile carrier / hotspot IPv6 blackholes from hanging connections
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

import os
import io
import re
import time
import struct
import collections
import queue
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

verified_pool = []
key_lock = threading.Lock()
current_pool_idx = 0
key_cooldowns = {}  # {pool_index: cooldown_expiry_timestamp}

# Fast instant initialization (gemini-3.5-flash-lite verified working across all keys)
for idx, key_str in enumerate(API_KEYS):
    verified_pool.append({
        "idx": idx,
        "client": genai.Client(api_key=key_str),
        "model": "gemini-3.5-flash-lite",
        "key_str": key_str,
        "label": f"Key #{idx + 1} ({key_str[:8]}...{key_str[-4:]})"
    })

print(f"🚀 AI Pool ready: {len(verified_pool)} Gemini key(s) active on [gemini-3.5-flash-lite]!\n")

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
ROBOT_SYSTEM_INSTRUCTION = """You are MEMO, a witty and cheerful desktop robot companion. You are having a live voice chat.
RULES:
- Reply in 1 SHORT sentence only (max 10 words). Keep it punchy and conversational!
- Speak naturally and warmly in plain words only.
- NEVER say "right now" repeatedly. Avoid repetitive filler phrases like "chatting with you" or "as hard as I can".
- NEVER use asterisks (*), underscores (_), markdown formatting, emojis, or sound actions like *beep boop*. Output plain spoken English words only.
- You understand Sinhala, Singlish, and English. Always reply in English.
- Skip filler like "Sure!", "Of course!", "Great question!".
- NEVER say "How can I help you?" or "Is there anything else?" — just answer directly.
- NEVER claim you only understand English or refuse non-English input."""

# --- NETWORK CONFIGURATION ---
TCP_PORT = 8005
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 200  # Lower = more sensitive mic detection
MAX_SILENCE_SECONDS = 0.65  # Seconds of silence before sending to Gemini (0.65s gives natural pause)
STREAMING_TTS = False  # Set False for crystal-clear Option A (PSRAM audio buffering, sub-2s latency, zero breaking radio noise)

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
    # Try local Whisper first (fast, free, no network)
    if whisper_model:
        try:
            t0 = time.time()
            # Convert 16-bit PCM bytes to float32 numpy array for Whisper
            pcm_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_float32 = pcm_int16.astype(np.float32) / 32768.0
            
            # Peak-normalize to 0.95 so Whisper always receives optimal volume even when quiet
            peak_val = np.max(np.abs(audio_float32))
            if peak_val > 0.001:
                audio_float32 = (audio_float32 / peak_val) * 0.95
            
            lang_code = "si" if "si" in current_language else "en"
            segments, info = whisper_model.transcribe(
                audio_float32,
                beam_size=1,
                language=lang_code,
                condition_on_previous_text=False,
                temperature=0.0,
                vad_filter=False,
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
    """Ultra-fast speculative dual-key race: runs 2 healthy keys in parallel.
    The fastest response wins (~1.1s latency), and the other call is cancelled."""
    # Build conversation context for continuity
    context = ""
    if conversation_history:
        context = "Recent conversation:\n" + "\n".join(
            [f"{role}: {msg}" for role, msg in conversation_history]
        ) + "\n\n"
    
    prompt = f"{context}User said: \"{user_transcript}\"\nReply in 1 short sentence (max 12 words)."
    
    # Pick 2 healthy keys from the pool
    entry1, idx1 = get_next_healthy_entry()
    entry2, idx2 = get_next_healthy_entry(idx1 + 1)
    if idx1 == idx2 and len(verified_pool) > 1:
        entry2, idx2 = verified_pool[(idx1 + 1) % len(verified_pool)], (idx1 + 1) % len(verified_pool)
        
    candidates = [(entry1, idx1)]
    if idx2 != idx1:
        candidates.append((entry2, idx2))
        
    def call_gemini(entry_item, pool_index):
        client = entry_item["client"]
        model_name = entry_item["model"]
        t0 = time.time()
        response = client.models.generate_content(
            model=model_name,
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=ROBOT_SYSTEM_INSTRUCTION,
                max_output_tokens=50,
                safety_settings=[
                    types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_NONE),
                ]
            )
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        text = response.text.strip() if response.text else "I hear you."
        return entry_item, pool_index, text, elapsed_ms

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            future_to_entry = {
                executor.submit(call_gemini, entry, idx): (entry, idx)
                for entry, idx in candidates
            }
            # Wait up to 5.0s for the first completed successful call
            done, pending = concurrent.futures.wait(
                future_to_entry.keys(),
                timeout=5.0,
                return_when=concurrent.futures.FIRST_COMPLETED
            )
            
            # Cancel pending tasks immediately
            executor.shutdown(wait=False, cancel_futures=True)
            
            for f in done:
                try:
                    entry_item, pool_index, ai_text, elapsed_ms = f.result()
                    print(f"[LLM Race Winner] ({elapsed_ms}ms, {entry_item['label']} ({entry_item['model']})) → \"{ai_text}\"")
                    conversation_history.append(("User", user_transcript))
                    conversation_history.append(("MEMO", ai_text))
                    return ai_text
                except Exception as e:
                    err_str = str(e)
                    failed_entry, failed_idx = future_to_entry[f]
                    print(f"[LLM Error] {failed_entry['label']}: {e}")
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        key_cooldowns[failed_idx] = time.time() + 60

            # If first finished future had an error, check any remaining completed
            for f in pending:
                if f.done():
                    try:
                        entry_item, pool_index, ai_text, elapsed_ms = f.result()
                        print(f"[LLM Race Winner (2nd)] ({elapsed_ms}ms, {entry_item['label']}) → \"{ai_text}\"")
                        conversation_history.append(("User", user_transcript))
                        conversation_history.append(("MEMO", ai_text))
                        return ai_text
                    except Exception:
                        pass

    except Exception as e:
        print(f"[LLM Race Exception]: {e}")

    # Sequential single fallback if both race candidates failed
    fallback_entry, fallback_idx = get_next_healthy_entry()
    try:
        t0 = time.time()
        res = fallback_entry["client"].models.generate_content(
            model=fallback_entry["model"],
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=ROBOT_SYSTEM_INSTRUCTION,
                max_output_tokens=50
            )
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        ai_text = res.text.strip() if res.text else "I am here."
        print(f"[LLM Fallback OK] ({elapsed_ms}ms, {fallback_entry['label']}) → \"{ai_text}\"")
        conversation_history.append(("User", user_transcript))
        conversation_history.append(("MEMO", ai_text))
        return ai_text
    except Exception as e:
        print(f"[LLM Fallback Error]: {e}")

    print("[LLM] ⚠️ Quick fallback used to keep robot responsive with zero freeze.")
    return "I am right here with you!"

async def broadcast(msg):
    # Also include the robot_socket if we want to log to robot Serial
    for client in list(connected_clients):
        try: await client.send_text(msg)
        except: connected_clients.discard(client)

def text_to_pcm(text):
    """Convert text to raw 16kHz 16-bit mono PCM using edge-tts (cloud fallback)."""
    async def run():
        communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
        mp3_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])
        mp3_buf.seek(0)
        audio = AudioSegment.from_mp3(mp3_buf)
        audio = audio + 10
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        return audio.raw_data
    return asyncio.run(run())

def text_to_pcm_fast(text, is_first=False, is_last=False):
    """Local piper-tts TTS (~150-250ms). Natural Amy voice with mono 16kHz anti-pop windowing."""
    if piper_voice:
        try:
            t0 = time.time()
            raw_bytes = bytearray()
            for chunk in piper_voice.synthesize(text):
                raw_bytes.extend(chunk.audio_int16_bytes)
            if not raw_bytes:
                return b""
            audio = AudioSegment(
                data=bytes(raw_bytes),
                sample_width=2,
                frame_rate=piper_voice.config.sample_rate,
                channels=1
            )
            # Boost volume by +10dB and convert to 16kHz mono (50% smaller Wi-Fi payload)
            audio = (audio + 10).set_frame_rate(16000).set_channels(1).set_sample_width(2)
            
            # Anti-pop windowing: smooth fade-in and fade-out to eliminate step discontinuities
            fade_in_ms = 25 if is_first else 12
            fade_out_ms = 30 if is_last else 15
            audio = audio.fade_in(fade_in_ms).fade_out(fade_out_ms)
            
            # Preamble silence for cold amp unmute
            if is_first:
                silence_pre = AudioSegment.silent(duration=25, frame_rate=16000).set_channels(1).set_sample_width(2)
                audio = silence_pre + audio
            if is_last:
                silence_post = AudioSegment.silent(duration=35, frame_rate=16000).set_channels(1).set_sample_width(2)
                audio = audio + silence_post
                
            elapsed = int((time.time() - t0) * 1000)
            print(f"[TTS-Piper] ({elapsed}ms) {len(audio.raw_data)} bytes (mono)")
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
            # Dynamic safe timeout: at least 20 seconds, or 1 second per 6KB
            robot_socket.settimeout(max(20.0, length / 6000.0))
            robot_socket.sendall(header + pcm_data)
            robot_socket.settimeout(None)
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
            speech_start_time = 0
            phrase_buffer = bytearray()
            # 500ms Pre-Roll Ring Buffer (16 chunks * ~32ms = ~512ms ensures zero clipped first words)
            pre_roll_buffer = collections.deque(maxlen=16)
            # Adaptive Noise Floor (Calibrated on connect)
            noise_floor_rms = 400.0
            
            # Software AGC (Automatic Gain Control) state
            agc_gain = 1.0
            TARGET_SPEECH_RMS = 3000.0
            
            loud_chunk_count = 0
            calibration_chunks = 15  # Discard initial socket pops and calibrate true ambient floor
            last_heartbeat = 0
            
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
                
                # Warm-up calibration on connect
                if calibration_chunks > 0:
                    calibration_chunks -= 1
                    noise_floor_rms = 0.8 * noise_floor_rms + 0.2 * rms
                    pre_roll_buffer.append(chunk)
                    continue
                
                # Heartbeat to give real-time visibility into incoming mic stream
                if not is_speaking and (time.time() - last_heartbeat > 2.5):
                    last_heartbeat = time.time()
                    print(f"[Mic Audio] 🟢 Ingesting audio: RMS={rms:.0f} | NoiseFloor={noise_floor_rms:.0f} | StartTrigger={max(100.0, noise_floor_rms * 2.0):.0f}")
                
                # Calculate dynamic AGC gain during speech
                if rms > 0 and is_speaking:
                    ideal_gain = TARGET_SPEECH_RMS / rms
                    ideal_gain = max(1.0, min(ideal_gain, 4.0))
                    agc_gain = 0.9 * agc_gain + 0.1 * ideal_gain
                elif not is_speaking:
                    agc_gain = 0.95 * agc_gain + 0.05 * 1.0  # Reset gain smoothly when silent

                scaled_chunk = apply_agc(chunk, agc_gain)
                
                # Update adaptive noise floor when silent, ONLY during quiet periods
                if not is_speaking and rms < noise_floor_rms * 1.5:
                    noise_floor_rms = 0.95 * noise_floor_rms + 0.05 * rms
                    noise_floor_rms = max(20.0, min(noise_floor_rms, 600.0))
                
                # Dual VAD Thresholds (Dynamic based on true ambient room noise):
                start_threshold = max(100.0, noise_floor_rms * 2.2)
                silence_threshold = max(50.0, noise_floor_rms * 1.4)
                
                if not is_speaking:
                    pre_roll_buffer.append(scaled_chunk)
                    if rms > start_threshold:
                        loud_chunk_count += 1
                        # Require 2 consecutive loud chunks (~64ms) to debounce clicks
                        if loud_chunk_count >= 2:
                            is_speaking = True
                            speech_start_time = time.time()
                            silence_start = 0
                            # Include full 500ms pre-roll lead-in so initial consonants ("Can", "Look") are never cut off
                            phrase_buffer.extend(b"".join(pre_roll_buffer))
                            pre_roll_buffer.clear()
                            print(f"[VAD] 🎙️ Speech detected! (RMS: {rms:.0f}, Threshold: {start_threshold:.0f})")
                            # Instant display feedback on ESP32 screen
                            with socket_lock:
                                if robot_socket:
                                    try: robot_socket.sendall(b"TEXT:Listening...\n")
                                    except: pass
                            asyncio.run_coroutine_threadsafe(broadcast("LISTENING_START"), active_loop)
                    else:
                        loud_chunk_count = 0
                else:
                    # DURING SPEECH: Record every syllable smoothly!
                    phrase_buffer.extend(scaled_chunk)
                    now = time.time()
                    
                    if rms > silence_threshold:
                        silence_start = 0
                    else:
                        if silence_start == 0:
                            silence_start = now
                        
                        # Stop conditions: silence pause OR max phrase safety cutoff (6.0s)
                        silence_met = (silence_start > 0 and (now - silence_start > MAX_SILENCE_SECONDS))
                        max_phrase_met = (now - speech_start_time) > 6.0
                        
                        if silence_met or max_phrase_met:
                            global turn_start_time
                            turn_start_time = now
                            is_speaking = False
                            silence_start = 0
                            loud_chunk_count = 0
                            pre_roll_buffer.clear()
                            print(f"[VAD] 🛑 Speech finished ({len(phrase_buffer)} bytes). Processing...")
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
                                global is_processing_ai, turn_start_time, mic_ignore_until
                                is_processing_ai = True
                                if turn_start_time is None:
                                    turn_start_time = time.time()
                                t_start = turn_start_time
                                
                                try:
                                    # Discard noise blips under 0.35s (less than 11,000 bytes)
                                    if len(buf) < 11000:
                                        return
                                    
                                    # Save last capture for inspection/playback
                                    try:
                                        with wave.open("last_capture.wav", "wb") as wf:
                                            wf.setnchannels(1)
                                            wf.setsampwidth(2)
                                            wf.setframerate(SAMPLE_RATE)
                                            wf.writeframes(buf)
                                    except Exception:
                                        pass
                                    
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

                                    if STREAMING_TTS:
                                        # ==========================================================
                                        # OPTION B: STREAMING LLM → CHUNKED TTS PIPELINING (DECOUPLED)
                                        # ==========================================================
                                        punct_re = re.compile(r'([.!?,;:\n])(\s+|$)')
                                        full_ai_text = ""
                                        first_chunk_sent = False
                                        total_pcm_bytes = 0
                                        playback_start_time = None
                                        
                                        # Dedicated background audio queue & sender thread
                                        # (Decouples LLM token generation from socket I/O)
                                        audio_queue = queue.Queue()
                                        
                                        def audio_sender_worker():
                                            while True:
                                                item = audio_queue.get()
                                                if item is None:
                                                    break
                                                msg_type, payload = item
                                                if msg_type == "TEXT":
                                                    with socket_lock:
                                                        if robot_socket:
                                                            try: robot_socket.sendall(("TEXT:" + payload + "\n").encode('utf-8'))
                                                            except: pass
                                                elif msg_type == "CHUNK":
                                                    header = b'CHUNK' + struct.pack('>I', len(payload))
                                                    with socket_lock:
                                                        if robot_socket:
                                                            try: robot_socket.sendall(header + payload)
                                                            except: pass
                                                elif msg_type == "END":
                                                    with socket_lock:
                                                        if robot_socket:
                                                            try:
                                                                if payload:
                                                                    robot_socket.sendall(("TEXT:" + payload + "\n").encode('utf-8'))
                                                                robot_socket.sendall(b'CHUNK' + struct.pack('>I', 0))
                                                            except: pass
                                                audio_queue.task_done()
                                        
                                        sender_thread = threading.Thread(target=audio_sender_worker, daemon=True)
                                        sender_thread.start()
                                        
                                        # Context & prompt
                                        context = ""
                                        if conversation_history:
                                            context = "Recent conversation:\n" + "\n".join(
                                                [f"{role}: {msg}" for role, msg in conversation_history]
                                            ) + "\n\n"
                                        prompt = f"{context}User said: \"{user_transcript}\"\nReply in 1 short sentence (max 15 words)."
                                        
                                        entry, pool_idx = get_next_healthy_entry()
                                        
                                        def emit_clause(clause_raw, is_last=False):
                                            nonlocal first_chunk_sent, total_pcm_bytes, playback_start_time
                                            clean = re.sub(r'[*_#~`]', '', clause_raw)
                                            clean = clean.encode('ascii', 'ignore').decode('ascii')
                                            clean = re.sub(r'\s+', ' ', clean).strip()
                                            if not re.search(r'[a-zA-Z0-9]', clean):
                                                return
                                            
                                            # Send first clause text to OLED for instant expression
                                            if not first_chunk_sent:
                                                audio_queue.put(("TEXT", clean))
                                            
                                            t_syn = time.time()
                                            is_first_chunk = (not first_chunk_sent)
                                            pcm = text_to_pcm_fast(clean, is_first=is_first_chunk, is_last=is_last)
                                            syn_dur_ms = int((time.time() - t_syn) * 1000)
                                            
                                            if pcm:
                                                total_pcm_bytes += len(pcm)
                                                if not first_chunk_sent:
                                                    first_chunk_sent = True
                                                    playback_start_time = time.time()
                                                    lat_ms = int((playback_start_time - t_start) * 1000)
                                                    print(f"[STREAM-TTS] ⚡ First audio playing at {lat_ms}ms! (clause: \"{clean}\", syn: {syn_dur_ms}ms)")
                                                else:
                                                    print(f"[STREAM-TTS] Chunk queued ({syn_dur_ms}ms, {len(pcm)} bytes): \"{clean}\"")
                                                
                                                audio_queue.put(("CHUNK", pcm))

                                        for _ in range(len(verified_pool)):
                                            client = entry["client"]
                                            model_name = entry["model"]
                                            label = entry["label"]
                                            try:
                                                stream = client.models.generate_content_stream(
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
                                                
                                                stream_iter = iter(stream)
                                                
                                                # Guard: if first token does not arrive within 3.5s, failover to next key
                                                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                                                    first_future = ex.submit(lambda: next(stream_iter, None))
                                                    first_chunk = first_future.result(timeout=3.5)
                                                
                                                if first_chunk is None:
                                                    entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
                                                    continue
                                                
                                                buffer = ""
                                                
                                                def process_token(token_text):
                                                    nonlocal buffer, full_ai_text
                                                    if not token_text:
                                                        return
                                                    full_ai_text += token_text
                                                    buffer += token_text
                                                    
                                                    while True:
                                                        match = punct_re.search(buffer)
                                                        if match:
                                                            end_idx = match.end()
                                                            clause = buffer[:end_idx].strip()
                                                            buffer = buffer[end_idx:]
                                                            emit_clause(clause)
                                                            continue
                                                        
                                                        words = buffer.strip().split()
                                                        if len(words) >= 6:
                                                            count = 0
                                                            split_point = -1
                                                            for i, char in enumerate(buffer):
                                                                if char.isspace():
                                                                    count += 1
                                                                    if count == 5:
                                                                        split_point = i
                                                                        break
                                                            if split_point != -1:
                                                                clause = buffer[:split_point].strip()
                                                                buffer = buffer[split_point:].lstrip()
                                                                emit_clause(clause)
                                                                continue
                                                        break
                                                
                                                # Process the first chunk
                                                process_token(first_chunk.text or "")
                                                
                                                # Process all subsequent chunks
                                                for chunk in stream_iter:
                                                    process_token(chunk.text or "")
                                                
                                                if buffer.strip():
                                                    emit_clause(buffer.strip(), is_last=True)
                                                
                                                if full_ai_text:
                                                    break
                                            except concurrent.futures.TimeoutError:
                                                print(f"[STREAM-LLM Timeout] ⏱️ {label} took >3.5s! Putting on 60s cooldown...")
                                                key_cooldowns[pool_idx] = time.time() + 60
                                                entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
                                            except Exception as e:
                                                err_str = str(e)
                                                print(f"[STREAM-LLM Error] {label}: {e}")
                                                if first_chunk_sent:
                                                    break
                                                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                                                    key_cooldowns[pool_idx] = time.time() + 60
                                                entry, pool_idx = get_next_healthy_entry(pool_idx + 1)
                                                time.sleep(0.05)
                                        
                                        if not first_chunk_sent:
                                            fallback = "I had a connection delay, could you say that again?"
                                            full_ai_text = fallback
                                            emit_clause(fallback, is_last=True)
                                        
                                        clean_full = re.sub(r'[*_#~`]', '', full_ai_text)
                                        clean_full = clean_full.encode('ascii', 'ignore').decode('ascii')
                                        clean_full = re.sub(r'\s+', ' ', clean_full).strip()
                                        
                                        total_ms = int((time.time() - t_start) * 1000)
                                        print(f"MEMO: {clean_full}  [{total_ms}ms total generation]")
                                        
                                        # Push 40ms silence tail before END to cleanly settle amp
                                        silence_tail = AudioSegment.silent(duration=40, frame_rate=16000).set_channels(2).set_sample_width(2).raw_data
                                        audio_queue.put(("CHUNK", silence_tail))
                                        
                                        # Signal end to sender worker and wait for socket delivery
                                        audio_queue.put(("END", clean_full))
                                        audio_queue.put(None)
                                        sender_thread.join()
                                        
                                        conversation_history.append(("User", user_transcript))
                                        conversation_history.append(("MEMO", clean_full))
                                        asyncio.run_coroutine_threadsafe(broadcast(f"AI:{clean_full}"), active_loop)
                                        
                                        if total_pcm_bytes > 0 and playback_start_time:
                                            total_audio_duration = total_pcm_bytes / 64000.0
                                            elapsed = time.time() - playback_start_time
                                            remaining = max(0.0, total_audio_duration - elapsed)
                                            time.sleep(remaining + 0.6)
                                    else:
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
                                            try: s.sendall(("TEXT:" + clean_text + "\n").encode('utf-8'))
                                            except: pass
                                        asyncio.run_coroutine_threadsafe(broadcast(f"AI:{clean_text}"), active_loop)

                                        # STEP 3: FAST Local TTS (Piper TTS ~150-300ms on CPU, no cloud)
                                        asyncio.run_coroutine_threadsafe(broadcast("STATUS:🔊 Speaking..."), active_loop)
                                        pcm = text_to_pcm_fast(clean_text, is_first=True, is_last=True)

                                        # Prevent acoustic feedback: lock mic out BEFORE audio transmission begins
                                        if pcm:
                                            audio_duration = len(pcm) / 32000.0
                                            mic_ignore_until = time.time() + audio_duration + 0.6
                                            speak_on_socket(pcm)
                                            # Keep AI processing state active while speaker plays on robot
                                            time.sleep(audio_duration + 0.5)
                                except Exception as e:
                                    print("Gemini voice pipeline failed:", e)
                                    asyncio.run_coroutine_threadsafe(broadcast("STATUS:❌ AI Error"), active_loop)
                                finally:
                                    # Set acoustic cooldown: discard residual large speaker echo from socket
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
