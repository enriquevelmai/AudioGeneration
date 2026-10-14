@echo off
REM ====================================================================
REM  podcast-tts - Abre AudioGeneration como app de escritorio (ventana
REM  propia con WebView2, sin navegador ni consola).
REM
REM  Si falta pywebview (extra "desktop") abre la UI en el navegador
REM  (bats\run_web.bat). Si la app ya esta abierta, la trae al frente.
REM
REM  Uso:   bats\run.bat              (ventana de escritorio, sin consola)
REM         bats\run.bat /console     (igual, pero el registro sale en esta consola)
REM  Argumentos extra se pasan a "podcast_tts desktop" (p.ej. --debug).
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0.." 2>nul || (
    echo ERROR: no se puede abrir la carpeta del proyecto: "%~dp0.."
    echo   Si esta en una ruta de red ^(\\servidor\carpeta^), copiala a un disco local.
    pause
    exit /b 1
)
if not exist "pyproject.toml" (
    echo ERROR: no se encuentra pyproject.toml en "%CD%".
    echo   - Si has abierto el zip sin extraerlo, extrae antes todo su contenido
    echo     ^(clic derecho sobre el zip ^> Extraer todo^) y ejecuta el .bat desde ahi.
    echo   - Si la carpeta esta en una ruta de red ^(\\servidor\carpeta^), copiala a un disco local.
    popd
    pause
    exit /b 1
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
REM Por si el .pth de la instalacion editable no se lee bien (rutas con acentos).
set "PYTHONPATH=%CD%\src"

set "CONSOLE=0"
if /i "%~1"=="/console" (
    set "CONSOLE=1"
    shift
)

if not exist ".venv\Scripts\python.exe" (
    echo No existe el entorno .venv. Ejecuta primero: bats\install.bat
    popd
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo AVISO: falta pywebview ^(extra "desktop"^): se abre la UI en el navegador.
    echo        Para la app de escritorio: bats\update.bat  ^(o bats\install.bat^)
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
    echo Abriendo AudioGeneration ^(registro en esta consola; cierra la ventana de la app para salir^)...
    ".venv\Scripts\python.exe" -m podcast_tts desktop%ARGS%
    if errorlevel 1 (
        echo.
        echo La app termino con error ^(ver arriba^). Diagnostico: .venv\Scripts\python.exe scripts\check_env.py
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
