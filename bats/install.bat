@echo off
REM ====================================================================
REM  podcast-tts - Instalacion (entorno aislado .venv gestionado por uv).
REM
REM  - Instala uv si falta (instalador oficial de astral, sin admin).
REM  - Instala Python 3.11 con uv.
REM  - Detecta GPU NVIDIA (nvidia-smi) y elige torch CUDA o CPU.
REM  - Instala tambien la app de escritorio (extra desktop: pywebview).
REM  - Ofrece descargar ya los modelos y, si usas Claude Code, la skill.
REM  - Ofrece crear accesos directos "AudioGeneration" (Escritorio y menu Inicio).
REM
REM  Uso:   bats\install.bat            (interactivo)
REM         bats\install.bat /y         (sin preguntas ni pause; responde si)
REM         bats\install.bat /cpu       (fuerza torch CPU aunque haya GPU)
REM         bats\install.bat /cuda      (fuerza torch CUDA)
REM  Variables opcionales:
REM         PODCAST_TTS_NONINTERACTIVE=1   igual que /y
REM         PODCAST_TTS_VARIANT=cpu|cuda   fuerza la variante de torch
REM         PODCAST_TTS_DOWNLOAD_MODELS=0|1, PODCAST_TTS_INSTALL_SKILL=0|1
REM         PODCAST_TTS_SHORTCUTS=0|1      accesos directos (en modo /y solo si vale 1)
REM ====================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"

set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
set "VARIANT=%PODCAST_TTS_VARIANT%"
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/y" set "NONINTERACTIVE=1"
if /i "%~1"=="-y" set "NONINTERACTIVE=1"
if /i "%~1"=="/cpu" set "VARIANT=cpu"
if /i "%~1"=="/cuda" set "VARIANT=cuda"
shift
goto parse_args
:args_done

echo ====================================================================
echo  podcast-tts - instalacion en %ROOT%
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
echo [2/8] Instalando Python 3.11 ^(gestionado por uv^)...
"%UV%" python install 3.11
if errorlevel 1 (
    REM Puede fallar solo el enlace de version menor aunque Python ya este instalado:
    REM si uv encuentra un 3.11 utilizable, se sigue adelante.
    "%UV%" python find 3.11 >nul 2>nul
    if errorlevel 1 (
        echo ERROR instalando Python 3.11 con uv.
        goto fail
    )
    echo   AVISO: uv python install devolvio error, pero hay un Python 3.11 utilizable. Se continua.
)

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
echo.
echo [4/8] Creando .venv e instalando dependencias ^(local + %VARIANT% + desktop^)...
echo   La primera vez descarga varios GB; las siguientes usa la cache de uv.
"%UV%" sync --locked --python 3.11 --extra local --extra %VARIANT% --extra desktop --extra dev
if errorlevel 1 (
    echo ERROR en uv sync. Revisa la salida de arriba.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo local %VARIANT% desktop dev
echo   Extras registrados en .venv\podcast-tts-extras.txt: local %VARIANT% desktop dev

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
    echo   No se encuentra %USERPROFILE%\.claude: Claude Code no parece instalado. Omitido.
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
if not defined DO_SHORTCUTS if "%NONINTERACTIVE%"=="1" set "DO_SHORTCUTS=0"
if not defined DO_SHORTCUTS call :ask "Crear accesos directos en el Escritorio y en el menu Inicio" DO_SHORTCUTS
if "%DO_SHORTCUTS%"=="1" (
    call "%~dp0create_shortcuts.bat" /y
    if errorlevel 1 echo AVISO: no se pudieron crear los accesos directos ^(ver arriba^).
) else (
    echo   Omitido. Mas tarde: bats\create_shortcuts.bat
)

echo.
echo ====================================================================
if defined ENV_PROBLEMS (
    echo  Instalado con avisos: revisa los [FAIL] de check_env.py.
) else (
    echo  Listo. App de escritorio:        bats\run.bat
)
echo  En el navegador:                 bats\run_web.bat
echo  Lanzador AudioGeneration.exe:    bats\build_launcher.bat
echo  Actualizar:                      bats\update.bat
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
if defined ENV_PROBLEMS (
    endlocal
    exit /b 2
)
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
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
