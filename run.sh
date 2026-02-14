#!/bin/bash
cd "$(dirname "$0")"

# Create venv if not exists
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Create data dir
mkdir -p data

# Run server
uvicorn app.main:app --host 0.0.0.0 --port 8087 --reload
