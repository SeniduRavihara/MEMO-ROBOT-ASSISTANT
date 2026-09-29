#!/usr/bin/env python3
"""
MEMO Robot — Microphone & Hearing Diagnostics Tool (listen_test.py)
==================================================================
Purpose:
  - Real-time diagnostic tool to test if the robot clearly hears speech at various distances.
  - Zero Gemini API calls, zero quota used, 100% local and free.
  - Saves voices sequentially as 1.wav, 2.wav, 3.wav, 4.wav... in 'voice_samples/'
  - Saves matching text for each sample as 1.txt, 2.txt...
  - Maintains a side-by-side comparison table (comparison.txt & comparison.csv)
  - Displays what was transcribed directly on your terminal AND on the Robot's OLED screen!
  - Real-time live audio volume meter (VU meter) in the terminal.

Usage:
  python3 listen_test.py                        # Listen & record 1.wav, 2.wav, 3.wav...
  python3 listen_test.py 192.168.43.186         # Custom Robot IP
  python3 listen_test.py --clear                # Start numbering from 1 (clears old samples)
  python3 listen_test.py --review               # Review & listen to previously saved samples
  python3 listen_test.py --lang si              # For Sinhala testing
"""

import sys
import os
import time
import math
import wave
import socket
import collections
import struct
import subprocess
import numpy as np
from dotenv import load_dotenv

load_dotenv()
from google import genai
from google.genai import types

# --- CONFIGURATION ---
DEFAULT_IP = os.getenv("ROBOT_IP", "192.168.43.186")
TCP_PORT = 8005
SAMPLE_RATE = 16000
MAX_SILENCE_SECONDS = 0.95  # Natural pause between words (0.95s allows breathing without cutting off speech)
TARGET_SPEECH_RMS = 3000.0  # Software AGC target
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_samples")

os.makedirs(SAMPLES_DIR, exist_ok=True)

# Parse CLI arguments
robot_ip = DEFAULT_IP
lang_choice = "en"  # Locked to English by default for instant 400ms STT with zero hallucinations
compare_cloud = False
clear_samples = False
review_mode = False

args = sys.argv[1:]
i = 0
while i < len(args):
    arg = args[i]
    if arg == "--lang" and i + 1 < len(args):
        lang_choice = args[i + 1]
        i += 2
    elif arg == "--auto-lang":
        lang_choice = None
        i += 1
    elif arg == "--cloud":
        compare_cloud = True
        i += 1
    elif arg == "--clear":
        clear_samples = True
        i += 1
    elif arg == "--review":
        review_mode = True
        i += 1
    elif not arg.startswith("--"):
        robot_ip = arg
        i += 1
    else:
        i += 1

def play_audio(wav_path):
    """Play WAV using system native audio server (PipeWire/PulseAudio) to ensure correct playback rate."""
    for cmd in [["paplay", wav_path], ["pw-play", wav_path], ["aplay", "-q", wav_path]]:
        try:
            subprocess.run(cmd, check=True)
            return
        except Exception:
            pass

