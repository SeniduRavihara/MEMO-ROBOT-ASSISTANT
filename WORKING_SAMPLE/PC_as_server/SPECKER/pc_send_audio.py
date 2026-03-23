import socket
import struct
import io
import asyncio
import edge_tts
from pydub import AudioSegment

# --- CONFIG ---
LISTEN_PORT = 8006
VOLUME_BOOST = 1  # Standard boost from working sample

async def generate_pcm(text: str) -> bytes:
    """Converts text to raw 16kHz Stereo 16-bit PCM."""
    print(f"Generating audio for: '{text}'...")
    communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
    mp3_buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buf.write(chunk["data"])
    mp3_buf.seek(0)
    
    audio = AudioSegment.from_mp3(mp3_buf)
    audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2)
    # Apply volume boost
    audio = audio + VOLUME_BOOST
    return audio.raw_data

async def main():
    print(f"\n==========================================")
    print(f"EXPERIMENT TTS SERVER STARTED (Port {LISTEN_PORT})")
    print(f"==========================================")

    # Get PC IP
    s_ip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s_ip.connect(("8.8.8.8", 80))
        pc_ip = s_ip.getsockname()[0]
    finally:
        s_ip.close()
    
    print(f"PC IP address for Robot to find: {pc_ip}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', LISTEN_PORT))
        s.listen(5)
        
        while True:
            print(f"\n[READY] Waiting for Robot to connect...")
            conn, addr = s.accept()
            with conn:
                print(f"Robot connected from {addr}")
                
                while True:
                    text = input("\nType text for Robot (or 'q' to disconnect robot): ").strip()
                    if not text: continue
                    if text.lower() == 'q': break
                    
                    try:
                        pcm = await generate_pcm(text)
                        length = len(pcm)
                        header = b'AUDIO' + struct.pack('>I', length)
                        
                        print(f"Sending {length} bytes of audio...")
                        conn.sendall(header)
                        conn.sendall(pcm)
                        print("Done!")
                    except Exception as e:
                        print(f"Connection lost: {e}")
                        break 
                
                print("Robot disconnected.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
