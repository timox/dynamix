@echo off
REM Build the shareable Windows version of DynaMix into dist\DynaMix, run its self-test, then
REM write dist\DynaMix-<version>-windows-x64.zip and, when Inno Setup is installed,
REM dist\DynaMix-<version>-setup.exe.
REM Needs the venv created by install_windows.bat.
setlocal
cd /d "%~dp0\.."
if not exist venv\Scripts\python.exe (
    echo [ERROR] venv not found. Run install_windows.bat first.
    exit /b 1
)
for /f %%v in ('venv\Scripts\python -c "from version import VERSION; print(VERSION)"') do set VERSION=%%v
if "%VERSION%"=="" (
    echo [ERROR] Could not read the version from version.py.
    exit /b 1
)
echo Building DynaMix %VERSION% ...
venv\Scripts\python -m pip install --upgrade pyinstaller || exit /b 1
venv\Scripts\python -m PyInstaller packaging\dynamix.spec --noconfirm --distpath dist --workpath build || exit /b 1
start "" /wait dist\DynaMix\DynaMix.exe --self-test dist\selftest.txt
set RESULT=%ERRORLEVEL%
type dist\selftest.txt
if not "%RESULT%"=="0" (
    echo [ERROR] The self-test of the build failed.
    exit /b 1
)

set ZIP=dist\DynaMix-%VERSION%-windows-x64.zip
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\DynaMix' -DestinationPath '%ZIP%'" || exit /b 1
echo Built: %ZIP%

REM Inno Setup: winget installs it per user, the classic installer in Program Files
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
    echo.
    echo [SKIP] Inno Setup not found: no installer built. To build one:
    echo        winget install JRSoftware.InnoSetup
    echo        then run this script again.
    echo Built: dist\DynaMix  - DynaMix.exe starts it.
    exit /b 0
)
"%ISCC%" /Q "/DAppVersion=%VERSION%" packaging\dynamix.iss || exit /b 1
echo.
echo Built: dist\DynaMix-%VERSION%-setup.exe  - the installer.
echo        %ZIP%  - the same build as a zip, for people who would rather not install.
exit /b 0
