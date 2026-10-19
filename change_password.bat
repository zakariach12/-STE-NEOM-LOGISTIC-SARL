@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo  Lancez dabord start.bat une fois.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" change_password.py
pause
