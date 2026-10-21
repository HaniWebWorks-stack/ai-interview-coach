@echo off
REM AI Interview Coach - installs the Python packages for the agent.
REM The packages go in a private folder OUTSIDE OneDrive, so OneDrive
REM does not try to sync thousands of library files:
REM   %LOCALAPPDATA%\ai-interview-coach\venv
REM Nothing else on the computer is changed.
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\ai-interview-coach\venv
set LOG=setup-log.txt
echo AI Interview Coach - setup log> "%LOG%"
echo Started: %date% %time%>> "%LOG%"

echo.
echo Installing the AI voice packages. This usually takes 3 to 6 minutes.
echo Please keep this window open...
echo.

echo === 1. Create private Python environment ===>> "%LOG%"
if not exist "%VENV%\Scripts\python.exe" (
  py -3.14 -m venv "%VENV%" >> "%LOG%" 2>&1
) else (
  echo Already exists, reusing it.>> "%LOG%"
)

echo === 2. Upgrade pip ===>> "%LOG%"
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1

echo === 3. Install packages ===>> "%LOG%"
"%VENV%\Scripts\python.exe" -m pip install -r agent\requirements.txt >> "%LOG%" 2>&1
echo pip exit code: %errorlevel%>> "%LOG%"

echo === 4. Test that the packages load ===>> "%LOG%"
"%VENV%\Scripts\python.exe" -c "import sys, livekit.agents as a; from livekit.plugins import openai, liveavatar; print('IMPORT TEST PASSED - python', sys.version.split()[0], '- livekit-agents', a.__version__)" >> "%LOG%" 2>&1

echo Finished: %date% %time%>> "%LOG%"
echo END OF LOG>> "%LOG%"

echo.
echo Done. You can close this window.
echo You can close this window.
pause
