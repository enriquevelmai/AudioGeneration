<#
.SYNOPSIS
  Wrapper del CLI de podcast_tts: localiza el proyecto, fija las variables de entorno
  (PYTHONUTF8, PYTHONIOENCODING, COQUI_TOS_AGREED) y pasa todos los argumentos.

.DESCRIPTION
  Raiz del proyecto, por este orden:
    1. Variable de entorno PODCAST_TTS_HOME.
    2. Destino de la junction %USERPROFILE%\.claude\skills\podcast-tts (-> <repo>\skill\podcast-tts).
    3. ..\..\.. desde este script (si se ejecuta dentro del repositorio).

.EXAMPLE
  & "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" voices list --json
  & "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" generate C:\ruta\guion.md -o C:\ruta\episodio.mp3
  & "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" --where    # imprime la raiz del proyecto
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
    Write-Error ("No se encuentra el proyecto podcast-tts. Define PODCAST_TTS_HOME con la ruta del " +
                 "repositorio o reinstala la skill con scripts\install_skill.ps1.")
    exit 2
}
if ($args.Count -eq 1 -and $args[0] -eq '--where') { Write-Output $Project; exit 0 }

$Python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "No existe $Python. Ejecuta bats\install.bat en $Project."
    exit 2
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:COQUI_TOS_AGREED = '1'

& $Python -m podcast_tts @args
exit $LASTEXITCODE
