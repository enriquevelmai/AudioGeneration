@echo off
REM ====================================================================
REM  podcast-tts - Arranca la interfaz web (Gradio) y abre el navegador.
REM  Argumentos extra se pasan a "podcast_tts ui" (p.ej. --port 7861).
REM ====================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"

if not exist ".venv\Scripts\python.exe" (
    echo No existe el entorno .venv. Ejecuta primero: bats\install.bat
    pause
    exit /b 1
)

echo Arrancando la UI de podcast-tts ^(por defecto http://127.0.0.1:7860^)...
echo Cierra esta ventana o pulsa Ctrl+C para pararla.
".venv\Scripts\python.exe" -m podcast_tts ui --inbrowser %*
if errorlevel 1 (
    echo.
    echo La UI termino con error ^(ver arriba^). Diagnostico: .venv\Scripts\python.exe scripts\check_env.py
    pause
    exit /b 1
)
endlocal
