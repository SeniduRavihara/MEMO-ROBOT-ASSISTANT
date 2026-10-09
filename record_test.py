#!/usr/bin/env python3
"""
MEMO Robot — Microphone Comparison & Diagnostic Tool
Connects to ESP32 over TCP (port 8005), records test speech,
analyzes signal metrics, runs Whisper STT, and prints a side-by-side comparison.
"""

import sys
import os

# Auto re-exec with project venv to ensure faster-whisper & numpy are available
VENV_PYTHON = "/home/senu/PROJECTS/MEMO/WORKING_SAMPLE/voice_response_AI/python_backend/.venv/bin/python3"
if sys.executable != VENV_PYTHON and os.path.exists(VENV_PYTHON):
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

import socket
import time
import wave
import math
import struct
import json
import subprocess
import numpy as np

ROBOT_IP = "192.168.43.186"
ROBOT_PORT = 8005
SAMPLE_RATE = 16000
RECORDINGS_DIR = "/home/senu/PROJECTS/MEMO/recordings"
HISTORY_FILE = os.path.join(RECORDINGS_DIR, "history.json")

os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Parse CLI arguments or prompt
label = "test_mic"
duration = 10

if len(sys.argv) > 1:
    for arg in sys.argv[1:]:
        if arg.isdigit():
            duration = int(arg)
        elif "." in arg and len(arg.split(".")) == 4:
            ROBOT_IP = arg
        else:
            label = arg
else:
    print("\n" + "=" * 65)
    print("🎙️  MEMO ROBOT — DUAL MICROPHONE TEST & COMPARISON")
    print("=" * 65)
    user_label = input("Enter test label (e.g. 'old_mic' or 'new_mic') [default: new_mic]: ").strip()
    if user_label:
        label = user_label.replace(" ", "_")
    else:
        label = "new_mic"

    user_dur = input(f"Enter recording duration in seconds [default: 10]: ").strip()
    if user_dur.isdigit():
        duration = int(user_dur)

# Sanitize label
label = "".join(c for c in label if c.isalnum() or c in ("_", "-"))

