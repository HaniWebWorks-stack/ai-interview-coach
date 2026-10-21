@echo off
REM Starts the P1 voice test using your laptop's microphone and speakers.
REM Press Ctrl+C in this window (or close it) to stop.
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
"%VENV%\Scripts\python.exe" agent\stop_old.py
"%VENV%\Scripts\python.exe" agent\agent.py console
echo.
echo The voice test has stopped. You can close this window.
pause
