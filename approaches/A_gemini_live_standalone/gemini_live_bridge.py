#!/usr/bin/env python3
"""
APPROACH A: Gemini Live API Bridge (v4 — Clean VAD + Auto-Reconnect)
====================================================================
Key fixes from v3:
  - REMOVED silence keepalives (they confused Gemini's VAD → long delays)
  - VAD done in bridge: only sends speech to Gemini, not continuous noise
  - Auto-reconnect still active for session drops

Run:
  source .venv/bin/activate
  python3 gemini_live_bridge.py
"""

import os
import asyncio
import socket
import struct
from dotenv import load_dotenv
from pydub import AudioSegment
from google import genai
from google.genai import types

load_dotenv()

# ── CONFIG ──────────────────────────────────────────────────────────────
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")
ESP32_IP         = "192.168.43.186"
ESP32_PORT       = 8005
MIC_RATE         = 16000
CHUNK_SIZE       = 3200          # 100ms at 16kHz 16-bit mono
NOISE_FLOOR      = 300           # RMS below this = silence
SPEECH_CHUNKS    = 3             # Need 3 loud chunks to confirm speech started
SILENCE_CHUNKS   = 8             # 8 silent chunks (800ms) = end of speech

ROBOT_PERSONA = """You are MEMO, a small friendly AI robot with a tiny OLED screen.
Reply in 1 SHORT sentence (max 15 words). Be warm, direct, skip filler phrases."""

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={"api_version": "v1alpha"}
)

LIVE_CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=ROBOT_PERSONA,
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
        )
    ),
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)

robot_speaking = False


def rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0: return 0.0
    s = struct.unpack(f"<{n}h", pcm[:n*2])
    return (sum(x*x for x in s) / n) ** 0.5


def send_text(sock, text):
    try: sock.sendall(f"TEXT:{text}\n".encode())
    except: pass


def send_audio(sock, pcm_24k_mono: bytes):
    try:
        audio = AudioSegment(data=pcm_24k_mono, sample_width=2, frame_rate=24000, channels=1)
        audio = (audio + 6).set_frame_rate(16000).set_channels(2)
        pcm = audio.raw_data
        sock.sendall(b"AUDIO" + struct.pack(">I", len(pcm)))
        sock.sendall(pcm)
        print(f"[SPK] {len(pcm)} bytes → speaker")
    except Exception as e:
        print(f"[SPK] Error: {e}")


async def run_session(esp32_sock, session):
    """One Gemini Live session with bridge-side VAD."""
    global robot_speaking
    loop = asyncio.get_event_loop()
    stop = asyncio.Event()

    async def mic_sender():
        """Bridge-side VAD: detect speech segments, send only those to Gemini."""
        buf = bytearray()
        speech_buf = bytearray()
        loud_count = 0
        silent_count = 0
        in_speech = False

        while not stop.is_set():
            try:
                data = await asyncio.wait_for(
                    loop.run_in_executor(None, esp32_sock.recv, 1024), timeout=1.5
                )
                if not data: break
                buf.extend(data)

                while len(buf) >= CHUNK_SIZE:
                    chunk = bytes(buf[:CHUNK_SIZE])
                    buf = buf[CHUNK_SIZE:]

                    if robot_speaking:
                        loud_count = 0
                        silent_count = 0
                        in_speech = False
                        speech_buf.clear()
                        continue

                    energy = rms(chunk)

                    if energy > NOISE_FLOOR:
                        loud_count += 1
                        silent_count = 0
                        if not in_speech and loud_count >= SPEECH_CHUNKS:
                            in_speech = True
                            print("[VAD] 🎤 Speech started")
                            send_text(esp32_sock, "Listening...")
                        if in_speech:
                            speech_buf.extend(chunk)
                            # Stream speech chunk to Gemini immediately
                            await session.send_realtime_input(
                                media=types.Blob(
                                    mime_type=f"audio/pcm;rate={MIC_RATE}",
                                    data=chunk
                                )
                            )
                    else:
                        if in_speech:
                            silent_count += 1
                            # Keep sending brief silence so Gemini hears end of speech
                            await session.send_realtime_input(
                                media=types.Blob(
                                    mime_type=f"audio/pcm;rate={MIC_RATE}",
                                    data=chunk
                                )
                            )
                            if silent_count >= SILENCE_CHUNKS:
                                print(f"[VAD] 🔇 Speech ended ({len(speech_buf)} bytes)")
                                in_speech = False
                                loud_count = 0
                                silent_count = 0
                                speech_buf.clear()
                                send_text(esp32_sock, "Thinking...")
                        else:
                            loud_count = 0

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[MIC] {e}"); break
        stop.set()

    async def speaker_receiver():
        global robot_speaking
        audio_buf = bytearray()
        try:
            async for resp in session.receive():
                if stop.is_set(): break
                if hasattr(resp, 'data') and resp.data:
                    audio_buf.extend(resp.data)
                if resp.server_content:
                    if resp.server_content.turn_complete and audio_buf:
                        print(f"[Gemini] ✅ {len(audio_buf)} bytes response")
                        robot_speaking = True
                        send_text(esp32_sock, "Speaking...")
                        send_audio(esp32_sock, bytes(audio_buf))
                        audio_buf.clear()
                        await asyncio.sleep(0.3)
                        robot_speaking = False
                        send_text(esp32_sock, "Listening...")
                    if resp.server_content.interrupted:
                        audio_buf.clear()
                        robot_speaking = False
        except Exception as e:
            print(f"[Recv] {e}")
        finally:
            stop.set()

    await asyncio.gather(mic_sender(), speaker_receiver())


async def main_loop(esp32_sock):
    count = 0
    while True:
        count += 1
        print(f"\n[Gemini] Connecting session #{count}...")
        send_text(esp32_sock, "Connecting..." if count > 1 else "Ready...")
        try:
            async with gemini_client.aio.live.connect(
                model="gemini-2.5-flash-native-audio-latest", config=LIVE_CONFIG
            ) as session:
                print(f"[Gemini] Session #{count} live ✅")
                send_text(esp32_sock, "Listening...")
                await run_session(esp32_sock, session)
        except Exception as e:
            print(f"[Gemini] Session #{count} error: {e}")
        print("[Gemini] Reconnecting in 2s...")
        await asyncio.sleep(2)


def main():
    print("=" * 50)
    print("  MEMO — Gemini Live Bridge v4 (VAD + Reconnect)")
    print("=" * 50)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((ESP32_IP, ESP32_PORT))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(None)
    print("ESP32 Connected! ✅")
    asyncio.run(main_loop(sock))


if __name__ == "__main__":
    main()
