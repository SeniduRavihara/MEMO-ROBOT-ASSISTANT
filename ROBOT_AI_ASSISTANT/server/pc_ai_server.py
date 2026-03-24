# PC AI SERVER: "I HEARD YOU" OFFLINE TEST (No Gemini Needed)
import os, socket, struct, io, asyncio, edge_tts, math, wave
from pydub import AudioSegment

# --- CONFIG ---
LISTEN_PORT = 8006
VOLUME_BOOST = 12 

# VAD Parameters
VAD_THRESHOLD = 500   
SILENCE_TIMEOUT = 1.0 
MIN_SPEECH_LEN = 0.4  

# TEST MODE: DISABLE GEMINI
SKIP_AI = True 

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

async def server_main():
    print(f"\n[OFFLINE TEST SERVER] Port: {LISTEN_PORT}")
    print("Mode: 'I HEARD YOU' (No Gemini needed)")
    
    async def client_handler(reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Robot connected from {addr}")
        
        mic_buffer = bytearray()
        is_user_speaking = False
        last_speech_time = 0
        
        # Manual Test Thread (Always alive)
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
                
                # VAD: Calculate energy
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
                            print(f"\n[VAD] User spoke ({len(mic_buffer)} bytes). Responding...")
                            
                            # Canned Response (Instant Offline Test)
                            resp_text = "I heard you loud and clear!"
                            pcm = await generate_tts(resp_text)
                            if pcm:
                                header = b'AUDIO' + struct.pack('>I', len(pcm))
                                writer.write(header)
                                writer.write(pcm)
                                await writer.drain()
                                print("[OFFLINE] Response sent to Robot.")
                            
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
