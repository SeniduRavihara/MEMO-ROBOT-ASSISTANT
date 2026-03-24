# PC AI SERVER: Multimodal Gemini Voice Assistant (with Transcript)
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
# Using gemini-flash-latest (1.5 Flash) for free-tier stability
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

async def get_ai_response_from_audio(audio_data: bytes) -> tuple:
    """Returns (transcript, response_text)"""
    if not GEMINI_API_KEY:
        return "Key Missing", "System error: API key missing."
    try:
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(audio_data)
        wav_buf.seek(0)
        
        temp_filename = "temp_input.wav"
        with open(temp_filename, "wb") as f: f.write(wav_buf.read())
            
        samples = struct.unpack(f"<{len(audio_data)//2}h", audio_data)
        if max(samples) < 500: # Silence check
            os.remove(temp_filename)
            return None, None
             
        audio_file = await asyncio.to_thread(genai.upload_file, path=temp_filename, mime_type="audio/wav")
        prompt = (
            "You are a friendly robot assistant. Listen to the user's audio. "
            "First, provide a transcript of what the user said (prefixed with 'TRANSCRIPT:'). "
            "Then, provide your response (prefixed with 'RESPONSE:'). Keep the response very short and concise."
        )
        response = await asyncio.to_thread(model.generate_content, [prompt, audio_file])
        
        os.remove(temp_filename)
        output = response.text.replace("*", "").replace("#", "").strip()
        
        # Parse TRANSCRIPT and RESPONSE
        transcript = ""
        reply = ""
        if "TRANSCRIPT:" in output and "RESPONSE:" in output:
            parts = output.split("RESPONSE:")
            transcript = parts[0].replace("TRANSCRIPT:", "").strip()
            reply = parts[1].strip()
        else:
            reply = output # Fallback
            
        return transcript, reply
    except Exception as e:
        print(f"[AI ERROR] {e}")
        return "Error", f"System error: {str(e)[:50]}"

async def server_main():
    print(f"\n[AI VOICE SERVER] Port: {LISTEN_PORT}")
    
    async def client_handler(reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Robot connected from {addr}")
        
        mic_buffer = bytearray()
        is_user_speaking = False
        last_speech_time = 0.0
        
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
                            print(f"\n[VAD] User spoke. Calling Gemini...")
                            
                            transcript, resp_text = await get_ai_response_from_audio(bytes(mic_buffer))
                            
                            if transcript:
                                print(f"[USER] {transcript}")
                                # Send TEXT header
                                text_bytes = f"You: {transcript}".encode('utf-8')
                                header = b'TEXT' + struct.pack('>I', len(text_bytes))
                                writer.write(header + text_bytes)
                                await writer.drain()

                            if resp_text:
                                pcm = await generate_tts(resp_text)
                                if pcm:
                                    header = b'AUDIO' + struct.pack('>I', len(pcm))
                                    writer.write(header + pcm)
                                    await writer.drain()
                                    print("[AI] Response sent to Robot.")
                            
                            mic_buffer.clear()

                    bar = "#" * int(rms / 100)
                    print(f"\r[MIC] RMS: {int(rms):4} | {bar:<30}", end="", flush=True)

            except Exception as e:
                print(f"\n[ERROR] {e}")
                break
        
        print("\nRobot disconnected.")
        writer.close()

    server = await asyncio.start_server(client_handler, '0.0.0.0', LISTEN_PORT)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    try: asyncio.run(server_main())
    except KeyboardInterrupt: print("\nCleaning up...")
