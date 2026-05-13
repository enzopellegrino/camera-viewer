#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== Camera Viewer - Setup macOS ==="

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "✅ Setup completato!"
echo ""
echo "Per avviare:   source .venv/bin/activate && python main.py"
echo "Per buildare:  bash build/build_mac.sh"
