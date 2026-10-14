@echo off
REM ====================================================================
REM  podcast-tts - Actualizacion.
REM
REM  1. git pull (solo si es un clon de git con remoto).
REM  2. uv sync con los mismos extras que se instalaron
REM     (.venv\podcast-tts-extras.txt, escrito por install.bat).
REM  3. Actualiza los modelos ya descargados (podcast-tts models update).
REM
REM  Uso:   bats\update.bat         bats\update.bat /y   (sin pause)
REM ====================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
if /i "%~1"=="/y" set "NONINTERACTIVE=1"
if /i "%~1"=="-y" set "NONINTERACTIVE=1"

set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do if not defined UV set "UV=%%i"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV (
    echo ERROR: uv no encontrado. Ejecuta primero bats\install.bat
    goto fail
)

REM --------------------------------------------------------------------
echo [1/3] Actualizando el codigo...
set "HAS_REMOTE="
if exist ".git" (
    where git >nul 2>nul
    if errorlevel 1 (
        echo   git no esta instalado: se omite.
    ) else (
        for /f "delims=" %%r in ('git remote 2^>nul') do set "HAS_REMOTE=1"
        if defined HAS_REMOTE (
            git pull --ff-only
            if errorlevel 1 echo   AVISO: git pull fallo ^(cambios locales o ramas divergentes^). Se continua.
        ) else (
            echo   Repositorio sin remoto: se omite.
        )
    )
) else (
    echo   No es un clon de git: se omite ^(descarga la nueva version a mano^).
)

REM --------------------------------------------------------------------
echo.
echo [2/3] Sincronizando dependencias...
set "EXTRAS="
if exist ".venv\podcast-tts-extras.txt" (
    set /p EXTRAS=<".venv\podcast-tts-extras.txt"
) else (
    echo   No hay .venv\podcast-tts-extras.txt: se deduce de la GPU.
    set "EXTRAS=local cpu dev"
    where nvidia-smi >nul 2>nul
    if not errorlevel 1 set "EXTRAS=local cuda dev"
)
set "EXTRA_ARGS="
for %%e in (!EXTRAS!) do set "EXTRA_ARGS=!EXTRA_ARGS! --extra %%e"
echo   Extras: !EXTRAS!
"%UV%" sync --locked --python 3.11 !EXTRA_ARGS!
if errorlevel 1 (
    echo ERROR en uv sync. Revisa la salida de arriba.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo !EXTRAS!

REM --------------------------------------------------------------------
echo.
echo [3/3] Actualizando modelos descargados...
echo !EXTRAS! | findstr /i /c:"local" >nul
if errorlevel 1 (
    echo   Sin el extra local no hay modelos que actualizar.
) else (
    ".venv\Scripts\python.exe" -m podcast_tts models update
    if errorlevel 1 echo   AVISO: no se pudieron actualizar todos los modelos ^(ver arriba^).
)

echo.
echo ====================================================================
echo  Actualizado. Para abrir la interfaz:  bats\run.bat
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 1
