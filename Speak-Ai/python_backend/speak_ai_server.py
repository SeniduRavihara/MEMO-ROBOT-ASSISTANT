import os
import time
import socket
import struct
import shutil
import asyncio
import speech_recognition as sr
from pydub import AudioSegment
from dotenv import load_dotenv
from google import genai
import edge_tts

# --- CONFIGURATION ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set!")

# Initialize the NEW Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

# Audio settings
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 500  # RMS threshold
SILENCE_DURATION = 1.0   # Seconds of silence before processing

# --- UTILS ---

def calculate_rms(audio_bytes):
    count = len(audio_bytes) // 2
    if count == 0: return 0
    shorts = struct.unpack(f"<{count}h", audio_bytes)
    sum_squares = sum(s*s for s in shorts)
    return int((sum_squares / count)**0.5)

async def generate_speech_pcm(text):
    """Generate 16kHz 16-bit Stereo PCM for the Robot"""
    try:
        communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
        temp_mp3 = "temp_speech.mp3"
        await communicate.save(temp_mp3)
        
        audio = AudioSegment.from_mp3(temp_mp3)
        audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2)
        
        # Volume Boost for Robot Speaker
        audio = audio + 10 
        
        pcm_data = audio.raw_data
        if os.path.exists(temp_mp3): os.remove(temp_mp3)
        return pcm_data
    except Exception as e:
        print(f"[TTS Error] {e}")
        return b''

def ask_gemini(prompt):
    """Try to get response from Gemini, or return a friendly error message."""
    # List of models to try (some environments have different names)
    models = ['gemini-1.5-flash-latest', 'gemini-1.5-flash', 'gemini-2.0-flash-exp']
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response and response.text:
                return response.text
        except Exception:
            continue
            
    # If all models fail, return a fallback message
    return "I am sorry, my AI brain is currently unavailable. Please check my API key."

# --- MAIN ENGINE ---

async def robot_engine():
    print("\n" + "="*42)
    print("SPEAK-AI ENGINE (PROVEN MODE)")
    print("="*42)

    robot_ip = input("\nEnter Robot IP (from OLED): ").strip()
    if not robot_ip: return

    print(f"\n[CLIENT] Connecting to {robot_ip}:8006...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((robot_ip, 8006))
        sock.settimeout(0.1) 
        print("[CLIENT] Connected! Start speaking to the Robot.")
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return

    audio_buffer = bytearray()
    last_sound_time = time.time()
    is_processing = False

    while True:
        try:
            # 1. READ MIC DATA FROM ROBOT
            try:
                data = sock.recv(2048) # Larger recv
                if not data: break
                
                rms = calculate_rms(data)
                
                if rms > SILENCE_THRESHOLD:
                    if not is_processing: 
                        print(" [HEARING]", end="\r")
                    audio_buffer.extend(data)
                    last_sound_time = time.time()
                    is_processing = True
                
                if is_processing and (time.time() - last_sound_time > SILENCE_DURATION):
                    print(f"\n[SERVER] Processing {len(audio_buffer)} bytes...")
                    
                    # Save temporary WAV for STT
                    temp_wav = "temp_input.wav"
                    audio_seg = AudioSegment(
                        data=bytes(audio_buffer),
                        sample_width=2,
                        frame_rate=16000,
                        channels=1
                    )
                    audio_seg.export(temp_wav, format="wav")
                    
                    # 2. TRANSCRIBE
                    r = sr.Recognizer()
                    with sr.AudioFile(temp_wav) as source:
                        audio_data = r.record(source)
                        try:
                            user_text = r.recognize_google(audio_data)
                            print(f"User: {user_text}")
                            
                            # 3. ASK GEMINI
                            ai_text = ask_gemini(user_text)
                            print(f"AI: {ai_text}")
                            
                            # 4. SEND TEXT TO OLED
                            clean_text = ai_text.replace('\n', ' ').strip()
                            sock.settimeout(30.0) # HEAVY TIMEOUT FOR LARGE AUDIO
                            sock.sendall(f"TEXT:{clean_text}\n".encode('utf-8'))
                            
                            # 5. SEND AUDIO TO SPEAKER
                            print("[SERVER] Synthesizing speech...")
                            pcm = await generate_speech_pcm(clean_text)
                            if pcm:
                                sock.sendall(b'AUDIO' + struct.pack('>I', len(pcm)))
                                sock.sendall(pcm)
                                print("[SERVER] Finished playback.")
                            else:
                                print("[SERVER] Speech generation failed.")

                            sock.settimeout(0.1) # Back to fast recv

                        except sr.UnknownValueError:
                            print("[SERVER] Could not understand audio.")
                        except Exception as inner_e:
                            print(f"[ERROR during processing] {inner_e}")
                            sock.settimeout(0.1)
                    
                    # Reset buffer
                    audio_buffer = bytearray()
                    is_processing = False
                    print(" [Mic Level: 0]", end="\r")

            except socket.timeout:
                pass
            except socket.error:
                pass
            
            await asyncio.sleep(0.01)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n[FATAL ERROR] {e}")
            break

    sock.close()

if __name__ == "__main__":
    try:
        asyncio.run(robot_engine())
    except KeyboardInterrupt:
        print("\n[SERVER] Stopped.")
