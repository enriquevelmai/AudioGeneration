@echo off
REM ====================================================================
REM  AudioGeneration - Builds launcher.py into AudioGeneration.exe
REM  (PyInstaller --onefile --windowed, run with uvx: PyInstaller is
REM  NOT part of the project dependencies nor of the .venv).
REM
REM  Result: AudioGeneration.exe in the repo root (not versioned).
REM  The exe does NOT bundle the app (nor torch): it looks for .venv\ next to it,
REM  offers to install/update and launches "pythonw -m podcast_tts desktop".
REM  That is why it has to live in the project folder; to have it at
REM  hand, use shortcuts (bats\create_shortcuts.bat).
REM
REM  Usage: bats\build_launcher.bat        bats\build_launcher.bat /y   (no pause)
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0.." 2>nul || (
    echo ERROR: cannot open the project folder: "%~dp0.."
    echo   If it is on a network path ^(\\server\folder^), copy it to a local disk.
    if /i not "%~1"=="/y" pause
    exit /b 1
)
if not exist "pyproject.toml" (
    echo ERROR: pyproject.toml not found in "%CD%".
    echo   - If you opened the zip without extracting it, extract all its contents first
    echo     ^(right-click the zip ^> Extract All^) and run the .bat from there.
    echo   - If the folder is on a network path ^(\\server\folder^), copy it to a local disk.
    popd
    if /i not "%~1"=="/y" pause
    exit /b 1
)
REM The user's PYTHONPATH could sneak unrelated modules into the exe.
set "PYTHONPATH="
set "PYTHONHOME="
set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
if /i "%~1"=="/y" set "NONINTERACTIVE=1"
if /i "%~1"=="-y" set "NONINTERACTIVE=1"

set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do if not defined UV set "UV=%%i"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV (
    echo ERROR: uv not found. Run bats\install.bat first
    goto fail
)
if not exist "assets\icon.ico" (
    echo ERROR: assets\icon.ico is missing. Generate it with:
    echo        uv run --no-project --with pillow python scripts\make_icon.py
    goto fail
)

REM If the app is open from the exe, PyInstaller cannot overwrite it.
if exist "AudioGeneration.exe" (
    del /q "AudioGeneration.exe" >nul 2>nul
    if exist "AudioGeneration.exe" (
        echo ERROR: AudioGeneration.exe is in use. Close the launcher and try again.
        goto fail
    )
)

echo [1/1] Building launcher.py with PyInstaller ^(uvx; downloads it the first time^)...
"%UV%" tool run --python 3.11 --from pyinstaller pyinstaller --noconfirm --clean ^
  --onefile --windowed ^
  --name AudioGeneration ^
  --icon "%CD%\assets\icon.ico" ^
  --distpath "%CD%" ^
  --workpath "%CD%\build\launcher" ^
  --specpath "%CD%\build\launcher" ^
  launcher.py
if errorlevel 1 (
    echo ERROR building the launcher ^(see above^).
    goto fail
)
if not exist "AudioGeneration.exe" (
    echo ERROR: PyInstaller did not produce AudioGeneration.exe.
    goto fail
)

for %%f in ("AudioGeneration.exe") do set "EXE_SIZE=%%~zf"
echo.
echo ====================================================================
echo  Done: AudioGeneration.exe ^(%EXE_SIZE% bytes^) in the repo root.
echo  Shortcuts on the Desktop and in the Start menu:
echo      bats\create_shortcuts.bat
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal
exit /b 1
