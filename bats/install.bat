@echo off
REM ====================================================================
REM  podcast-tts - Installation (isolated .venv environment managed by uv).
REM
REM  - Installs uv if missing (official astral installer, no admin).
REM  - Installs Python 3.11 with uv (unless a usable one already exists).
REM  - Detects an NVIDIA GPU (nvidia-smi) and picks CUDA or CPU torch.
REM  - Also installs the desktop app (desktop extra: pywebview)
REM    and the MCP server for AI assistants (mcp extra).
REM  - Offers to download the models now and, if you use Claude Code, the skill.
REM  - Creates "AudioGeneration" shortcuts (Desktop and Start menu).
REM
REM  Usage: bats\install.bat               (interactive)
REM         bats\install.bat /y            (no questions or pause; answers yes to everything,
REM                                         shortcuts included)
REM         bats\install.bat /cpu          (forces CPU torch even if there is a GPU)
REM         bats\install.bat /cuda         (forces CUDA torch)
REM         bats\install.bat /noshortcuts  (does not create shortcuts)
REM         bats\install.bat /dev          (adds the dev extra: pytest, for development)
REM  Optional variables:
REM         PODCAST_TTS_NONINTERACTIVE=1   same as /y
REM         PODCAST_TTS_VARIANT=cpu|cuda   forces the torch variant
REM         PODCAST_TTS_DOWNLOAD_MODELS=0|1, PODCAST_TTS_INSTALL_SKILL=0|1
REM         PODCAST_TTS_SHORTCUTS=0|1      shortcuts (0 = do not create them)
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
set "ROOT=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "COQUI_TOS_AGREED=1"
REM In case the editable install .pth is not read correctly (paths with accents).
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
echo  podcast-tts - installing in "%ROOT%"
echo ====================================================================

REM --------------------------------------------------------------------
echo.
echo [1/8] Checking uv...
call :find_uv
if not defined UV (
    echo   uv not found. Installing uv ^(local, no admin^)...
    powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    call :find_uv
)
if not defined UV (
    echo ERROR: could not install uv. Install it manually: https://docs.astral.sh/uv/
    goto fail
)
echo   uv: %UV%

REM --------------------------------------------------------------------
echo.
echo [2/8] Python 3.11 ^(managed by uv^)...
"%UV%" python find 3.11 >nul 2>nul
if not errorlevel 1 (
    echo   A usable Python 3.11 is already available.
    goto python_done
)
echo   Downloading Python 3.11 ^(about 30 MB^)...
set "UVPY_LOG=%TEMP%\podcast-tts-uv-python.log"
"%UV%" python install 3.11 >"%UVPY_LOG%" 2>&1
set "UVPY_ERR=%errorlevel%"
"%UV%" python find 3.11 >nul 2>nul
if errorlevel 1 (
    type "%UVPY_LOG%"
    echo ERROR installing Python 3.11 with uv ^(see above^).
    goto fail
)
REM uv may warn "Missing expected target directory for Python minor version link"
REM even though Python is installed and works: it is not shown to avoid alarming users.
if not "%UVPY_ERR%"=="0" echo   Python 3.11 installed ^(uv reported a minor, harmless issue^).
if "%UVPY_ERR%"=="0" echo   Python 3.11 installed.
:python_done

REM --------------------------------------------------------------------
echo.
echo [3/8] Checking for an NVIDIA GPU...
if defined VARIANT (
    echo   Forced variant: %VARIANT%
) else (
    call :detect_gpu
)
if /i not "%VARIANT%"=="cuda" if /i not "%VARIANT%"=="cpu" (
    echo ERROR: unknown variant "%VARIANT%" ^(use cpu or cuda^).
    goto fail
)
if /i "%VARIANT%"=="cuda" (
    echo   PyTorch with CUDA 12.6 will be installed ^(~2.5 GB^).
) else (
    echo   PyTorch for CPU will be installed: it works, but synthesis will be VERY slow.
)

REM --------------------------------------------------------------------
set "EXTRAS=local %VARIANT% desktop mcp"
if "%WITH_DEV%"=="1" set "EXTRAS=local %VARIANT% desktop mcp dev"
set "EXTRA_ARGS=--extra local --extra %VARIANT% --extra desktop --extra mcp"
if "%WITH_DEV%"=="1" set "EXTRA_ARGS=%EXTRA_ARGS% --extra dev"
echo.
echo [4/8] Creating .venv and installing dependencies ^(%EXTRAS%^)...
echo   The first time it downloads several GB; later runs use the uv cache.
"%UV%" sync --locked --python 3.11 %EXTRA_ARGS%
if errorlevel 1 (
    echo ERROR in uv sync. Check the output above.
    goto fail
)
> ".venv\podcast-tts-extras.txt" echo %EXTRAS%
echo   Extras recorded in .venv\podcast-tts-extras.txt: %EXTRAS%
".venv\Scripts\python.exe" -I -S scripts\fix_editable_pth.py

