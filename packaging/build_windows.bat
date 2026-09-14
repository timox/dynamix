@echo off
REM Build the shareable Windows version of DynaMix into dist\DynaMix, then run its self-test.
REM Needs the venv created by install_windows.bat.
setlocal
cd /d "%~dp0\.."
if not exist venv\Scripts\python.exe (
    echo [ERROR] venv not found. Run install_windows.bat first.
    exit /b 1
)
venv\Scripts\python -m pip install --upgrade pyinstaller || exit /b 1
venv\Scripts\python -m PyInstaller packaging\dynamix.spec --noconfirm --distpath dist --workpath build || exit /b 1
start "" /wait dist\DynaMix\DynaMix.exe --self-test dist\selftest.txt
set RESULT=%ERRORLEVEL%
type dist\selftest.txt
if not "%RESULT%"=="0" (
    echo [ERROR] The self-test of the build failed.
    exit /b 1
)
echo.
echo Built: dist\DynaMix  - zip this folder to share DynaMix (DynaMix.exe starts it).
exit /b 0
