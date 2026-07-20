"""
ESP_as_server / MIC Test — PC receives mic from Robot
Robot must be flashed first. This script auto-retries until Robot is ready.
Port: 8005
"""
import socket, struct, time

ROBOT_IP   = "192.168.43.59"
ROBOT_PORT = 8005

def rms(data):
    n = len(data) // 2
    if n == 0: return 0
    samples = struct.unpack(f"<{n}h", data)
    return int((sum(s*s for s in samples) / n) ** 0.5)

# Auto-retry loop — keeps trying until Robot boots
sock = None
print(f"Waiting for Robot at {ROBOT_IP}:{ROBOT_PORT}...")
print("(Make sure robot_mic.ino is flashed!)\n")
while True:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect((ROBOT_IP, ROBOT_PORT))
        print("Connected! Speak into the mic.\n")
        break
    except (ConnectionRefusedError, socket.timeout):
        print("  Robot not ready yet, retrying in 2s...", end="\r")
        sock.close()
        time.sleep(2)
    except KeyboardInterrupt:
        print("\nCancelled.")
        exit()

sock.settimeout(1.0)
while True:
    try:
        data = sock.recv(2048)
        if not data: break
        level = rms(data)
        bar = "#" * (level // 30)
        print(f" RMS: {level:5d} | {bar:<50}", end="\r")
    except socket.timeout:
        pass
    except KeyboardInterrupt:
        break

sock.close()
print("\nDone.")
