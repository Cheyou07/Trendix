#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
echo ""
echo "Starting backend on http://localhost:8000 — leave this window open."
echo ""
uvicorn app.main:app --reload --port 8000
