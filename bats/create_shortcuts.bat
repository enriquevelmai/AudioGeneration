@echo off
REM ====================================================================
REM  AudioGeneration - Creates the "AudioGeneration" shortcuts on the
REM  user's Desktop and Start menu (no admin).
REM
REM  They point to AudioGeneration.exe if it exists (bats\build_launcher.bat)
REM  and otherwise to bats\run.bat. They use the assets\icon.ico icon.
REM
REM  Usage: bats\create_shortcuts.bat                  (real Desktop and Start menu)
REM         bats\create_shortcuts.bat C:\path\tests     (creates "Desktop" and "Start Menu"
REM                                                     inside that folder; for testing)
REM         bats\create_shortcuts.bat /y [folder]      (no pause)
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
set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
set "DEST="
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/y" (
    set "NONINTERACTIVE=1"
) else if /i "%~1"=="-y" (
    set "NONINTERACTIVE=1"
) else (
    set "DEST=%~f1"
)
shift
goto parse_args
:args_done

echo Creating AudioGeneration shortcuts...
if defined DEST (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\create_shortcuts.ps1" -Root "%CD%" -Dest "%DEST%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\create_shortcuts.ps1" -Root "%CD%"
)
if errorlevel 1 (
    echo ERROR: could not create the shortcuts ^(see above^).
    if not "%NONINTERACTIVE%"=="1" pause
    popd
    endlocal
    exit /b 1
)
if not exist "AudioGeneration.exe" (
    echo   Note: they point to bats\run.bat. Once you build the launcher ^(bats\build_launcher.bat^),
    echo         run this script again so they point to AudioGeneration.exe.
)
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal
exit /b 0
