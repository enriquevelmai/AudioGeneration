@echo off
REM ====================================================================
REM  AudioGeneration - Packages the Windows release zip.
REM
REM  Result: dist\AudioGeneration-v<version>-windows.zip with everything inside
REM  an AudioGeneration\ folder (extracting it does not mix with other files):
REM    - the code versioned in HEAD (git archive only packages versioned
REM      files: no .venv, output, .cache or .env), and
REM    - AudioGeneration\AudioGeneration.exe (if missing, it is built with
REM      bats\build_launcher.bat).
REM  The version is read from pyproject.toml.
REM
REM  NOTE: git archive packages HEAD; uncommitted changes are NOT included.
REM
REM  Usage: bats\package_release.bat        bats\package_release.bat /y   (no pause)
REM ====================================================================
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0.." 2>nul || (
    echo ERROR: cannot open the project folder: "%~dp0.."
    echo   If it is on a network path ^(\\server\folder^), copy it to a local disk.
    if /i not "%~1"=="/y" pause
    exit /b 1
)
if not exist "pyproject.toml" (
    echo ERROR: pyproject.toml not found in "%CD%".
    echo   - If you opened the zip without extracting it, extract all its contents first
    echo     ^(right-click the zip ^> Extract All^) and run the .bat from there.
    echo   - If the folder is on a network path ^(\\server\folder^), copy it to a local disk.
    popd
    if /i not "%~1"=="/y" pause
    exit /b 1
)
set "NONINTERACTIVE=0"
if "%PODCAST_TTS_NONINTERACTIVE%"=="1" set "NONINTERACTIVE=1"
if /i "%~1"=="/y" set "NONINTERACTIVE=1"
if /i "%~1"=="-y" set "NONINTERACTIVE=1"

where git >nul 2>nul
if errorlevel 1 (
    echo ERROR: git is not installed or not on the PATH.
    goto fail
)
git rev-parse --verify HEAD >nul 2>nul
if errorlevel 1 (
    echo ERROR: this folder is not a git repository with commits.
    goto fail
)

REM --------------------------------------------------------------------
REM  Version: first line  version = "x.y.z"  of pyproject.toml
set "VERSION="
for /f "tokens=2 delims==" %%v in ('findstr /r /b /c:"version *=" pyproject.toml') do (
    if not defined VERSION set "VERSION=%%~v"
)
set "VERSION=%VERSION: =%"
set "VERSION=%VERSION:"=%"
if not defined VERSION (
    echo ERROR: could not read the version from pyproject.toml.
    goto fail
)
set "ZIP=dist\AudioGeneration-v%VERSION%-windows.zip"
echo Packaging AudioGeneration v%VERSION%...

git diff --quiet HEAD -- 2>nul
if errorlevel 1 echo   WARNING: there are uncommitted changes; the zip only includes what is in HEAD.

REM --------------------------------------------------------------------
echo.
echo [1/3] AudioGeneration.exe launcher...
if not exist "AudioGeneration.exe" (
    echo   Not found: building it with bats\build_launcher.bat
    call "%~dp0build_launcher.bat" /y
    if errorlevel 1 goto fail
) else (
    echo   Using the existing AudioGeneration.exe.
)

REM --------------------------------------------------------------------
echo.
echo [2/3] git archive HEAD -^> %ZIP%
if not exist "dist" mkdir "dist"
if exist "%ZIP%" del /q "%ZIP%"
git archive --format=zip --prefix=AudioGeneration/ -o "%ZIP%" HEAD
if errorlevel 1 (
    echo ERROR in git archive.
    goto fail
)

REM --------------------------------------------------------------------
echo.
echo [3/3] Adding AudioGeneration.exe to the zip and checking its contents...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$z=[IO.Compression.ZipFile]::Open((Resolve-Path -LiteralPath '%ZIP%').Path,'Update');" ^
  "try { [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z,(Resolve-Path -LiteralPath 'AudioGeneration.exe').Path,'AudioGeneration/AudioGeneration.exe','Optimal');" ^
  " $out=@($z.Entries | ? { -not $_.FullName.StartsWith('AudioGeneration/') });" ^
  " if ($out.Count) { Write-Host ('  ERROR: entries outside AudioGeneration/: ' + ($out.FullName -join ', ')); exit 3 };" ^
  " $bad=@($z.Entries | ? { $_.FullName -match '^AudioGeneration/((\.venv|output|\.cache|models|build|dist)/|\.env$)' });" ^
  " if ($bad.Count) { Write-Host ('  ERROR: entries that should not be there: ' + ($bad.FullName -join ', ')); exit 3 };" ^
  " Write-Host ('  ' + $z.Entries.Count + ' entries, all inside AudioGeneration/.') } finally { $z.Dispose() }"
if errorlevel 1 (
    echo ERROR preparing the zip.
    goto fail
)

for %%f in ("%ZIP%") do set "ZIP_SIZE=%%~zf"
echo.
echo ====================================================================
echo  Done: %ZIP% ^(%ZIP_SIZE% bytes^)
echo  Upload it as an asset of the v%VERSION% release on GitHub.
echo ====================================================================
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal
exit /b 0

:fail
if not "%NONINTERACTIVE%"=="1" pause
popd
endlocal
exit /b 1
