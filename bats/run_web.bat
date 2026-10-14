@echo off
REM ====================================================================
REM  podcast-tts - Starts the web interface (Gradio) and opens the browser.
REM  For the desktop app (its own window) use bats\run.bat.
REM  Extra arguments are passed to "podcast_tts ui" (e.g. --port 7861).
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0.." 2>nul || (
    echo ERROR: cannot open the project folder: "%~dp0.."
    echo   If it is on a network path ^(\\server\folder^), copy it to a local disk.
    pause
    exit /b 1
)
if not exist "pyproject.toml" (
    echo ERROR: pyproject.toml not found in "%CD%".
    echo   - If you opened the zip without extracting it, extract all its contents first
    echo     ^(right-click the zip ^> Extract All^) and run the .bat from there.
    echo   - If the folder is on a network path ^(\\server\folder^), copy it to a local disk.
    popd
    pause
    exit /b 1
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
REM In case the editable install .pth is not read correctly (paths with accents).
set "PYTHONPATH=%CD%\src"

if not exist ".venv\Scripts\python.exe" (
    echo The .venv environment does not exist. Run first: bats\install.bat
    popd
    pause
    exit /b 1
)

echo Starting the podcast-tts UI in the browser ^(default http://127.0.0.1:7860^)...
echo Close this window or press Ctrl+C to stop it.
".venv\Scripts\python.exe" -m podcast_tts ui --inbrowser %*
if errorlevel 1 (
    echo.
    echo The UI exited with an error ^(see above^). Diagnostics: .venv\Scripts\python.exe scripts\check_env.py
    popd
    pause
    exit /b 1
)
popd
endlocal
