<#
.SYNOPSIS
  Wrapper for the podcast_tts CLI: finds the project, sets the environment variables
  (PYTHONUTF8, PYTHONIOENCODING, COQUI_TOS_AGREED) and forwards all arguments.

.DESCRIPTION
  Project root, in this order:
    1. PODCAST_TTS_HOME environment variable.
    2. Target of the %USERPROFILE%\.claude\skills\podcast-tts junction (-> <repo>\skill\podcast-tts).
    3. ..\..\.. from this script (when run inside the repository).

.EXAMPLE
  & "$HOME\.claude\skills\podcast-tts\scripts\generate.ps1" voices list --json
  & "$HOME\.claude\skills\podcast-tts\scripts\generate.ps1" generate C:\path\script.md -o C:\path\episode.mp3
  & "$HOME\.claude\skills\podcast-tts\scripts\generate.ps1" --where    # prints the project root
#>
$ErrorActionPreference = 'Stop'

function Test-ProjectRoot([string]$Path) {
    return ($Path -and (Test-Path -LiteralPath (Join-Path $Path 'src\podcast_tts')))
}

$candidates = @()
if ($env:PODCAST_TTS_HOME) { $candidates += $env:PODCAST_TTS_HOME }
$link = Get-Item -LiteralPath (Join-Path $env:USERPROFILE '.claude\skills\podcast-tts') -Force -ErrorAction SilentlyContinue
if ($link -and ($link.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    $target = @($link.Target)[0]
    if ($target) { $candidates += (Join-Path $target '..\..') }
}
$candidates += (Join-Path $PSScriptRoot '..\..\..')

$Project = $null
foreach ($c in $candidates) {
    if (Test-ProjectRoot $c) { $Project = (Resolve-Path -LiteralPath $c).Path; break }
}
if (-not $Project) {
    Write-Error ("Cannot find the podcast-tts project. Set PODCAST_TTS_HOME to the repository path " +
                 "or reinstall the skill with scripts\install_skill.ps1.")
    exit 2
}
if ($args.Count -eq 1 -and $args[0] -eq '--where') { Write-Output $Project; exit 0 }

$Python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "$Python does not exist. Run bats\install.bat in $Project."
    exit 2
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:COQUI_TOS_AGREED = '1'

& $Python -m podcast_tts @args
exit $LASTEXITCODE
