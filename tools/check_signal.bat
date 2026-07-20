@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run: python -m venv .venv
  exit /b 1
)
".venv\Scripts\python.exe" tools\manual_signal.py
pause
