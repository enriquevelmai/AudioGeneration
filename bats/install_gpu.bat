@echo off
REM ====================================================================
REM  podcast-tts - Switches PyTorch from CPU to CUDA (NVIDIA GPU) without
REM  reinstalling everything: uv only replaces torch/torchaudio (the rest stays).
REM
REM  Usage: bats\install_gpu.bat        bats\install_gpu.bat /y  (no pause)
REM         bats\install_gpu.bat /force (even if nvidia-smi is not detected)
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
set "FORCE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
for %%a in (%*) do (
    if /i "%%~a"=="/y" set "NONINTERACTIVE=1"
    if /i "%%~a"=="-y" set "NONINTERACTIVE=1"
    if /i "%%~a"=="/force" set "FORCE=1"
)

if not exist ".venv\Scripts\python.exe" (
    echo .venv does not exist. Run bats\install.bat first ^(it already detects the GPU^).
    goto fail
)
set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do if not defined UV set "UV=%%i"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV (
    echo ERROR: uv not found. Run bats\install.bat
    goto fail
)

REM --------------------------------------------------------------------
echo [1/3] Checking for an NVIDIA GPU...
where nvidia-smi >nul 2>nul
if errorlevel 1 (
    if "%FORCE%"=="1" (
        echo   nvidia-smi not found; continuing because of /force.
    ) else (
        echo ERROR: nvidia-smi not found. Install the NVIDIA driver ^(or use /force^).
        goto fail
    )
) else (
    for /f "delims=" %%g in ('nvidia-smi -L') do echo   %%g
)

REM --------------------------------------------------------------------
setlocal EnableDelayedExpansion
echo.
echo [2/3] Installing PyTorch CUDA 12.6 ^(replaces the CPU variant, ~2.5 GB^)...
set "EXTRAS=local"
if exist ".venv\podcast-tts-extras.txt" set /p EXTRAS=<".venv\podcast-tts-extras.txt"
set "NEW_EXTRAS="
for %%e in (!EXTRAS!) do (
    if /i not "%%e"=="cpu" if /i not "%%e"=="cuda" set "NEW_EXTRAS=!NEW_EXTRAS! %%e"
)
echo !NEW_EXTRAS! | findstr /i /c:"local" >nul
if errorlevel 1 set "NEW_EXTRAS=local!NEW_EXTRAS!"
set "NEW_EXTRAS=!NEW_EXTRAS! cuda"
echo !NEW_EXTRAS! | findstr /i /c:"desktop" >nul
if errorlevel 1 set "NEW_EXTRAS=!NEW_EXTRAS! desktop"
echo !NEW_EXTRAS! | findstr /i /c:"mcp" >nul
if errorlevel 1 set "NEW_EXTRAS=!NEW_EXTRAS! mcp"
for /f "tokens=*" %%x in ("!NEW_EXTRAS!") do set "NEW_EXTRAS=%%x"
set "EXTRA_ARGS="
for %%e in (!NEW_EXTRAS!) do set "EXTRA_ARGS=!EXTRA_ARGS! --extra %%e"
echo   Extras: !NEW_EXTRAS!
"%UV%" sync --locked --python 3.11 !EXTRA_ARGS!
if errorlevel 1 (
    echo ERROR in uv sync. Check the output above.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo !NEW_EXTRAS!
".venv\Scripts\python.exe" -I -S scripts\fix_editable_pth.py

REM --------------------------------------------------------------------
echo.
echo [3/3] Verifying...
".venv\Scripts\python.exe" scripts\check_env.py
if errorlevel 1 (
    echo WARNING: check_env.py found problems ^(see above^).
    goto fail
)
echo.
echo  Done: the engines will use the GPU. Open the app with bats\run.bat
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal & endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal & endlocal
exit /b 1