def review_saved_samples():
    """Interactive review mode: list all saved samples and play them back."""
    print("\n" + "=" * 70)
    print("🎧  MEMO VOICE SAMPLES — COMPARISON & PLAYBACK REVIEW")
    print("=" * 70)
    
    comp_file = os.path.join(SAMPLES_DIR, "comparison.txt")
    if os.path.exists(comp_file):
        with open(comp_file, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print("No comparison log found yet. Run listen_test.py to record voices first.")
        return

    print("=" * 70)
    print("Type a sample number (e.g. 1, 2, 3) to play the audio.")
    print("Type 'q' or press Ctrl+C to exit.\n")
    
    while True:
        try:
            choice = input("Enter sample # to play [or q to quit]: ").strip().lower()
            if choice in ['q', 'exit']:
                break
            if not choice.isdigit():
                continue
            wav_path = os.path.join(SAMPLES_DIR, f"{choice}.wav")
            txt_path = os.path.join(SAMPLES_DIR, f"{choice}.txt")
            if not os.path.exists(wav_path):
                print(f"⚠️ Sample #{choice} not found ({wav_path})")
                continue
            
            transcript = ""
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    transcript = f.read().strip()
            
            print(f"\n▶️ Playing Sample #{choice}: \"{transcript}\"")
            play_audio(wav_path)
            print("✓ Playback finished.\n")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting review.")
            break

if review_mode:
    review_saved_samples()
    sys.exit(0)

# Handle --clear flag
if clear_samples:
    for fname in os.listdir(SAMPLES_DIR):
        fpath = os.path.join(SAMPLES_DIR, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
    print(f"🧹 Cleared all previous samples in {SAMPLES_DIR}/\n")

def get_next_sample_index():
    """Find the next incremental sample number (1, 2, 3...)."""
    existing_nums = []
    for fname in os.listdir(SAMPLES_DIR):
        if fname.endswith(".wav"):
            base = os.path.splitext(fname)[0]
            if base.isdigit():
                existing_nums.append(int(base))
    return max(existing_nums, default=0) + 1

# --- LOAD LOCAL WHISPER STT ---
print("\n" + "=" * 70)
print("🎙️  MEMO ROBOT — VOICE SAMPLES RECORDER & COMPARISON TOOL")
print("=" * 70)
print(f"📡 Target Robot IP : {robot_ip}:{TCP_PORT}")
print(f"📁 Output Directory: {SAMPLES_DIR}/")
print(f"🌐 STT Language    : {lang_choice if lang_choice else 'Auto-Detect (English / Sinhala)'}")
print("=" * 70)

print("\n⏳ Loading local Whisper STT model (tiny, int8)...")
t0 = time.time()
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
from faster_whisper import WhisperModel
try:
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8", local_files_only=True)
except Exception:
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
print(f"✅ Whisper loaded in {int((time.time() - t0) * 1000)}ms!\n")

# --- GEMINI DIRECT MULTIMODAL AUDIO CLIENT ---
raw_keys = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
gemini_clients = [genai.Client(api_key=k) for k in API_KEYS] if API_KEYS else []
gemini_key_idx = 0
if gemini_clients:
    print(f"🧠 Gemini Multimodal Audio Pool: {len(gemini_clients)} API key(s) active!\n")
else:
    print("⚠️ No GEMINI_API_KEY found in .env (will use local Whisper only)\n")

def query_gemini_voice(wav_bytes):
    """Send raw audio directly to Gemini 2.5 Flash for native multimodal transcription and response."""
    global gemini_key_idx
    if not gemini_clients:
        return "", "", 0

    prompt = (
        "You are MEMO, a small friendly AI companion robot.\n"
        "Listen to the user speaking in this audio.\n"
        "Output EXACTLY in this format:\n"
        "HEARD: <exact words the user spoke in original language (English or Sinhala)>\n"
        "REPLY: <short friendly reply under 12 words as MEMO>"
    )

    models_to_try = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]

    for attempt in range(len(gemini_clients)):
        idx = (gemini_key_idx + attempt) % len(gemini_clients)
        client = gemini_clients[idx]
        for m in models_to_try:
            try:
                t0 = time.time()
                res = client.models.generate_content(
                    model=m,
                    contents=[types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"), prompt]
                )
                elapsed_ms = int((time.time() - t0) * 1000)
                gemini_key_idx = idx

                heard = ""
                reply = ""
                for line in res.text.strip().splitlines():
                    if line.startswith("HEARD:"):
                        heard = line[6:].strip()
                    elif line.startswith("REPLY:"):
                        reply = line[6:].strip()
                if not heard:
                    heard = res.text.strip()
                return heard, reply, elapsed_ms
            except Exception as e:
                err_str = str(e)
                if "404" in err_str and ("not found" in err_str.lower() or "available" in err_str.lower()):
                    continue  # Try next model on this key
                if any(err_code in err_str for err_code in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "INTERNAL"]):
                    break     # Quota or server busy on this key, try next key in pool
                return f"API Error: {e}", "", 0

    return "All Gemini keys exhausted", "", 0

def calculate_rms(pcm_bytes):
    """Calculate Root Mean Square (volume level) of 16-bit PCM audio."""
    if not pcm_bytes:
        return 0
    count = len(pcm_bytes) // 2
    if count == 0:
        return 0
    shorts = struct.unpack(f"<{count}h", pcm_bytes)
    sum_squares = sum(s * s for s in shorts)
    return math.sqrt(sum_squares / count)

def apply_agc(pcm_bytes, gain):
    """Software Automatic Gain Control to normalize distant/quiet speech."""
    if gain <= 1.05 and gain >= 0.95:
        return pcm_bytes
    count = len(pcm_bytes) // 2
    if count == 0:
        return pcm_bytes
    shorts = struct.unpack(f"<{count}h", pcm_bytes)
    boosted = [max(-32768, min(32767, int(s * gain))) for s in shorts]
    return struct.pack(f"<{count}h", *boosted)

def trim_silence_pcm(audio_bytes, threshold=45, frame_ms=20):
    """Remove leading and trailing silence frames from PCM audio."""
    frame_size = int(SAMPLE_RATE * (frame_ms / 1000.0) * 2)
    if len(audio_bytes) < frame_size:
        return audio_bytes
    total_frames = len(audio_bytes) // frame_size
    if total_frames == 0:
        return audio_bytes
    
    start_frame = 0
    for i in range(total_frames):
        frame = audio_bytes[i * frame_size : (i + 1) * frame_size]
        if calculate_rms(frame) > threshold:
            start_frame = max(0, i - 2)
            break
    else:
        return audio_bytes
    
    end_frame = total_frames - 1
    for i in range(total_frames - 1, -1, -1):
        frame = audio_bytes[i * frame_size : (i + 1) * frame_size]
        if calculate_rms(frame) > threshold:
            end_frame = min(total_frames - 1, i + 2)
            break
            
    return audio_bytes[start_frame * frame_size : (end_frame + 1) * frame_size]

def render_vu_bar(rms, threshold, is_speaking):
    """Render a dynamic live terminal volume meter bar."""
    meter_len = 20
    fill = min(meter_len, int((rms / 5000.0) * meter_len))
    bar = "█" * fill + "░" * (meter_len - fill)
    status = "🔴 [SPEAKING]" if is_speaking else "⚪ [WAITING] "
    return f"{status} |{bar}| RMS:{int(rms):4d} (Gate:{int(threshold):4d})"

def save_wav(filename, pcm_bytes):
    """Save raw 16kHz 16-bit mono PCM bytes to standard WAV file."""
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)

