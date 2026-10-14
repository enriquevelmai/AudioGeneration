@echo off
REM ====================================================================
REM  AudioGeneration - Empaqueta el zip de release para Windows.
REM
REM  Resultado: dist\AudioGeneration-v<version>-windows.zip con
REM    - el codigo versionado en HEAD (git archive: sin .venv, output,
REM      .cache, .env ni nada que no este en git), y
REM    - AudioGeneration.exe en la raiz del zip (si falta, se compila con
REM      bats\build_launcher.bat).
REM  La version se lee de pyproject.toml.
REM
REM  OJO: git archive empaqueta HEAD; los cambios sin commitear NO entran.
REM
REM  Uso:   bats\package_release.bat        bats\package_release.bat /y   (sin pause)
REM ====================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
if /i "%~1"=="/y" set "NONINTERACTIVE=1"
if /i "%~1"=="-y" set "NONINTERACTIVE=1"

where git >nul 2>nul
if errorlevel 1 (
    echo ERROR: git no esta instalado o no esta en el PATH.
    goto fail
)
git rev-parse --verify HEAD >nul 2>nul
if errorlevel 1 (
    echo ERROR: esta carpeta no es un repositorio git con commits.
    goto fail
)

REM --------------------------------------------------------------------
REM  Version: primera linea  version = "x.y.z"  de pyproject.toml
set "VERSION="
for /f "tokens=2 delims==" %%v in ('findstr /r /b /c:"version *=" pyproject.toml') do (
    if not defined VERSION set "VERSION=%%~v"
)
set "VERSION=%VERSION: =%"
set "VERSION=%VERSION:"=%"
if not defined VERSION (
    echo ERROR: no se pudo leer la version de pyproject.toml.
    goto fail
)
set "ZIP=dist\AudioGeneration-v%VERSION%-windows.zip"
echo Empaquetando AudioGeneration v%VERSION%...

git diff --quiet HEAD -- 2>nul
if errorlevel 1 echo   AVISO: hay cambios sin commitear; el zip solo incluye lo que hay en HEAD.

REM --------------------------------------------------------------------
echo.
echo [1/3] Lanzador AudioGeneration.exe...
if not exist "AudioGeneration.exe" (
    echo   No existe: se compila con bats\build_launcher.bat
    call "%~dp0build_launcher.bat" /y
    if errorlevel 1 goto fail
) else (
    echo   Se usa el AudioGeneration.exe existente.
)

REM --------------------------------------------------------------------
echo.
echo [2/3] git archive HEAD -^> %ZIP%
if not exist "dist" mkdir "dist"
if exist "%ZIP%" del /q "%ZIP%"
git archive --format=zip -o "%ZIP%" HEAD
if errorlevel 1 (
    echo ERROR en git archive.
    goto fail
)

REM --------------------------------------------------------------------
echo.
echo [3/3] Anadiendo AudioGeneration.exe a la raiz del zip y comprobando el contenido...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$z=[IO.Compression.ZipFile]::Open((Resolve-Path '%ZIP%').Path,'Update');" ^
  "try { [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z,(Resolve-Path 'AudioGeneration.exe').Path,'AudioGeneration.exe','Optimal');" ^
  " $bad=@($z.Entries | ? { $_.FullName -match '^(\.venv|output|\.cache|models|build|dist)/|^\.env$|(^|/)CLAUDE\.md$' });" ^
  " if ($bad.Count) { Write-Host ('  ERROR: entradas que no deberian estar: ' + ($bad.FullName -join ', ')); exit 3 };" ^
  " Write-Host ('  ' + $z.Entries.Count + ' entradas; AudioGeneration.exe en la raiz.') } finally { $z.Dispose() }"
if errorlevel 1 (
    echo ERROR preparando el zip.
    goto fail
)

for %%f in ("%ZIP%") do set "ZIP_SIZE=%%~zf"
echo.
echo ====================================================================
echo  Listo: %ZIP% ^(%ZIP_SIZE% bytes^)
echo  Subelo como asset de la release v%VERSION% en GitHub.
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
endlocal
exit /b 1
