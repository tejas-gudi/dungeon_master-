@echo off
setlocal
cd /d "%~dp0"

if not exist venv (
    where python >nul 2>nul
    if not errorlevel 1 (
        echo Creating virtual environment with python...
        python -m venv venv
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 (
            echo Creating virtual environment with py -3...
            py -3 -m venv venv
        ) else (
            echo Could not find a working Python 3 interpreter ^(tried python, py^).
            echo Install Python 3.10+ and make sure it's on PATH, then run this script again.
            exit /b 1
        )
    )
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Created .env from .env.example -- fill in DISCORD_TOKEN and NVIDIA_API_KEY, then run this script again.
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [WARN] ffmpeg not found on PATH - voice playback ^(TTS^) will not work until it's installed.
)

python bot.py
