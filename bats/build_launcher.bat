@echo off
REM ====================================================================
REM  AudioGeneration - Compila launcher.py a AudioGeneration.exe
REM  (PyInstaller --onefile --windowed, ejecutado con uvx: PyInstaller
REM  NO entra en las dependencias del proyecto ni en el .venv).
REM
REM  Resultado: AudioGeneration.exe en la raiz del repo (no se versiona).
REM  El exe NO lleva la app dentro (ni torch): busca .venv\ junto a el,
REM  ofrece instalar/actualizar y lanza "pythonw -m podcast_tts desktop".
REM  Por eso tiene que vivir en la carpeta del proyecto; para tenerlo a
REM  mano usa accesos directos (bats\create_shortcuts.bat).
REM
REM  Uso:   bats\build_launcher.bat        bats\build_launcher.bat /y   (sin pause)
REM ====================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
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
if not exist "assets\icon.ico" (
    echo ERROR: falta assets\icon.ico. Generalo con:
    echo        uv run --no-project --with pillow python scripts\make_icon.py
    goto fail
)

REM Si la app esta abierta desde el exe, PyInstaller no puede sobrescribirlo.
if exist "AudioGeneration.exe" (
    del /q "AudioGeneration.exe" >nul 2>nul
    if exist "AudioGeneration.exe" (
        echo ERROR: AudioGeneration.exe esta en uso. Cierra el lanzador y vuelve a intentarlo.
        goto fail
    )
)

echo [1/1] Compilando launcher.py con PyInstaller ^(uvx; la primera vez lo descarga^)...
"%UV%" tool run --python 3.11 --from pyinstaller pyinstaller --noconfirm --clean ^
  --onefile --windowed ^
  --name AudioGeneration ^
  --icon "%CD%\assets\icon.ico" ^
  --distpath "%CD%" ^
  --workpath "%CD%\build\launcher" ^
  --specpath "%CD%\build\launcher" ^
  launcher.py
if errorlevel 1 (
    echo ERROR compilando el launcher ^(ver arriba^).
    goto fail
)
if not exist "AudioGeneration.exe" (
    echo ERROR: PyInstaller no genero AudioGeneration.exe.
    goto fail
)

for %%f in ("AudioGeneration.exe") do set "EXE_SIZE=%%~zf"
echo.
echo ====================================================================
echo  Listo: AudioGeneration.exe ^(%EXE_SIZE% bytes^) en la raiz del repo.
echo  Accesos directos en el Escritorio y el menu Inicio:
echo      bats\create_shortcuts.bat
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 1
