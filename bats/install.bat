@echo off
REM ====================================================================
REM  podcast-tts - Instalacion (entorno aislado .venv gestionado por uv).
REM
REM  - Instala uv si falta (instalador oficial de astral, sin admin).
REM  - Instala Python 3.11 con uv (si no hay ya uno utilizable).
REM  - Detecta GPU NVIDIA (nvidia-smi) y elige torch CUDA o CPU.
REM  - Instala tambien la app de escritorio (extra desktop: pywebview)
REM    y el servidor MCP para asistentes de IA (extra mcp).
REM  - Ofrece descargar ya los modelos y, si usas Claude Code, la skill.
REM  - Crea accesos directos "AudioGeneration" (Escritorio y menu Inicio).
REM
REM  Uso:   bats\install.bat               (interactivo)
REM         bats\install.bat /y            (sin preguntas ni pause; responde si a todo,
REM                                         accesos directos incluidos)
REM         bats\install.bat /cpu          (fuerza torch CPU aunque haya GPU)
REM         bats\install.bat /cuda         (fuerza torch CUDA)
REM         bats\install.bat /noshortcuts  (no crea accesos directos)
REM         bats\install.bat /dev          (anade el extra dev: pytest, para desarrollo)
REM  Variables opcionales:
REM         PODCAST_TTS_NONINTERACTIVE=1   igual que /y
REM         PODCAST_TTS_VARIANT=cpu|cuda   fuerza la variante de torch
REM         PODCAST_TTS_DOWNLOAD_MODELS=0|1, PODCAST_TTS_INSTALL_SKILL=0|1
REM         PODCAST_TTS_SHORTCUTS=0|1      accesos directos (0 = no crearlos)
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
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
set "ROOT=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
REM Por si el .pth de la instalacion editable no se lee bien (rutas con acentos).
set "PYTHONPATH=%ROOT%\src"

set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
set "VARIANT=%PODCAST_TTS_VARIANT%"
set "WITH_DEV=0"
set "NOSHORTCUTS=0"
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/y" set "NONINTERACTIVE=1"
if /i "%~1"=="-y" set "NONINTERACTIVE=1"
if /i "%~1"=="/cpu" set "VARIANT=cpu"
if /i "%~1"=="/cuda" set "VARIANT=cuda"
if /i "%~1"=="/dev" set "WITH_DEV=1"
if /i "%~1"=="/noshortcuts" set "NOSHORTCUTS=1"
shift
goto parse_args
:args_done

echo ====================================================================
echo  podcast-tts - instalacion en "%ROOT%"
echo ====================================================================

REM --------------------------------------------------------------------
echo.
echo [1/8] Comprobando uv...
call :find_uv
if not defined UV (
    echo   uv no encontrado. Instalando uv ^(local, sin admin^)...
    powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    call :find_uv
)
if not defined UV (
    echo ERROR: no se pudo instalar uv. Instalalo a mano: https://docs.astral.sh/uv/
    goto fail
)
echo   uv: %UV%

REM --------------------------------------------------------------------
echo.
echo [2/8] Python 3.11 ^(gestionado por uv^)...
"%UV%" python find 3.11 >nul 2>nul
if not errorlevel 1 (
    echo   Ya hay un Python 3.11 utilizable.
    goto python_done
)
echo   Descargando Python 3.11 ^(unos 30 MB^)...
set "UVPY_LOG=%TEMP%\podcast-tts-uv-python.log"
"%UV%" python install 3.11 >"%UVPY_LOG%" 2>&1
set "UVPY_ERR=%errorlevel%"
"%UV%" python find 3.11 >nul 2>nul
if errorlevel 1 (
    type "%UVPY_LOG%"
    echo ERROR instalando Python 3.11 con uv ^(ver arriba^).
    goto fail
)
REM uv puede avisar "Missing expected target directory for Python minor version link"
REM aunque Python quede instalado y funcione: no se muestra para no asustar.
if not "%UVPY_ERR%"=="0" echo   Python 3.11 instalado ^(uv aviso de un detalle menor sin importancia^).
if "%UVPY_ERR%"=="0" echo   Python 3.11 instalado.
:python_done

REM --------------------------------------------------------------------
echo.
echo [3/8] Comprobando GPU NVIDIA...
if defined VARIANT (
    echo   Variante forzada: %VARIANT%
) else (
    call :detect_gpu
)
if /i not "%VARIANT%"=="cuda" if /i not "%VARIANT%"=="cpu" (
    echo ERROR: variante desconocida "%VARIANT%" ^(usa cpu o cuda^).
    goto fail
)
if /i "%VARIANT%"=="cuda" (
    echo   Se instalara PyTorch con CUDA 12.6 ^(~2.5 GB^).
) else (
    echo   Se instalara PyTorch para CPU: funciona, pero la sintesis sera MUY lenta.
)

