@echo off
chcp 65001 >nul
title STE NEOM LOGISTIC SARL - Factures
cd /d "%~dp0"

rem ---- 1. Already set up: start directly ----
if exist ".venv\Scripts\python.exe" goto install

rem ---- 2. Find a supported Python (3.10 to 3.13) ----
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do call :trypy %%V
if defined PY goto makevenv
python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto makevenv

echo.
echo  Python 3.13 est necessaire (les versions 3.14 et 3.15 ne marchent pas encore avec PyMuPDF/numpy).
echo  Installez "Python 3.13" depuis https://www.python.org/downloads/windows/
echo  (cochez "Add Python to PATH"), puis relancez start.bat.
echo.
pause
exit /b 1

:makevenv
echo  Preparation (premiere fois seulement)...
%PY% -m venv .venv
if errorlevel 1 (
  echo  Impossible de creer l'environnement Python.
  pause
  exit /b 1
)

:install
rem ---- 3. Install the libraries in .venv (fast when already installed) ----
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Installation des librairies impossible. Verifiez Internet, supprimez le dossier .venv et relancez start.bat.
  echo.
  pause
  exit /b 1
)

rem ---- 4. Start the app ----
".venv\Scripts\python.exe" serve.py
pause
exit /b 0

:trypy
if defined PY exit /b 0
py -%1 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -%1"
exit /b 0