def append_to_comparison_logs(sample_num, duration_sec, rms_val, stt_ms, transcript, gemini_heard="", gemini_reply="", gemini_ms=0):
    """Save record to comparison.txt and comparison.csv with both Whisper and Gemini results."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    time_short = time.strftime("%H:%M:%S")
    
    # 1. Individual text file: voice_samples/1.txt
    txt_path = os.path.join(SAMPLES_DIR, f"{sample_num}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"[Local Whisper ({stt_ms}ms)] : {transcript}\n")
        if gemini_heard:
            f.write(f"[Gemini Voice ({gemini_ms}ms)] : {gemini_heard}\n")
        if gemini_reply:
            f.write(f"[MEMO Robot Reply]           : {gemini_reply}\n")
        
    # 2. CSV log
    csv_path = os.path.join(SAMPLES_DIR, "comparison.csv")
    csv_exists = os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8") as f:
        if not csv_exists:
            f.write("Sample_ID,Timestamp,Audio_File,Duration_Sec,RMS,Whisper_STT,Whisper_ms,Gemini_Heard,Gemini_Reply,Gemini_ms\n")
        safe_transcript = transcript.replace('"', '""')
        safe_gemini = gemini_heard.replace('"', '""')
        safe_reply = gemini_reply.replace('"', '""')
        f.write(f'{sample_num},"{timestamp}","{sample_num}.wav",{duration_sec:.2f},{int(rms_val)},"{safe_transcript}",{stt_ms},"{safe_gemini}","{safe_reply}",{gemini_ms}\n')
        
    # 3. Formatted Table log
    table_path = os.path.join(SAMPLES_DIR, "comparison.txt")
    table_exists = os.path.exists(table_path)
    with open(table_path, "a", encoding="utf-8") as f:
        if not table_exists:
            f.write("=" * 105 + "\n")
            f.write(f"{'#':<4} | {'Audio File':<8} | {'Time':<8} | {'Length':<6} | {'Whisper Heard':<32} | Gemini Direct Voice\n")
            f.write("=" * 105 + "\n")
        g_display = gemini_heard if gemini_heard else transcript
        f.write(f"{sample_num:<4} | {sample_num}.wav{'' if sample_num > 9 else ' ':<3} | {time_short:<8} | {duration_sec:>4.1f}s | {transcript[:30]:<32} | {g_display}\n")

def main():
    session_records = []
    
    while True:
        try:
            print(f"Connecting to Robot at {robot_ip}:{TCP_PORT}...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(8)
            sock.connect((robot_ip, TCP_PORT))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(None)
            
            # Reset OLED screen on robot
            try:
                sock.sendall(b"TEXT:Voice Recorder\nSpeak 1 2 3...\n")
            except Exception:
                pass
            
            print("✅ Connected to Robot! Ready for recording.")
            print("🗣️  Speak phrase #1, pause, speak phrase #2, etc.")
            print("🛑 Press Ctrl+C at any time to finish and see full comparison table!\n")
            
            is_speaking = False
            silence_start = 0
            phrase_buffer = bytearray()
            pre_roll_buffer = collections.deque(maxlen=10)  # ~300ms pre-roll
            noise_floor_rms = 28.0
            consecutive_loud_chunks = 0
            agc_gain = 1.0
            
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    print("\n⚠️ Robot disconnected.")
                    break
                
                rms = calculate_rms(chunk)
                
                # Dynamic AGC calculation during speech
                if rms > 0 and is_speaking:
                    ideal_gain = TARGET_SPEECH_RMS / rms
                    ideal_gain = max(1.0, min(ideal_gain, 4.0))
                    agc_gain = 0.9 * agc_gain + 0.1 * ideal_gain
                elif not is_speaking:
                    agc_gain = 0.95 * agc_gain + 0.05 * 1.0
                
                scaled_chunk = apply_agc(chunk, agc_gain)
                
                # Adaptive background noise tracking when silent
                if not is_speaking:
                    noise_floor_rms = 0.95 * noise_floor_rms + 0.05 * rms
                
                # Dynamic VAD Threshold: 1.40x background noise, minimum floor 45.0 (so quiet voices aren't cut off)
                dynamic_threshold = max(45.0, noise_floor_rms * 1.40)
                
                # Render real-time VU meter in terminal
                meter_str = render_vu_bar(rms, dynamic_threshold, is_speaking)
                sys.stdout.write(f"\r{meter_str} Floor:{int(noise_floor_rms):3d}  ")
                sys.stdout.flush()
                
                if rms > dynamic_threshold:
                    consecutive_loud_chunks += 1
                    if not is_speaking:
                        # 2 consecutive chunks (~64ms) required to confirm human voice vs click
                        if consecutive_loud_chunks >= 2:
                            is_speaking = True
                            phrase_buffer.extend(b"".join(pre_roll_buffer))
                            pre_roll_buffer.clear()
                            phrase_buffer.extend(scaled_chunk)
                            try:
                                sock.sendall(b"TEXT:Recording...\n")
                            except Exception:
                                pass
                        else:
                            pre_roll_buffer.append(scaled_chunk)
                    else:
                        phrase_buffer.extend(scaled_chunk)
                        silence_start = 0
                else:
                    consecutive_loud_chunks = 0
                    if not is_speaking:
                        pre_roll_buffer.append(scaled_chunk)
                    else:
                        phrase_buffer.extend(scaled_chunk)
                        if silence_start == 0:
                            silence_start = time.time()
                        elif time.time() - silence_start > MAX_SILENCE_SECONDS:
                            # Finished speaking!
                            is_speaking = False
                            silence_start = 0
                            pre_roll_buffer.clear()
                            
                            sys.stdout.write("\r" + " " * 75 + "\r")
                            sys.stdout.flush()
                            
                            try:
                                sock.sendall(b"TEXT:Transcribing...\n")
                            except Exception:
                                pass
                            
                            audio_to_transcribe = bytearray(phrase_buffer)
                            phrase_buffer.clear()
                            
                            # Trim leading/trailing silence
                            audio_trimmed = trim_silence_pcm(audio_to_transcribe)
                            
                            pcm_int16 = np.frombuffer(audio_trimmed, dtype=np.int16)
                            if len(pcm_int16) < 320:  # Skip trivial spikes < 20ms
                                continue
                                
                            duration_sec = len(pcm_int16) / float(SAMPLE_RATE)
                            audio_float32 = pcm_int16.astype(np.float32) / 32768.0
                            
                            # Transcribe with Whisper (normal natural audio)
                            t_stt_start = time.time()
                            segments, info = whisper_model.transcribe(
                                audio_float32,
                                beam_size=1,
                                language=lang_choice,
                                vad_filter=True,
                                vad_parameters=dict(min_silence_duration_ms=200)
                            )
                            transcript = " ".join([seg.text.strip() for seg in segments]).strip()
                            stt_ms = int((time.time() - t_stt_start) * 1000)
                            
                            if transcript:
                                sample_num = get_next_sample_index()
                                wav_filename = f"{sample_num}.wav"
                                wav_path = os.path.join(SAMPLES_DIR, wav_filename)
                                
                                # Save exact natural audio as 1.wav, 2.wav, 3.wav...
                                save_wav(wav_path, audio_trimmed)
                                # Also update last_capture.wav for convenience
                                save_wav(os.path.join(os.path.dirname(SAMPLES_DIR), "last_capture.wav"), audio_trimmed)
                                
                                # Query Gemini Direct Voice only if --cloud flag is specified
                                gemini_heard, gemini_reply, gemini_ms = "", "", 0
                                if compare_cloud:
                                    with open(wav_path, "rb") as f:
                                        wav_bytes = f.read()
                                    gemini_heard, gemini_reply, gemini_ms = query_gemini_voice(wav_bytes)
                                
                                speech_rms = calculate_rms(audio_trimmed)
                                # 2. Append to logs and comparison records
                                append_to_comparison_logs(sample_num, duration_sec, speech_rms, stt_ms, transcript, gemini_heard, gemini_reply, gemini_ms)
                                session_records.append((sample_num, wav_filename, duration_sec, stt_ms, transcript))
                                
                                print("\n" + "┌" + "─" * 68 + "┐")
                                print(f"│ 🎯 Voice Sample #{sample_num} Saved: voice_samples/{wav_filename}")
                                print(f"│ 🗣️ Transcribed Text : \"{transcript}\" ({stt_ms}ms) ⚡")
                                if gemini_heard:
                                    print(f"│ 🧠 Gemini Voice     : \"{gemini_heard}\" ({gemini_ms}ms)")
                                if gemini_reply:
                                    print(f"│ 💬 MEMO's Reply     : \"{gemini_reply}\"")
                                print(f"│ ⏱️ Duration: {duration_sec:.1f}s | Voice RMS: {int(speech_rms)} | Lang: {lang_choice or 'auto'}")
                                print(f"│ 🎧 To listen: paplay {os.path.relpath(wav_path)}")
                                print("└" + "─" * 68 + "┘\n")
                                
                                # Send result to Robot OLED screen immediately!
                                clean_screen_text = transcript.replace('\n', ' ')
                                if len(clean_screen_text) > 30:
                                    clean_screen_text = clean_screen_text[:27] + "..."
                                try:
                                    sock.sendall(f"TEXT:#{sample_num} Captured!\n\"{clean_screen_text}\"\n".encode('utf-8'))
                                except Exception:
                                    pass
                            else:
                                print(f"\n[Quiet sound / non-speech noise ignored]\n")
                                try:
                                    sock.sendall(b"TEXT:Voice Recorder\nSpeak 1 2 3...\n")
                                except Exception:
                                    pass
                                    
        except KeyboardInterrupt:
            print("\n\n" + "=" * 76)
            print("📋  SESSION COMPARISON SUMMARY (VOICE vs AI TRANSCRIPTION)")
            print("=" * 76)
            if session_records:
                print(f"{'#':<4} | {'Audio File':<8} | {'Length':<7} | {'STT':<6} | Transcribed Text by AI")
                print("-" * 76)
                for s_num, s_file, s_dur, s_stt, s_text in session_records:
                    print(f"{s_num:<4} | {s_file:<8} | {s_dur:>4.1f}s  | {s_stt:>4d}ms | \"{s_text}\"")
                print("=" * 76)
                print(f"📂 Audio files saved in : {SAMPLES_DIR}/")
                print(f"📄 Full comparison log  : {os.path.join(SAMPLES_DIR, 'comparison.txt')}")
                print(f"💡 To listen & review any sample anytime, run:")
                print(f"   python3 listen_test.py --review")
            else:
                print("No samples were recorded in this session.")
            print("=" * 76 + "\n")
            
            try:
                sock.sendall(b"TEXT:MEMO Ready! Speak...\n")
                sock.close()
            except Exception:
                pass
            break
        except Exception as e:
            print(f"\n⚠️ Connection error: {e}. Retrying in 3 seconds...")
            time.sleep(3)

if __name__ == "__main__":
    main()
