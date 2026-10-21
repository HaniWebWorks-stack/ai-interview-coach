@echo off
REM 1) Installs the extra Google package (free).
REM 2) Saves your FREE Google Gemini API key on THIS laptop only, outside OneDrive:
REM      %LOCALAPPDATA%\ai-interview-coach\agent.env
REM 3) Checks the key works (uses no quota, costs nothing).
cd /d "%~dp0"
set APPDIR=%LOCALAPPDATA%\ai-interview-coach
set VENV=%APPDIR%\venv
set LOG=key-check-log.txt

echo.
echo Step 1 of 2: installing the Google voice package (about 1 minute)...
echo === install ===> "%LOG%"
"%VENV%\Scripts\python.exe" -m pip install -r agent\requirements.txt >> "%LOG%" 2>&1

echo.
echo Step 2 of 2: paste your Gemini API key below (right-click to paste),
echo then press Enter. It is saved only on this laptop.
echo.
set /p NEW_GOOGLE_API_KEY=Gemini key: 
if "%NEW_GOOGLE_API_KEY%"=="" (
  echo No key entered. Nothing was saved.
  pause
  exit /b 1
)
echo.
echo Checking the key with Google...
echo === key check ===>> "%LOG%"
"%VENV%\Scripts\python.exe" agent\check_gemini.py >> "%LOG%" 2>&1
set NEW_GOOGLE_API_KEY=
echo === end ===>> "%LOG%"
echo.
powershell -NoProfile -Command "Get-Content '%LOG%' | Select-String -Pattern 'PASS|FAIL|available|Key |  - '"
echo.
echo Done. You can close this window.
echo You can close this window.
pause
