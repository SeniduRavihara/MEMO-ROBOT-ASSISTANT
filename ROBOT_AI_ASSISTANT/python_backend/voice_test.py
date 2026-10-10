#!/usr/bin/env python3
# Simple direct voice test - bypasses the full server
# Generates TTS and sends it straight to the ESP32

import socket
import asyncio
import io
import struct
import edge_tts
from pydub import AudioSegment

# ---- CHANGE THIS TO YOUR ESP32's IP ----
ESP32_IP   = "192.168.43.186"
ESP32_PORT = 8005

TEST_TEXT = "Hello! I am MEMO, your AI robot assistant. Can you hear me?"

async def generate_tts(text):
    print(f"Generating TTS for: '{text}'")
    communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
    mp3_buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buf.write(chunk["data"])
    mp3_buf.seek(0)

    audio = AudioSegment.from_mp3(mp3_buf)
    audio = audio + 10  # +10dB volume boost
    audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2)
    pcm = audio.raw_data
    print(f"Generated {len(pcm)} bytes of 16kHz stereo 16-bit PCM")
    return pcm

def send_to_esp32(pcm):
    print(f"Connecting to ESP32 at {ESP32_IP}:{ESP32_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((ESP32_IP, ESP32_PORT))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("Connected!")

    # Send TEXT header first (so OLED shows something)
    text_bytes = TEST_TEXT.encode('utf-8')
    sock.sendall(b"TEXT:" + text_bytes + b"\n")
    print("Sent TEXT header")

    import time; time.sleep(1)  # wait for beep to finish

    # Send AUDIO header + PCM data
    header = b'AUDIO' + struct.pack('>I', len(pcm))
    sock.sendall(header)
    sock.sendall(pcm)
    print(f"Sent AUDIO: {len(pcm)} bytes")

    import time; time.sleep(5)  # wait for playback
    sock.close()
    print("Done!")

if __name__ == "__main__":
    pcm = asyncio.run(generate_tts(TEST_TEXT))
    send_to_esp32(pcm)
