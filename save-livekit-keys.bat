@echo off
REM Saves your LiveKit Cloud project details on THIS laptop only, outside OneDrive:
REM   %LOCALAPPDATA%\ai-interview-coach\agent.env   (other saved keys are kept)
REM Then checks them with LiveKit (free - uses no minutes).
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
set LOG=livekit-check-log.txt
echo.
echo Paste each value (right-click to paste), then press Enter.
echo.
set /p NEW_LIVEKIT_URL=1) LiveKit URL (starts with wss://): 
set /p NEW_LIVEKIT_API_KEY=2) API key (starts with API): 
set /p NEW_LIVEKIT_API_SECRET=3) API secret: 
echo.
echo Checking with LiveKit...
"%VENV%\Scripts\python.exe" agent\check_livekit.py > "%LOG%" 2>&1
set NEW_LIVEKIT_URL=
set NEW_LIVEKIT_API_KEY=
set NEW_LIVEKIT_API_SECRET=
type "%LOG%"
echo.
echo Done. You can close this window.
echo You can close this window.
pause
