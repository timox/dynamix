@echo off
REM DynaMix - Windows installer
REM Creates a virtual environment, installs the requirements and checks the setup.
REM Usage: double-click this file or run it from the dynamix folder in a terminal.

setlocal
cd /d "%~dp0"

echo === DynaMix - Windows installation ===
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON=python"
    ) else (
        echo [ERROR] Python not found. Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
        echo         and tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
)

echo [1/4] Creating virtual environment (venv)...
if not exist venv (
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo [2/4] Upgrading pip...
call venv\Scripts\python.exe -m pip install --upgrade pip >nul

echo [3/4] Installing requirements (this can take a few minutes)...
call venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. See the messages above.
    echo         If numba/llvmlite failed to build, install Python 3.11 or 3.12 and run this script again.
    pause
    exit /b 1
)

echo [4/4] Checking the installation...
call venv\Scripts\python.exe check_install.py
set "RESULT=%errorlevel%"

echo.
if "%RESULT%"=="0" (
    echo Installation complete. To use DynaMix, open a terminal in this folder and run:
    echo     venv\Scripts\activate
    echo     python gui.py
) else (
    echo Installation finished with errors. Fix them and run check_install.py again.
)
pause
exit /b %RESULT%
