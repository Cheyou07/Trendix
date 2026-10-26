#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d "node_modules" ]; then
  echo "Installing frontend dependencies..."
  npm install
fi
echo ""
echo "Starting frontend — open the URL it prints below (usually http://localhost:5173)"
echo ""
npm run dev
