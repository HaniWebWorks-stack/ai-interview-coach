@echo off
REM AI Interview Coach - starts the app.
REM Opens TWO windows: 1) the AI coach (voice + avatar), 2) this window = the
REM local web server. Your browser opens at http://localhost:8765
REM Close both windows to stop.
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
set AVATAR_ENABLED=true
%VENV%\Scripts\python.exe agent\stop_old.py
echo Starting the AI coach in a second window...
start "Interview Coach - AI coach (keep open)" cmd /k %VENV%\Scripts\python.exe agent\agent.py dev
echo Waiting for the coach to connect...
timeout /t 10 /nobreak >nul
echo Opening the app...
%VENV%\Scripts\python.exe agent\viewer_server.py
pause
