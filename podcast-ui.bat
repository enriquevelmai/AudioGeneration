@echo off
rem Arranca la UI de podcast-tts y abre el navegador.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set COQUI_TOS_AGREED=1
if not exist ".venv\Scripts\python.exe" (
  echo No existe .venv. Ejecuta primero: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  pause
  exit /b 1
)
echo Arrancando la UI en http://127.0.0.1:7860 ...
".venv\Scripts\python.exe" -m podcast_tts ui --inbrowser %*
pause