REM --------------------------------------------------------------------
set "EXTRAS=local %VARIANT% desktop mcp"
if "%WITH_DEV%"=="1" set "EXTRAS=local %VARIANT% desktop mcp dev"
set "EXTRA_ARGS=--extra local --extra %VARIANT% --extra desktop --extra mcp"
if "%WITH_DEV%"=="1" set "EXTRA_ARGS=%EXTRA_ARGS% --extra dev"
echo.
echo [4/8] Creando .venv e instalando dependencias ^(%EXTRAS%^)...
echo   La primera vez descarga varios GB; las siguientes usa la cache de uv.
"%UV%" sync --locked --python 3.11 %EXTRA_ARGS%
if errorlevel 1 (
    echo ERROR en uv sync. Revisa la salida de arriba.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo %EXTRAS%
echo   Extras registrados en .venv\podcast-tts-extras.txt: %EXTRAS%
".venv\Scripts\python.exe" -I -S scripts\fix_editable_pth.py

REM --------------------------------------------------------------------
echo.
echo [5/8] Comprobando ffmpeg y el entorno...
call :ensure_ffmpeg
".venv\Scripts\python.exe" scripts\check_env.py
if errorlevel 1 (
    echo AVISO: check_env.py ha detectado problemas ^(ver arriba^).
    set "ENV_PROBLEMS=1"
)

REM --------------------------------------------------------------------
echo.
echo [6/8] Modelos ^(F5-TTS, F5-Spanish, Vocos, XTTS v2: ~4.5 GB^)...
echo   Se descargan solos la primera vez que se usan; puedes bajarlos ya.
echo   Licencias: F5 y F5-Spanish CC-BY-NC-4.0, XTTS v2 CPML ^(uso NO comercial^).
set "DO_MODELS=%PODCAST_TTS_DOWNLOAD_MODELS%"
if not defined DO_MODELS call :ask "Descargar ahora los modelos" DO_MODELS
if "%DO_MODELS%"=="1" (
    ".venv\Scripts\python.exe" -m podcast_tts models download all
    if errorlevel 1 echo AVISO: alguna descarga fallo; reintenta con: bats\update.bat
) else (
    echo   Omitido. Mas tarde: .venv\Scripts\python.exe -m podcast_tts models download
)

REM --------------------------------------------------------------------
echo.
echo [7/8] Skill de Claude Code...
if not exist "%USERPROFILE%\.claude\" (
    echo   No se encuentra la carpeta .claude del usuario: Claude Code no parece instalado. Omitido.
    goto skill_done
)
set "DO_SKILL=%PODCAST_TTS_INSTALL_SKILL%"
if not defined DO_SKILL call :ask "Instalar la skill podcast-tts en Claude Code" DO_SKILL
if "%DO_SKILL%"=="1" (
    if "%NONINTERACTIVE%"=="1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -NoReplace
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_skill.ps1
    )
    if errorlevel 1 echo AVISO: no se pudo instalar la skill ^(ver arriba^).
) else (
    echo   Omitido. Mas tarde: powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1
)
:skill_done

REM --------------------------------------------------------------------
echo.
echo [8/8] Accesos directos "AudioGeneration" ^(Escritorio y menu Inicio^)...
set "DO_SHORTCUTS=%PODCAST_TTS_SHORTCUTS%"
if "%NOSHORTCUTS%"=="1" set "DO_SHORTCUTS=0"
if not defined DO_SHORTCUTS call :ask "Crear accesos directos en el Escritorio y en el menu Inicio" DO_SHORTCUTS
if "%DO_SHORTCUTS%"=="1" (
    call "%ROOT%\bats\create_shortcuts.bat" /y
    if errorlevel 1 echo AVISO: no se pudieron crear los accesos directos ^(ver arriba^).
) else (
    echo   Omitido. Mas tarde: bats\create_shortcuts.bat
)

echo.
echo ====================================================================
if defined ENV_PROBLEMS echo  Instalado con avisos: revisa los [FAIL] de check_env.py.
if not defined ENV_PROBLEMS echo  Listo.
if exist "AudioGeneration.exe" (
    echo  Abrir la app:      AudioGeneration.exe ^(o el acceso directo AudioGeneration^)
) else (
    echo  Abrir la app:      bats\run.bat ^(o el acceso directo AudioGeneration^)
)
echo  En el navegador:   bats\run_web.bat
echo  Actualizar:        bats\update.bat
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
popd
if defined ENV_PROBLEMS (
    endlocal
    exit /b 2
)
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal
exit /b 1

REM ====================================================================
REM  Subrutinas
REM ====================================================================
:find_uv
set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do if not defined UV set "UV=%%i"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
exit /b 0

:detect_gpu
set "VARIANT=cpu"
where nvidia-smi >nul 2>nul
if errorlevel 1 (
    echo   Sin nvidia-smi: no hay GPU NVIDIA ^(o falta el driver^).
    exit /b 0
)
nvidia-smi -L >nul 2>nul
if errorlevel 1 (
    echo   nvidia-smi no responde: se usara CPU. Actualiza el driver NVIDIA si tienes GPU.
    exit /b 0
)
set "VARIANT=cuda"
for /f "delims=" %%g in ('nvidia-smi -L') do echo   %%g
exit /b 0

:ensure_ffmpeg
where ffmpeg >nul 2>nul
if not errorlevel 1 exit /b 0
echo   ffmpeg no esta en el PATH ^(necesario para leer/escribir MP3^).
where winget >nul 2>nul
if errorlevel 1 (
    echo   Instalalo a mano ^(p.ej. https://www.gyan.dev/ffmpeg/builds/^) y anadelo al PATH.
    exit /b 0
)
set "DO_FFMPEG="
call :ask "Instalar ffmpeg con winget (Gyan.FFmpeg, sin admin)" DO_FFMPEG
if not "%DO_FFMPEG%"=="1" exit /b 0
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where ffmpeg >nul 2>nul
if errorlevel 1 echo   Abre una consola nueva para que ffmpeg aparezca en el PATH.
exit /b 0

REM  :ask "pregunta" VARIABLE  -> VARIABLE=1 (si) o 0 (no). En modo /y responde si.
:ask
if "%NONINTERACTIVE%"=="1" (
    set "%~2=1"
    exit /b 0
)
set "ANSWER="
set /p "ANSWER=  %~1? [S/n] "
if /i "%ANSWER%"=="n" (set "%~2=0") else if /i "%ANSWER%"=="no" (set "%~2=0") else (set "%~2=1")
exit /b 0
