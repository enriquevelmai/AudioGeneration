@echo off
REM ====================================================================
REM  podcast-tts - Opens AudioGeneration as a desktop app (its own
REM  WebView2 window, no browser or console).
REM
REM  If pywebview is missing ("desktop" extra) it opens the UI in the browser
REM  (bats\run_web.bat). If the app is already open, it brings it to the front.
REM
REM  Usage: bats\run.bat              (desktop window, no console)
REM         bats\run.bat /console     (same, but the log goes to this console)
REM  Extra arguments are passed to "podcast_tts desktop" (e.g. --debug).
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

set "CONSOLE=0"
if /i "%~1"=="/console" (
    set "CONSOLE=1"
    shift
)

if not exist ".venv\Scripts\python.exe" (
    echo The .venv environment does not exist. Run first: bats\install.bat
    popd
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo WARNING: pywebview is missing ^("desktop" extra^): opening the UI in the browser.
    echo          For the desktop app: bats\update.bat  ^(or bats\install.bat^)
    echo.
    popd
    endlocal
    call "%~dp0run_web.bat"
    exit /b %errorlevel%
)

set "ARGS="
:collect
if "%~1"=="" goto launch
set "ARGS=%ARGS% %1"
shift
goto collect

:launch
if "%CONSOLE%"=="1" (
    echo Opening AudioGeneration ^(log in this console; close the app window to exit^)...
    ".venv\Scripts\python.exe" -m podcast_tts desktop%ARGS%
    if errorlevel 1 (
        echo.
        echo The app exited with an error ^(see above^). Diagnostics: .venv\Scripts\python.exe scripts\check_env.py
        popd
        pause
        exit /b 1
    )
    popd
    endlocal
    exit /b 0
)

set "PYW=.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=.venv\Scripts\python.exe"
start "" "%PYW%" -m podcast_tts desktop%ARGS%
popd
endlocal
exit /b 0
