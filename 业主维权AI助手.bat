@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Owner Rights AI Assistant...

rem Probe order: python in PATH -> py launcher -> WorkBuddy bundled Python.
rem Verify each candidate with "import kivy" so we never launch a broken interpreter.
set "PYEXE="

where python >nul 2>&1
if not errorlevel 1 (
  python -c "import kivy" >nul 2>&1
  if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
  py -3 -c "import kivy" >nul 2>&1
  if not errorlevel 1 set "PYEXE=py -3"
)

if not defined PYEXE (
  for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    if exist "%%D\python.exe" (
      "%%D\python.exe" -c "import kivy" >nul 2>&1
      if not errorlevel 1 set "PYEXE=%%D\python.exe"
    )
  )
)

if not defined PYEXE (
  echo.
  echo [ERROR] No Python with kivy found.
  echo Install Python 3.13 and run:  pip install kivy requests
  pause
  exit /b 1
)

echo Using Python: %PYEXE%
echo.
%PYEXE% app.py
if errorlevel 1 (
  echo.
  echo [ERROR] App exited with error. See messages above.
  pause
)
