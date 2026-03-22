import socket
import struct
import io
import asyncio
import edge_tts
from pydub import AudioSegment

# --- CONFIG ---
LISTEN_PORT = 8006
TEXT_TO_SAY = "How are you? I am a happy robot."

async def generate_pcm(text):
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
    return audio.raw_data

def start_server_and_send(pcm_data):
    """Starts a server and waits for the ESP32 to connect to THIS PC."""
    print(f"\n==========================================")
    print(f"TCP SERVER STARTED on port {LISTEN_PORT}")
    print(f"==========================================")
    
    # Get PC IP to show user
    s_ip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s_ip.connect(("8.8.8.8", 80))
        pc_ip = s_ip.getsockname()[0]
    finally:
        s_ip.close()
    
    print(f"PC IP address: {pc_ip}")
    print("Waiting for Robot to connect...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', LISTEN_PORT))
        s.listen(1)
        
        conn, addr = s.accept()
        with conn:
            print(f"Robot connected from {addr}!")
            length = len(pcm_data)
            header = b'AUDIO' + struct.pack('>I', length)
            
            print(f"Sending audio ({length} bytes)...")
            conn.sendall(header)
            conn.sendall(pcm_data)
            print("Done! Audio should be playing now.")

async def main():
    pcm = await generate_pcm(TEXT_TO_SAY)
    start_server_and_send(pcm)

if __name__ == "__main__":
    asyncio.run(main())
