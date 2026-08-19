@echo off
chcp 65001 > nul
title Garage Bot
echo =========================================
echo   Garage Bot - Wialon + Telegram
echo =========================================
echo.
echo Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)
echo.
echo Installing requirements...
pip install -r requirements.txt -q
echo.
echo Starting bot...
echo Press Ctrl+C to stop.
echo.
python main.py
pause