REM --------------------------------------------------------------------
echo.
echo [5/8] Checking ffmpeg and the environment...
call :ensure_ffmpeg
".venv\Scripts\python.exe" scripts\check_env.py
if errorlevel 1 (
    echo WARNING: check_env.py found problems ^(see above^).
    set "ENV_PROBLEMS=1"
)

REM --------------------------------------------------------------------
echo.
echo [6/8] Models ^(F5-TTS, F5-Spanish, Vocos, XTTS v2: ~4.5 GB^)...
echo   They download automatically the first time they are used; you can fetch them now.
echo   Licenses: F5 and F5-Spanish CC-BY-NC-4.0, XTTS v2 CPML ^(NON-commercial use^).
set "DO_MODELS=%PODCAST_TTS_DOWNLOAD_MODELS%"
if not defined DO_MODELS call :ask "Download the models now" DO_MODELS
if "%DO_MODELS%"=="1" (
    ".venv\Scripts\python.exe" -m podcast_tts models download all
    if errorlevel 1 echo WARNING: some download failed; retry with: bats\update.bat
) else (
    echo   Skipped. Later: .venv\Scripts\python.exe -m podcast_tts models download
)

REM --------------------------------------------------------------------
echo.
echo [7/8] Claude Code skill...
if not exist "%USERPROFILE%\.claude\" (
    echo   The user's .claude folder was not found: Claude Code does not seem to be installed. Skipped.
    goto skill_done
)
set "DO_SKILL=%PODCAST_TTS_INSTALL_SKILL%"
if not defined DO_SKILL call :ask "Install the podcast-tts skill in Claude Code" DO_SKILL
if "%DO_SKILL%"=="1" (
    if "%NONINTERACTIVE%"=="1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -NoReplace
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_skill.ps1
    )
    if errorlevel 1 echo WARNING: could not install the skill ^(see above^).
) else (
    echo   Skipped. Later: powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1
)
:skill_done

REM --------------------------------------------------------------------
echo.
echo [8/8] "AudioGeneration" shortcuts ^(Desktop and Start menu^)...
set "DO_SHORTCUTS=%PODCAST_TTS_SHORTCUTS%"
if "%NOSHORTCUTS%"=="1" set "DO_SHORTCUTS=0"
if not defined DO_SHORTCUTS call :ask "Create shortcuts on the Desktop and in the Start menu" DO_SHORTCUTS
if "%DO_SHORTCUTS%"=="1" (
    call "%ROOT%\bats\create_shortcuts.bat" /y
    if errorlevel 1 echo WARNING: could not create the shortcuts ^(see above^).
) else (
    echo   Skipped. Later: bats\create_shortcuts.bat
)

echo.
echo ====================================================================
if defined ENV_PROBLEMS echo  Installed with warnings: review the [FAIL] lines from check_env.py.
if not defined ENV_PROBLEMS echo  Done.
if exist "AudioGeneration.exe" (
    echo  Open the app:      AudioGeneration.exe ^(or the AudioGeneration shortcut^)
) else (
    echo  Open the app:      bats\run.bat ^(or the AudioGeneration shortcut^)
)
echo  In the browser:    bats\run_web.bat
echo  Update:            bats\update.bat
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
REM  Subroutines
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
    echo   No nvidia-smi: there is no NVIDIA GPU ^(or the driver is missing^).
    exit /b 0
)
nvidia-smi -L >nul 2>nul
if errorlevel 1 (
    echo   nvidia-smi does not respond: CPU will be used. Update the NVIDIA driver if you have a GPU.
    exit /b 0
)
set "VARIANT=cuda"
for /f "delims=" %%g in ('nvidia-smi -L') do echo   %%g
exit /b 0

:ensure_ffmpeg
where ffmpeg >nul 2>nul
if not errorlevel 1 exit /b 0
echo   ffmpeg is not on the PATH ^(needed to read/write MP3^).
where winget >nul 2>nul
if errorlevel 1 (
    echo   Install it manually ^(e.g. https://www.gyan.dev/ffmpeg/builds/^) and add it to the PATH.
    exit /b 0
)
set "DO_FFMPEG="
call :ask "Install ffmpeg with winget (Gyan.FFmpeg, no admin)" DO_FFMPEG
if not "%DO_FFMPEG%"=="1" exit /b 0
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where ffmpeg >nul 2>nul
if errorlevel 1 echo   Open a new console so that ffmpeg shows up on the PATH.
exit /b 0

REM  :ask "question" VARIABLE  -> VARIABLE=1 (yes) or 0 (no). In /y mode it answers yes.
REM  Anything other than n/no counts as yes (so Y, S and Enter all accept).
:ask
if "%NONINTERACTIVE%"=="1" (
    set "%~2=1"
    exit /b 0
)
set "ANSWER="
set /p "ANSWER=  %~1? [Y/n] "
if /i "%ANSWER%"=="n" (set "%~2=0") else if /i "%ANSWER%"=="no" (set "%~2=0") else (set "%~2=1")
exit /b 0
