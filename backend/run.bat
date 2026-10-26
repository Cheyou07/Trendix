@echo off
cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo Installing dependencies (first run only, may take a minute)...
venv\Scripts\python.exe -m pip install -q -r requirements.txt

echo.
echo Starting backend on http://localhost:8000 -- leave this window open.
echo.
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

echo.
echo The server stopped or failed to start. Read any red error text above.
pause
