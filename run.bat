@echo off
title Twitch Chat Downloader
cd /d "%~dp0"
echo Installing dependencies...
pip install -r requirements.txt > nul
echo Starting Twitch Chat Downloader...
python main.py
pause
