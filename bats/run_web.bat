@echo off
REM ====================================================================
REM  podcast-tts - Arranca la interfaz web (Gradio) y abre el navegador.
REM  Para la app de escritorio (ventana propia) usa bats\run.bat.
REM  Argumentos extra se pasan a "podcast_tts ui" (p.ej. --port 7861).
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

if not exist ".venv\Scripts\python.exe" (
    echo No existe el entorno .venv. Ejecuta primero: bats\install.bat
    popd
    pause
    exit /b 1
)

echo Arrancando la UI de podcast-tts en el navegador ^(por defecto http://127.0.0.1:7860^)...
echo Cierra esta ventana o pulsa Ctrl+C para pararla.
".venv\Scripts\python.exe" -m podcast_tts ui --inbrowser %*
if errorlevel 1 (
    echo.
    echo La UI termino con error ^(ver arriba^). Diagnostico: .venv\Scripts\python.exe scripts\check_env.py
    popd
    pause
    exit /b 1
)
popd
endlocal
