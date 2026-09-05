@echo off
REM DynaMix - launch the graphical interface (double-click me)
setlocal
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (
    echo [ERROR] venv not found. Run install_windows.bat first.
    pause
    exit /b 1
)
start "" venv\Scripts\pythonw.exe gui.py
exit /b 0
