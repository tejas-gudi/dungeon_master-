#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    PYTHON=""
    for candidate in python3 python py; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done

    if [ -z "$PYTHON" ]; then
        echo "Could not find a working Python 3 interpreter (tried python3, python, py)."
        echo "Install Python 3.10+ and make sure it's on PATH, then run this script again."
        exit 1
    fi

    echo "Creating virtual environment with $PYTHON..."
    "$PYTHON" -m venv venv
fi

# venv layout differs: bin/ on Linux/Mac, Scripts/ on native Windows (even under Git Bash)
if [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source venv/Scripts/activate
else
    echo "Could not find the venv activation script — venv/ may be corrupt. Delete it and run this script again."
    exit 1
fi

echo "Installing dependencies..."
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example — fill in DISCORD_TOKEN and NVIDIA_API_KEY, then run this script again."
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[WARN] ffmpeg not found on PATH — voice playback (TTS) will not work until it's installed."
fi

python bot.py