# Free socket if live_server is running
try:
    subprocess.run(["pkill", "-f", "live_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
except Exception:
    pass

print("\n" + "=" * 65)
print(f"🎙️  TEST CONFIGURATION:")
print(f"  • Label:      {label}")
print(f"  • Duration:   {duration} seconds")
print(f"  • Target:     {ROBOT_IP}:{ROBOT_PORT}")
print("=" * 65)
print(f"Connecting to ESP32 at {ROBOT_IP}:{ROBOT_PORT}...")

sock = None
attempts = 0
while attempts < 15:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.5)
        sock.connect((ROBOT_IP, ROBOT_PORT))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(1.0)
        print("✅ Connected to ESP32 microphone stream!\n")
        break
    except Exception:
        attempts += 1
        print(f"  Connecting... ({attempts}/15) (Make sure ESP32 is powered on Wi-Fi)", end="\r")
        time.sleep(1.0)

if not sock:
    print(f"\n❌ Could not connect to ESP32 at {ROBOT_IP}:{ROBOT_PORT}")
    print("Troubleshooting:")
    print("  1. Check if ESP32 IP is correct.")
    print("  2. Verify ESP32 is connected to the same Wi-Fi / hotspot.")
    sys.exit(1)

total_target_bytes = SAMPLE_RATE * 2 * duration
audio_buffer = bytearray()
start_time = time.time()
last_display = 0
rms_history = []
peak_history = []
clip_count = 0

print("🔴 RECORDING STARTED — Stay quiet for 1s, then speak clearly into mic!\n")

try:
    while len(audio_buffer) < total_target_bytes:
        chunk = sock.recv(1024)
        if not chunk:
            print("\n⚠️ Connection closed by ESP32.")
            break

        audio_buffer.extend(chunk)

        if len(chunk) >= 2:
            count = len(chunk) // 2
            samples = struct.unpack(f"<{count}h", chunk[:count * 2])
            sum_sq = sum(s * s for s in samples)
            rms = math.sqrt(sum_sq / count) if count > 0 else 0
            cur_peak = max(abs(s) for s in samples) if samples else 0
            rms_history.append(rms)
            peak_history.append(cur_peak)
            clip_count += sum(1 for s in samples if abs(s) >= 32700)

        now = time.time()
        if now - last_display >= 0.15:
            last_display = now
            elapsed = now - start_time
            progress = min(100, int((len(audio_buffer) / total_target_bytes) * 100))
            bar_len = 20
            filled = int(bar_len * (progress / 100))
            prog_bar = "█" * filled + "░" * (bar_len - filled)

            meter_val = min(25, int(rms / 120))
            meter = "■" * meter_val + " " * (25 - meter_val)
            print(f"\r[{prog_bar}] {progress:3d}% | {elapsed:4.1f}s/{duration}s | RMS: {rms:5.0f} [{meter}]", end="", flush=True)

except KeyboardInterrupt:
    print("\n\n⏹️ Recording stopped early by user.")
finally:
    try:
        sock.close()
    except Exception:
        pass

def apply_spectral_subtraction(samples, sample_rate=16000, noise_sec=1.2):
    """Subtract ambient noise profile using the initial silence period."""
    out_len = len(samples)
    if out_len < sample_rate:
        return samples, float(np.sqrt(np.mean(samples**2))), float(np.sqrt(np.mean(samples**2)))
    
    # 1. High-Pass Filter (>80Hz) to cut sub-audible room rumble and DC drift
    fft_full = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(out_len, 1.0 / sample_rate)
    hpf_mask = np.ones_like(freqs)
    transition = (freqs >= 60) & (freqs <= 95)
    hpf_mask[freqs < 60] = 0.0
    hpf_mask[transition] = 0.5 * (1 - np.cos(np.pi * (freqs[transition] - 60) / 35))
    filtered = np.fft.irfft(fft_full * hpf_mask, n=out_len)
    
    # 2. De-clicker: replace isolated sharp transient spikes
    diff = np.abs(np.diff(filtered))
    threshold = max(350.0, np.median(diff) + 4.0 * np.std(diff))
    spikes = np.where(diff > threshold)[0]
    for idx in spikes:
        if 2 <= idx < out_len - 2:
            filtered[idx] = (filtered[idx-1] + filtered[idx+1]) / 2.0
            
    # 3. Spectral subtraction using noise footprint from first noise_sec
    win_len = 512
    hop = 256
    window = np.hanning(win_len)
    
    noise_slice = filtered[:int(sample_rate * noise_sec)]
    mags = []
    for i in range(0, len(noise_slice) - win_len, hop):
        chunk = noise_slice[i:i+win_len] * window
        mags.append(np.abs(np.fft.rfft(chunk)))
    noise_profile = np.mean(mags, axis=0) * 1.35 if mags else None
    
    out_audio = np.zeros(out_len + win_len, dtype=np.float64)
    norm_win = np.zeros(out_len + win_len, dtype=np.float64)
    
    for i in range(0, out_len - win_len, hop):
        chunk = filtered[i:i+win_len] * window
        spec = np.fft.rfft(chunk)
        mag = np.abs(spec)
        phase = np.angle(spec)
        if noise_profile is not None and len(noise_profile) == len(mag):
            clean_mag = np.maximum(mag - noise_profile, 0.04 * mag)
        else:
            clean_mag = mag
        chunk_clean = np.fft.irfft(clean_mag * np.exp(1j * phase))
        out_audio[i:i+win_len] += chunk_clean * window
        norm_win[i:i+win_len] += window**2
        
    norm_win = np.maximum(norm_win, 1e-6)
    cleaned = (out_audio[:out_len] / norm_win[:out_len])
    
    raw_noise_rms = float(np.sqrt(np.mean(samples[:int(sample_rate * noise_sec)] ** 2)))
    clean_noise_rms = float(np.sqrt(np.mean(cleaned[:int(sample_rate * noise_sec)] ** 2)))
    
    cleaned_int16 = np.clip(cleaned, -32768, 32767).astype(np.int16)
    return cleaned_int16, raw_noise_rms, clean_noise_rms

print("\n\n" + "=" * 65)
actual_duration = len(audio_buffer) / (SAMPLE_RATE * 2)
print(f"📊 Capture complete: {len(audio_buffer)} bytes ({actual_duration:.1f}s)")

# Raw samples array
samples_raw = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float64)

# 1. Apply Noise Subtraction & Filtering
print("🧹 Applying Spectral Noise Subtraction & High-Pass Filter...")
samples_clean_int16, raw_noise_rms, clean_noise_rms = apply_spectral_subtraction(samples_raw, SAMPLE_RATE, noise_sec=1.2)
cleaned_bytes = samples_clean_int16.tobytes()
noise_reduction_pct = max(0.0, ((raw_noise_rms - clean_noise_rms) / max(1.0, raw_noise_rms)) * 100)

# Save files
timestamp = time.strftime("%Y%m%d_%H%M%S")
raw_wav = os.path.join(RECORDINGS_DIR, f"{label}_raw.wav")
dated_raw_wav = os.path.join(RECORDINGS_DIR, f"{label}_{timestamp}_raw.wav")

clean_wav = os.path.join(RECORDINGS_DIR, f"{label}_cleaned.wav")
dated_clean_wav = os.path.join(RECORDINGS_DIR, f"{label}_{timestamp}_cleaned.wav")
primary_wav = os.path.join(RECORDINGS_DIR, f"{label}.wav")
latest_wav = "/home/senu/PROJECTS/MEMO/latest_test.wav"

# Save RAW files
for p in (raw_wav, dated_raw_wav):
    try:
        with wave.open(p, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_buffer)
    except Exception:
        pass

