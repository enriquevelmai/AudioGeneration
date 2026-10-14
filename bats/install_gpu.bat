@echo off
REM ====================================================================
REM  podcast-tts - Cambia PyTorch de CPU a CUDA (GPU NVIDIA) sin reinstalar
REM  todo: uv solo sustituye torch/torchaudio (el resto queda igual).
REM
REM  Uso:   bats\install_gpu.bat        bats\install_gpu.bat /y  (sin pause)
REM         bats\install_gpu.bat /force (aunque no se detecte nvidia-smi)
REM ====================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
set "NONINTERACTIVE=0"
set "FORCE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
for %%a in (%*) do (
    if /i "%%~a"=="/y" set "NONINTERACTIVE=1"
    if /i "%%~a"=="-y" set "NONINTERACTIVE=1"
    if /i "%%~a"=="/force" set "FORCE=1"
)

if not exist ".venv\Scripts\python.exe" (
    echo No existe .venv. Ejecuta primero bats\install.bat ^(ya detecta la GPU^).
    goto fail
)
set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do if not defined UV set "UV=%%i"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV (
    echo ERROR: uv no encontrado. Ejecuta bats\install.bat
    goto fail
)

REM --------------------------------------------------------------------
echo [1/3] Comprobando GPU NVIDIA...
where nvidia-smi >nul 2>nul
if errorlevel 1 (
    if "%FORCE%"=="1" (
        echo   nvidia-smi no encontrado; se continua por /force.
    ) else (
        echo ERROR: no se encuentra nvidia-smi. Instala el driver NVIDIA ^(o usa /force^).
        goto fail
    )
) else (
    for /f "delims=" %%g in ('nvidia-smi -L') do echo   %%g
)

REM --------------------------------------------------------------------
echo.
echo [2/3] Instalando PyTorch CUDA 12.6 ^(sustituye a la variante CPU, ~2.5 GB^)...
set "EXTRAS=local dev"
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
for /f "tokens=*" %%x in ("!NEW_EXTRAS!") do set "NEW_EXTRAS=%%x"
set "EXTRA_ARGS="
for %%e in (!NEW_EXTRAS!) do set "EXTRA_ARGS=!EXTRA_ARGS! --extra %%e"
echo   Extras: !NEW_EXTRAS!
"%UV%" sync --locked --python 3.11 !EXTRA_ARGS!
if errorlevel 1 (
    echo ERROR en uv sync. Revisa la salida de arriba.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo !NEW_EXTRAS!

REM --------------------------------------------------------------------
echo.
echo [3/3] Verificando...
".venv\Scripts\python.exe" scripts\check_env.py
if errorlevel 1 (
    echo AVISO: check_env.py ha detectado problemas ^(ver arriba^).
    goto fail
)
echo.
echo  Listo: los motores usaran la GPU. Abre la app con bats\run.bat
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 1
