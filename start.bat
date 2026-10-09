@echo off
setlocal
cd /d "%~dp0"
title TPS Windows Client - Startup
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 goto existing
)
py -3.12 --version >nul 2>&1
if not errorlevel 1 goto py312
py -3 --version >nul 2>&1
if not errorlevel 1 goto pydefault
python --version >nul 2>&1
if not errorlevel 1 goto pythondefault
echo [Launcher ERROR] Python was not found. Install Python 3.12 from python.org.
echo Enable the Python launcher and Tcl/Tk during installation.
set "launch_exit=1"
goto finish
:existing
".venv\Scripts\python.exe" bootstrap.py %*
goto result
:py312
py -3.12 bootstrap.py %*
goto result
:pydefault
py -3 bootstrap.py %*
goto result
:pythondefault
python bootstrap.py %*
:result
set "launch_exit=%errorlevel%"
:finish
if "%launch_exit%"=="0" goto done
echo.
echo Startup failed. Read the message above.
if /i "%~1"=="--check" goto done
pause
:done
exit /b %launch_exit%