# Save CLEANED files
for p in (clean_wav, dated_clean_wav, primary_wav, latest_wav):
    try:
        with wave.open(p, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(cleaned_bytes)
    except Exception:
        pass

print(f"💾 Saved CLEANED audio to: {clean_wav}")
print(f"💾 Saved RAW audio to:     {raw_wav}")
print(f"💾 Latest symlink:         {latest_wav}")

# Signal Analysis on Cleaned Audio
samples_clean = samples_clean_int16.astype(np.float64)
peak_val = int(np.max(np.abs(samples_clean))) if len(samples_clean) > 0 else 0
speech_rms = float(np.percentile(rms_history, 85)) if len(rms_history) > 5 else 0

# SNR (Signal to Noise Ratio in dB) after cleaning
snr_db = 20.0 * math.log10(max(1.0, speech_rms) / max(1.0, clean_noise_rms)) if clean_noise_rms > 0 else 0

# Check for electrical click spikes
diffs = np.abs(np.diff(samples_clean)) if len(samples_clean) > 1 else np.array([])
click_spikes = int(np.sum(diffs > 400)) if len(diffs) > 0 else 0

print("\n" + "=" * 65)
print("🔬 AUDIO SIGNAL DIAGNOSTICS:")
print(f"  • Peak Amplitude:       {peak_val:5d} / 32,768 ({(peak_val / 32768) * 100:.1f}% of full scale)")
print(f"  • Speech RMS:           {speech_rms:5.1f}")
print(f"  • Raw Noise Floor:      {raw_noise_rms:5.1f} RMS")
print(f"  • Cleaned Noise Floor:  {clean_noise_rms:5.1f} RMS (✨ -{noise_reduction_pct:.1f}% noise removed!)")
print(f"  • Cleaned SNR (Clarity):{snr_db:5.1f} dB")
print(f"  • Click Spikes:         {click_spikes:5d}")
print(f"  • Clipped Samples:      {clip_count}")

# Health Rating
print("\n📋 HARDWARE HEALTH VERDICT:")
if peak_val == 0:
    print("  ❌ DEAD / ZERO SIGNAL: Check wiring (SCK, WS, SD, VDD, GND).")
elif peak_val < 3500:
    print("  ⚠️ WEAK SIGNAL: Microphone is unusually quiet (membrane issue or gain too low).")
elif snr_db < 10.0:
    print("  ⚠️ HIGH NOISE: Noise floor is high relative to voice.")
else:
    print("  ✅ EXCELLENT SIGNAL: High dynamic range, loud speech, and clear sensitivity!")

# Whisper Transcription on Cleaned Speech
print("\n⏳ Running Whisper Speech-to-Text on cleaned recording...")
transcript = ""
try:
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    audio_float = samples_clean.astype(np.float32) / 32768.0
    # Peak normalize
    max_p = np.max(np.abs(audio_float))
    if max_p > 0.001:
        audio_float = (audio_float / max_p) * 0.95
    segments, _ = model.transcribe(audio_float, beam_size=1, vad_filter=False)
    transcript = " ".join(s.text for s in segments).strip()
    print(f"🗣️  WHISPER HEARD: \"{transcript}\"")
except Exception as e:
    print(f"⚠️ Whisper error: {e}")

# Save to History
history = []
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    except Exception:
        history = []

entry = {
    "label": label,
    "timestamp": timestamp,
    "duration": round(actual_duration, 1),
    "peak": peak_val,
    "speech_rms": round(speech_rms, 1),
    "raw_noise": round(raw_noise_rms, 1),
    "noise_floor": round(clean_noise_rms, 1),
    "noise_reduction": f"-{noise_reduction_pct:.1f}%",
    "snr_db": round(snr_db, 1),
    "click_spikes": click_spikes,
    "transcript": transcript or "(no speech detected)"
}

# Update or append
existing_idx = next((i for i, h in enumerate(history) if h["label"] == label), None)
if existing_idx is not None:
    history[existing_idx] = entry
else:
    history.append(entry)

with open(HISTORY_FILE, "w") as f:
    json.dump(history, f, indent=2)

# Comparison Table
if len(history) > 1:
    print("\n" + "=" * 90)
    print("📊 MICROPHONE COMPARISON TABLE (All Recorded Tests)")
    print("=" * 90)
    print(f"{'Label':<15} | {'Peak':<8} | {'Speech RMS':<11} | {'Noise Floor':<12} | {'SNR (dB)':<9} | {'Whisper Transcript'}")
    print("-" * 15 + "-+-" + "-" * 8 + "-+-" + "-" * 11 + "-+-" + "-" * 12 + "-+-" + "-" * 9 + "-+-" + "-" * 26)
    for h in history:
        tr = (h.get('transcript', '')[:25] + "..") if len(h.get('transcript', '')) > 25 else h.get('transcript', '')
        print(f"{h['label']:<15} | {h['peak']:<8d} | {h['speech_rms']:<11.1f} | {h['noise_floor']:<12.1f} | {h['snr_db']:<9.1f} | \"{tr}\"")
    print("=" * 90)
print("\n✅ Done! Cleaned audio is saved and ready for listening.")
