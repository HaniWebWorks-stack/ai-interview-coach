@echo off
REM Voice diagnostic: tests your microphone and each free Gemini voice model.
REM Make sure no other voice test window is open before running this.
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
echo.
echo When the countdown finishes, speak clearly towards your laptop.
echo.
"%VENV%\Scripts\python.exe" agent\diagnose_voice.py
echo.
echo Done. You can close this window.
echo You can close this window.
pause
