import os
import time
import socket
import struct
import io
import asyncio
import speech_recognition as sr
from pydub import AudioSegment
from dotenv import load_dotenv
from google import genai
import edge_tts

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
client_ai = genai.Client(api_key=API_KEY)

# Port 8006: PC is SERVER (Robot connects here for Speaker/Text)
# Port 8005: Robot is SERVER (PC connects here for Mic)
PC_SPK_PORT = 8006
ROBOT_MIC_PORT = 8005

# Audio processing
SAMPLE_RATE = 16000
RMS_THRESHOLD = 500  # Voice detection sensitivity

def get_rms(data):
    n = len(data) // 2
    if n == 0: return 0
    samples = struct.unpack(f"<{n}h", data)
    return int((sum(s*s for s in samples) / n) ** 0.5)

async def tts_to_pcm(text):
    """Generate 16-bit Stereo PCM for the Robot (Port 8006 pattern)."""
    communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    audio = AudioSegment.from_mp3(buf)
    # Match the working simple_tts_test: 16kHz, Stereo, 16-bit
    audio = audio.set_frame_rate(SAMPLE_RATE).set_channels(2).set_sample_width(2)
    return (audio + 12).raw_data  # Boost volume 12dB

async def main():
    print("\n" + "="*42)
    print("SPEAK-AI ENGINE — HYBRID DUAL-PIPE MODE")
    print("="*42)
    
    # 1. Start Speaker Server (Port 8006) - PC WAITS FOR ROBOT
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("0.0.0.0", PC_SPK_PORT))
    server_sock.listen(1)
    
    print(f"\n[STEP 1] Listening on Port {PC_SPK_PORT} (SPK)...")
    print("        (Robot will find you automatically)")
    
    spk_conn, addr = server_sock.accept()
    robot_ip = addr[0]
    print(f"[OK] Speaker pipe connected from Robot at {robot_ip}")

    # 2. Connect to Robot Mic (Port 8005) - PC CONNECTS TO ROBOT
    print(f"\n[STEP 2] Connecting to Robot Mic at {robot_ip}:{ROBOT_MIC_PORT}...")
    mic_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # Retry connection a few times if robot is still booting
    for i in range(5):
        try:
            mic_sock.connect((robot_ip, ROBOT_MIC_PORT))
            print("[OK] Microphone pipe connected.")
            break
        except Exception as e:
            print(f"      Retry {i+1}/5...")
            time.sleep(2)
    else:
        print("[ERROR] Could not connect to Robot Mic.")
        return

    # 3. Start Processing Loop
    recognizer = sr.Recognizer()
    print("\n[READY] Start speaking to the Robot! 🎤🤖")
    
    while True:
        try:
            print("\n" + "-"*30)
            print(" [LISTENING]...")
            audio_buffer = io.BytesIO()
            silence_start = None
            voice_detected = False
            start_time = time.time()

            # Buffer audio until silence
            while True:
                data = mic_sock.recv(2048)
                if not data: break
                
                audio_buffer.write(data)
                rms = get_rms(data)
                
                if rms > RMS_THRESHOLD:
                    voice_detected = True
                    silence_start = None
                elif voice_detected:
                    if silence_start is None: silence_start = time.time()
                    if time.time() - silence_start > 1.2: break # 1.2s silence
                
                # Max 10s recording
                if time.time() - start_time > 10: break

            if not voice_detected:
                continue

            # Process Speech
            audio_buffer.seek(0)
            raw_audio = audio_buffer.read()
            print(f"[SERVER] Captured {len(raw_audio)} bytes. Processing...")
            
            audio_data = sr.AudioData(raw_audio, SAMPLE_RATE, 2)
            try:
                user_text = recognizer.recognize_google(audio_data)
                print(f"User: {user_text}")
            except Exception:
                print("[SERVER] Could not understand audio.")
                continue

            # Get AI Response
            try:
                response = client_ai.models.generate_content(
                    model="gemini-2.0-flash-exp", # Use high-speed experimental model
                    contents=user_text
                )
                ai_reply = response.text.strip()
                print(f"AI: {ai_reply}")
            except Exception as e:
                print(f"[AI ERROR] {e}")
                ai_reply = "I am sorry, my AI brain is acting up."

            # Send back to Robot (Text + Audio)
            # a) Send TEXT to OLED
            spk_conn.sendall(f"TEXT:{ai_reply}\n".encode())
            
            # b) Send AUDIO to Speaker
            print("[SERVER] Synthesizing speech...")
            pcm_data = await tts_to_pcm(ai_reply)
            header = b"AUDIO" + struct.pack(">I", len(pcm_data))
            spk_conn.sendall(header)
            spk_conn.sendall(pcm_data)
            print("[SERVER] Playback finished.")

        except Exception as e:
            print(f"[CRITICAL ERROR] {e}")
            break

    mic_sock.close()
    spk_conn.close()
    server_sock.close()

if __name__ == "__main__":
    asyncio.run(main())
