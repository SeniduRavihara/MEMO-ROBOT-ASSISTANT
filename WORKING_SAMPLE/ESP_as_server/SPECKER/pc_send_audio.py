"""
ESP_as_server / SPEAKER Test — PC connects to Robot and sends TTS audio.
Run this after flashing robot_speaker.ino. Auto-retries until Robot is ready.
Port: 8005
"""
import socket, struct, io, asyncio, edge_tts, time
from pydub import AudioSegment

ROBOT_IP   = "192.168.43.59"
ROBOT_PORT = 8005

async def tts_pcm(text):
    comm = edge_tts.Communicate(text, "en-US-GuyNeural")
    buf = io.BytesIO()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    audio = AudioSegment.from_mp3(buf)
    audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2)
    return (audio + 12).raw_data

async def main():
    # Auto-retry until Robot is ready
    sock = None
    print(f"Waiting for Robot at {ROBOT_IP}:{ROBOT_PORT}...")
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((ROBOT_IP, ROBOT_PORT))
            print(f"Connected to Robot!\n")
            sock.settimeout(30)
            break
        except (ConnectionRefusedError, socket.timeout):
            print("  Robot not ready, retrying in 2s...", end="\r")
            sock.close()
            time.sleep(2)
        except KeyboardInterrupt:
            print("\nCancelled."); return

    while True:
        text = input("Type text for Robot to say (q=quit): ").strip()
        if text == "q": break
        if not text: continue
        print("Generating speech...")
        pcm = await tts_pcm(text)
        sock.sendall(b"AUDIO" + struct.pack(">I", len(pcm)))
        sock.sendall(pcm)
        print(f"  Sent {len(pcm)} bytes. Robot should say it now!\n")

    sock.close()

asyncio.run(main())
