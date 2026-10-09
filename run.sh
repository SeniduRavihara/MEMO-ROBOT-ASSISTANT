#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/WORKING_SAMPLE/voice_response_AI/python_backend"

echo "=========================================================="
echo "🤖 Starting MEMO AI Voice Robot Server..."
echo "🧹 Spectral Subtraction & Noise Filtering Enabled (>90% cut)"
echo "=========================================================="

cd "$BACKEND_DIR"
exec "$BACKEND_DIR/.venv/bin/python3" live_server.py "$@"
