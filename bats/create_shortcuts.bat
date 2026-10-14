@echo off
REM ====================================================================
REM  AudioGeneration - Crea los accesos directos "AudioGeneration" en el
REM  Escritorio y en el menu Inicio del usuario (sin admin).
REM
REM  Apuntan a AudioGeneration.exe si existe (bats\build_launcher.bat) y,
REM  si no, a bats\run.bat. Usan el icono assets\icon.ico.
REM
REM  Uso:   bats\create_shortcuts.bat                 (Escritorio y menu Inicio reales)
REM         bats\create_shortcuts.bat C:\ruta\pruebas  (crea "Escritorio" y "Menu Inicio"
REM                                                     dentro de esa carpeta; para pruebas)
REM         bats\create_shortcuts.bat /y [carpeta]     (sin pause)
REM ====================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
set "DEST="
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/y" (
    set "NONINTERACTIVE=1"
) else if /i "%~1"=="-y" (
    set "NONINTERACTIVE=1"
) else (
    set "DEST=%~f1"
)
shift
goto parse_args
:args_done

echo Creando accesos directos de AudioGeneration...
if defined DEST (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\create_shortcuts.ps1" -Root "%CD%" -Dest "%DEST%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\create_shortcuts.ps1" -Root "%CD%"
)
if errorlevel 1 (
    echo ERROR: no se pudieron crear los accesos directos ^(ver arriba^).
    if not "%NONINTERACTIVE%"=="1" pause
    endlocal
    exit /b 1
)
if not exist "AudioGeneration.exe" (
    echo   Nota: apuntan a bats\run.bat. Con el lanzador ^(bats\build_launcher.bat^) vuelve a
    echo         ejecutar este script para que apunten a AudioGeneration.exe.
)
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 0
