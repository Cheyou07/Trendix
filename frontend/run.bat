@echo off
cd /d "%~dp0"

if not exist node_modules (
    echo Installing frontend dependencies...
    npm install
)

echo.
echo Starting frontend -- open the URL it prints below (usually http://localhost:5173)
echo.
npm run dev
