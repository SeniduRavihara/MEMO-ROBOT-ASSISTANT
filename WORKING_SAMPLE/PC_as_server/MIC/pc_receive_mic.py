"""
==========================================
PROJECT: PC_as_server / MICROPHONE
MODE:    PC is SERVER (Listening).
PORT:    8007
==========================================
"""
import socket, struct

PC_PORT = 8007 

def rms(data):
    n = len(data) // 2
    if n == 0: return 0
    # Little-endian 16-bit PCM
    samples = struct.unpack(f"<{n}h", data)
    return int((sum(s*s for s in samples) / n) ** 0.5)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PC_PORT)) 
    s.listen(1)
    print(f"\n[MIC SERVER READY] Listening on {PC_PORT} — Waiting for Robot...")
    
    conn, addr = s.accept()
    with conn:
        print(f"[CONNECTED] Robot found from {addr}\n")
        while True:
            try:
                data = conn.recv(1024)
                if not data: break
                v = rms(data)
                bar = "#" * (v // 30)
                print(f" RMS: {v:5d} | {bar:<50}", end="\r")
            except KeyboardInterrupt:
                break
print("\nDone.")
