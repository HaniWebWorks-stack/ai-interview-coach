@echo off
REM OPTIONAL / PAID - not needed for the free Gemini path.
REM Saves an OpenAI API key on THIS laptop only, outside OneDrive, keeping any
REM other saved keys, and switches the voice provider to OpenAI.
REM The check itself is free (no money spent).
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
set LOG=key-check-log.txt
echo.
echo Paste your OpenAI API key below (right-click to paste), then press Enter.
echo.
set /p NEW_OPENAI_API_KEY=OpenAI key: 
if "%NEW_OPENAI_API_KEY%"=="" (
  echo No key entered. Nothing was saved.
  pause
  exit /b 1
)
echo Checking the key with OpenAI...
"%VENV%\Scripts\python.exe" agent\check_openai.py > "%LOG%" 2>&1
set NEW_OPENAI_API_KEY=
type "%LOG%"
echo.
echo Done. You can close this window.
pause
