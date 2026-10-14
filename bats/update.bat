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
REM  Codigo de salida: 0 bien, 1 error (uv, entorno...), 3 fallo git pull
REM  (p.ej. cambios locales); en ese caso se sincronizan igualmente las
REM  dependencias de la version actual.
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
REM El cd va ANTES de habilitar la expansion retardada: con ella, los "!" de la ruta se pierden.
pushd "%~dp0.." 2>nul || (
    echo ERROR: no se puede abrir la carpeta del proyecto: "%~dp0.."
    echo   Si esta en una ruta de red ^(\\servidor\carpeta^), copiala a un disco local.
    if /i not "%~1"=="/y" pause
    exit /b 1
)
if not exist "pyproject.toml" (
    echo ERROR: no se encuentra pyproject.toml en "%CD%".
    echo   - Si has abierto el zip sin extraerlo, extrae antes todo su contenido
    echo     ^(clic derecho sobre el zip ^> Extraer todo^) y ejecuta el .bat desde ahi.
    echo   - Si la carpeta esta en una ruta de red ^(\\servidor\carpeta^), copiala a un disco local.
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
    echo ERROR: uv no encontrado. Ejecuta primero bats\install.bat
    goto fail
)

REM --------------------------------------------------------------------
echo [1/3] Actualizando el codigo...
set "PULL_FAILED="
set "HAS_REMOTE="
if not exist ".git" (
    echo   No es un clon de git: se omite ^(descarga la nueva version a mano^).
    goto pull_done
)
where git >nul 2>nul
if errorlevel 1 (
    echo   git no esta instalado: se omite.
    goto pull_done
)
for /f "delims=" %%r in ('git remote 2^>nul') do set "HAS_REMOTE=1"
if not defined HAS_REMOTE (
    echo   Repositorio sin remoto: se omite.
    goto pull_done
)
git pull --ff-only
if not errorlevel 1 goto pull_done
set "PULL_FAILED=1"
set "LOCAL_CHANGES="
for /f "delims=" %%c in ('git status --porcelain --untracked-files=no 2^>nul') do set "LOCAL_CHANGES=1"
echo.
echo   ERROR: git pull ha fallado y el codigo NO se ha actualizado.
if defined LOCAL_CHANGES (
    echo   Tienes cambios locales en ficheros del proyecto. Guardalos aparte y descartalos
    echo   ^(git stash^) o confirmalos, y vuelve a ejecutar bats\update.bat.
) else (
    echo   Tu rama y la del servidor han divergido o no hay conexion. Revisa: git status
)
echo   Se sincronizan igualmente las dependencias de la version actual.
:pull_done

REM --------------------------------------------------------------------
setlocal EnableDelayedExpansion
echo.
echo [2/3] Sincronizando dependencias...
set "EXTRAS="
if exist ".venv\podcast-tts-extras.txt" (
    set /p EXTRAS=<".venv\podcast-tts-extras.txt"
) else (
    echo   No hay .venv\podcast-tts-extras.txt: se deduce de la GPU.
    set "EXTRAS=local cpu desktop"
    where nvidia-smi >nul 2>nul
    if not errorlevel 1 set "EXTRAS=local cuda desktop"
)
REM La app de escritorio (extra desktop) va siempre, tambien en instalaciones anteriores.
echo !EXTRAS! | findstr /i /c:"desktop" >nul
if errorlevel 1 set "EXTRAS=!EXTRAS! desktop"
set "EXTRA_ARGS="
for %%e in (!EXTRAS!) do set "EXTRA_ARGS=!EXTRA_ARGS! --extra %%e"
echo   Extras: !EXTRAS!
"%UV%" sync --locked --python 3.11 !EXTRA_ARGS!
if errorlevel 1 (
    echo ERROR en uv sync. Revisa la salida de arriba.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo !EXTRAS!
".venv\Scripts\python.exe" -I -S scripts\fix_editable_pth.py

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
if defined PULL_FAILED (
    echo  El codigo NO se ha actualizado ^(git pull fallo, ver arriba^).
) else (
    echo  Actualizado. App de escritorio: bats\run.bat   ^(navegador: bats\run_web.bat^)
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
