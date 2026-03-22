import socket
import struct
import math
import time

def generate_stereo_beep(frequency, duration_sec, sample_rate=16000, volume=0.5):
    """Generates a 16-bit stereo PCM raw byte array of a sine wave."""
    num_samples = int(sample_rate * duration_sec)
    amplitude = int(volume * 32767)
    
    pcm_bytes = bytearray()
    
    for i in range(num_samples):
        t = float(i) / sample_rate
        sample = int(amplitude * math.sin(2.0 * math.pi * frequency * t))
        
        # Pack as 16-bit signed integer (little-endian is standard for PCM)
        packed_sample = struct.pack('<h', sample)
        
        # Stereo format (Right_Left): Append Left Channel, then Right Channel
        pcm_bytes.extend(packed_sample)
        pcm_bytes.extend(packed_sample)
        
    return pcm_bytes

def main():
    print("--- TCP Communication Tester ---")
    robot_ip = input("Enter Robot IP (e.g. 192.168.x.x): ").strip()
    robot_port = 8003
    
    print(f"Connecting to {robot_ip}:{robot_port}...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((robot_ip, robot_port))
        sock.settimeout(None) # Remove timeout for streaming
        print("Connected successfully!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    # 1. Test Text Transmission
    print("\n[1] Sending TEXT Command...")
    text_payload = "Display Works!\n"
    sock.sendall(f"TEXT:{text_payload}".encode('utf-8'))
    print("TEXT sent. Check the OLED display on the ESP32.")
    
    time.sleep(2) # Brief pause

    # 2. Test Audio Transmission
    print("\n[2] Generating PCM Audio Beep...")
    pcm_data = generate_stereo_beep(frequency=440.0, duration_sec=1.5, volume=0.8)
    data_len = len(pcm_data)
    print(f"Generated {data_len} bytes of Stereo 16-bit PCM.")
    
    # Construct Header: "AUDIO" + 4 bytes length (Big Endian)
    header = b"AUDIO" + struct.pack('>I', data_len)
    
    print("Sending AUDIO header and PCM payload...")
    sock.sendall(header)
    sock.sendall(pcm_data)
    
    print("Payload completed! Check if you heard the 440Hz beep on the speaker.")
    
    time.sleep(1)
    sock.close()
    print("Connection closed.")

if __name__ == "__main__":
    main()
