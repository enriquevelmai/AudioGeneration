@echo off
REM ====================================================================
REM  podcast-tts - Update.
REM
REM  1. git pull (only if it is a git clone with a remote).
REM  2. uv sync with the same extras that were installed
REM     (.venv\podcast-tts-extras.txt, written by install.bat).
REM  3. Updates the models already downloaded (podcast-tts models update).
REM
REM  Usage: bats\update.bat         bats\update.bat /y   (no pause)
REM  Exit code: 0 ok, 1 error (uv, environment...), 3 git pull failed
REM  (e.g. local changes); in that case the dependencies of the current
REM  version are synchronized anyway.
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
REM The cd goes BEFORE enabling delayed expansion: with it, any "!" in the path is lost.
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
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
set "PYTHONPATH=%CD%\src"
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

REM --------------------------------------------------------------------
echo [1/3] Updating the code...
set "PULL_FAILED="
set "HAS_REMOTE="
if not exist ".git" (
    echo   Not a git clone: skipped ^(download the new version manually^).
    goto pull_done
)
where git >nul 2>nul
if errorlevel 1 (
    echo   git is not installed: skipped.
    goto pull_done
)
for /f "delims=" %%r in ('git remote 2^>nul') do set "HAS_REMOTE=1"
if not defined HAS_REMOTE (
    echo   Repository without a remote: skipped.
    goto pull_done
)
git pull --ff-only
if not errorlevel 1 goto pull_done
set "PULL_FAILED=1"
set "LOCAL_CHANGES="
for /f "delims=" %%c in ('git status --porcelain --untracked-files=no 2^>nul') do set "LOCAL_CHANGES=1"
echo.
echo   ERROR: git pull failed and the code has NOT been updated.
if defined LOCAL_CHANGES (
    echo   You have local changes in project files. Set them aside and discard them
    echo   ^(git stash^) or commit them, and run bats\update.bat again.
) else (
    echo   Your branch and the server's have diverged or there is no connection. Check: git status
)
echo   The dependencies of the current version are synchronized anyway.
:pull_done

REM --------------------------------------------------------------------
setlocal EnableDelayedExpansion
echo.
echo [2/3] Synchronizing dependencies...
set "EXTRAS="
if exist ".venv\podcast-tts-extras.txt" (
    set /p EXTRAS=<".venv\podcast-tts-extras.txt"
) else (
    echo   No .venv\podcast-tts-extras.txt: deducing it from the GPU.
    set "EXTRAS=local cpu desktop mcp"
    where nvidia-smi >nul 2>nul
    if not errorlevel 1 set "EXTRAS=local cuda desktop mcp"
)
REM The desktop app (desktop extra) is always included, also for older installations.
echo !EXTRAS! | findstr /i /c:"desktop" >nul
if errorlevel 1 set "EXTRAS=!EXTRAS! desktop"
echo !EXTRAS! | findstr /i /c:"mcp" >nul
if errorlevel 1 set "EXTRAS=!EXTRAS! mcp"
set "EXTRA_ARGS="
for %%e in (!EXTRAS!) do set "EXTRA_ARGS=!EXTRA_ARGS! --extra %%e"
echo   Extras: !EXTRAS!
"%UV%" sync --locked --python 3.11 !EXTRA_ARGS!
if errorlevel 1 (
    echo ERROR in uv sync. Check the output above.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo !EXTRAS!
".venv\Scripts\python.exe" -I -S scripts\fix_editable_pth.py

REM --------------------------------------------------------------------
echo.
echo [3/3] Updating downloaded models...
echo !EXTRAS! | findstr /i /c:"local" >nul
if errorlevel 1 (
    echo   Without the local extra there are no models to update.
) else (
    ".venv\Scripts\python.exe" -m podcast_tts models update
    if errorlevel 1 echo   WARNING: not all models could be updated ^(see above^).
)

echo.
echo ====================================================================
if defined PULL_FAILED (
    echo  The code has NOT been updated ^(git pull failed, see above^).
) else (
    echo  Updated. Desktop app: bats\run.bat   ^(browser: bats\run_web.bat^)
)
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
popd
if defined PULL_FAILED (
    endlocal & endlocal
    exit /b 3
)
endlocal & endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal & endlocal
exit /b 1
