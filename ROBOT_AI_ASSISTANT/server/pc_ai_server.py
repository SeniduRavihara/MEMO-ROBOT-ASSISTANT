# PC AI SERVER: Multimodal Gemini Voice Assistant
import os, socket, struct, io, asyncio, edge_tts, math, wave
from pydub import AudioSegment
from dotenv import load_dotenv
import google.generativeai as genai

# --- CONFIG ---
load_dotenv()
LISTEN_PORT = 8006
VOLUME_BOOST = 12 

# VAD Parameters
VAD_THRESHOLD = 500   
SILENCE_TIMEOUT = 1.0 
MIN_SPEECH_LEN = 0.4  

# GEMINI SETUP
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("[WARNING] GEMINI_API_KEY not found in .env file!")

genai.configure(api_key=GEMINI_API_KEY)
# Using flash-latest (1.5 Flash) for free-tier stability
MODEL_NAME = 'gemini-flash-latest'
try:
    model = genai.GenerativeModel(MODEL_NAME)
except:
    model = genai.GenerativeModel('gemini-1.5-flash')

async def generate_tts(text: str) -> bytes:
    try:
        print(f"[TTS] Voice: '{text}'")
        communicate = edge_tts.Communicate(text, voice="en-US-GuyNeural")
        mp3_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])
        mp3_buf.seek(0)
        audio = AudioSegment.from_mp3(mp3_buf)
        audio = audio.set_frame_rate(24000).set_channels(2).set_sample_width(2)
        audio = audio + VOLUME_BOOST
        return audio.raw_data
    except Exception as e:
        print(f"[ERROR] TTS Failed: {e}")
        return b""

async def get_ai_response_from_audio(audio_data: bytes) -> str:
    if not GEMINI_API_KEY:
        return "System error: API key missing."
    try:
        # Convert raw PCM 16kHz to WAV
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_data)
        wav_buf.seek(0)
        
        # Upload to Gemini (Multimodal)
        # Note: In a production environment, you might use the Files API, 
        # but for small clips, we can sometimes send bytes if supported or use a temp file.
        # Here we'll use a temp file for maximum compatibility with the SDK.
        temp_filename = "temp_input.wav"
        with open(temp_filename, "wb") as f:
            f.write(wav_buf.read())
            
        # Final check: is there actually sound?
        samples = struct.unpack(f"<{len(audio_data)//2}h", audio_data)
        if max(samples) < 500: # Very silent
             return "" 
             
        audio_file = await asyncio.to_thread(genai.upload_file, path=temp_filename, mime_type="audio/wav")
        
        # Use a more natural prompt
        response = await asyncio.to_thread(
            model.generate_content, 
            ["You are a friendly robot assistant. Listen to the user's audio and give a very short, helpful response:", audio_file]
        )
        
        # Cleanup and extract text
        os.remove(temp_filename)
        text = response.text.replace("*", "").replace("#", "").strip()
        return text
    except Exception as e:
        print(f"[AI ERROR] {e}")
        return f"System error: {str(e)[:50]}"

async def server_main():
    print(f"\n[AI VOICE SERVER] Port: {LISTEN_PORT}")
    print(f"API Key: {'[FOUND]' if GEMINI_API_KEY else '[MISSING]'}")
    
    async def client_handler(reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Robot connected from {addr}")
        
        mic_buffer = bytearray()
        is_user_speaking = False
        last_speech_time = 0.0
        
        # Manual Test Thread
        async def manual_test():
            while True:
                text = await asyncio.to_thread(input, "")
                if text.strip():
                    pcm = await generate_tts(text)
                    if pcm:
                        header = b'AUDIO' + struct.pack('>I', len(pcm))
                        writer.write(header)
                        writer.write(pcm)
                        await writer.drain()
                        print("[TEST] Sent to Speaker.")

        asyncio.create_task(manual_test())

        while True:
            try:
                data = await reader.read(2048)
                if not data: break
                
                if len(data) >= 2:
                    samples = struct.unpack(f"<{len(data)//2}h", data)
                    rms = math.sqrt(sum(s*s for s in samples) / len(samples))
                    
                    if rms > VAD_THRESHOLD:
                        if not is_user_speaking:
                            is_user_speaking = True
                            mic_buffer.clear()
                        mic_buffer.extend(data)
                        last_speech_time = asyncio.get_event_loop().time()
                    
                    elif is_user_speaking:
                        if (asyncio.get_event_loop().time() - last_speech_time) > SILENCE_TIMEOUT:
                            is_user_speaking = False
                            print(f"\n[VAD] User spoke ({len(mic_buffer)} bytes). Calling Gemini Multimodal...")
                            
                            # Real AI Response from Audio
                            resp_text = await get_ai_response_from_audio(bytes(mic_buffer))
                            
                            if resp_text:
                                pcm = await generate_tts(resp_text)
                                if pcm:
                                    header = b'AUDIO' + struct.pack('>I', len(pcm))
                                    writer.write(header)
                                    writer.write(pcm)
                                    await writer.drain()
                                    print("[AI] Response sent to Robot.")
                            
                            mic_buffer.clear()

                    bar = "#" * int(rms / 100)
                    print(f"\r[MIC] RMS: {int(rms):4} | {bar:<30} {'(USER)' if is_user_speaking else '(IDLE)'}", end="", flush=True)

            except Exception as e:
                print(f"\n[ERROR] {e}")
                break
        
        print("\nRobot disconnected.")
        writer.close()

    server = await asyncio.start_server(client_handler, '0.0.0.0', LISTEN_PORT)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(server_main())
    except KeyboardInterrupt:
        print("\nCleaning up...")
