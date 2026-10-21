@echo off
REM Saves your LiveAvatar API key on THIS laptop only, outside OneDrive:
REM   %LOCALAPPDATA%\ai-interview-coach\agent.env   (other saved keys are kept)
REM Then checks it (free - uses no credits).
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
set LOG=liveavatar-check-log.txt
echo.
echo Paste your LiveAvatar API key (right-click to paste), then press Enter.
echo.
set /p NEW_LIVEAVATAR_API_KEY=LiveAvatar key: 
echo.
echo Checking with LiveAvatar...
"%VENV%\Scripts\python.exe" agent\check_liveavatar.py > "%LOG%" 2>&1
set NEW_LIVEAVATAR_API_KEY=
type "%LOG%"
echo.
echo Done. You can close this window.
echo You can close this window.
pause
