#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/python_backend"

# Detect Python virtual environment with faster-whisper and piper
if [ -f "$BACKEND_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/bin/python3"
elif [ -f "$SCRIPT_DIR/../WORKING_SAMPLE/voice_response_AI/python_backend/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/../WORKING_SAMPLE/voice_response_AI/python_backend/.venv/bin/python3"
else
    PYTHON_BIN="python3"
fi

echo "=========================================================="
echo "🤖 Starting MEMO AI Voice Robot Server (ROBOT_AI_ASSISTANT)..."
echo "⚡ Silero Neural VAD (Xiaozhi) + Whisper (6 CPU threads)"
echo "🧹 Spectral Subtraction + Piper Local Fast TTS"
echo "=========================================================="

cd "$BACKEND_DIR"
exec "$PYTHON_BIN" live_server.py "$@"
