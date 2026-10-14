<#
.SYNOPSIS
  Instala (idempotente) la skill de Claude Code `podcast-tts` creando una junction
  %USERPROFILE%\.claude\skills\podcast-tts -> <repo>\skill\podcast-tts.

  Las junctions no requieren permisos de administrador. Si ya existe una junction/symlink
  correcta no hace nada; si apunta a otro sitio la recrea (salvo con -NoReplace); si es una
  carpeta normal (copia antigua) la renombra a podcast-tts.bak-<fecha> antes de crear la junction.

  Los wrappers de la skill (scripts/generar.ps1 y generar.sh) localizan el proyecto siguiendo
  la junction, asi que no hace falta configurar nada mas.

.PARAMETER Copy
  En lugar de junction, copia la carpeta (habra que volver a ejecutar el script tras cada cambio).
  Como una copia no sabe donde esta el proyecto, fija ademas la variable de usuario
  PODCAST_TTS_HOME con la raiz del repositorio.

.PARAMETER NoReplace
  Si ya hay una skill instalada que apunta a OTRO proyecto, la deja como esta (modo no interactivo).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -Copy
#>
param([switch]$Copy, [switch]$NoReplace)
$ErrorActionPreference = 'Stop'

# -LiteralPath en todo: con -Path, los [ ] de una ruta se tratan como comodines.
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Source = Join-Path $Root 'skill\podcast-tts'
$SkillsDir = Join-Path $env:USERPROFILE '.claude\skills'
$Target = Join-Path $SkillsDir 'podcast-tts'

if (-not (Test-Path -LiteralPath (Join-Path $Source 'SKILL.md'))) { throw "No existe $Source\SKILL.md" }
[void][IO.Directory]::CreateDirectory($SkillsDir)

$item = Get-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue
if ($item) {
    $isLink = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    if ($isLink) {
        $current = @($item.Target)[0]
        $currentResolved = $null
        if ($current -and (Test-Path -LiteralPath $current)) {
            $currentResolved = (Resolve-Path -LiteralPath $current).Path.TrimEnd('\')
        }
        if (-not $Copy -and $currentResolved -eq $Source.TrimEnd('\')) {
            Write-Host "La skill ya esta instalada: $Target -> $Source"
            exit 0
        }
        if ($NoReplace -and $currentResolved) {
            Write-Host "AVISO: ya hay una skill podcast-tts que apunta a '$current'; no se toca (-NoReplace)."
            Write-Host "       Para usar este proyecto: powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1"
            exit 0
        }
        Write-Host "La junction apunta a '$current'; se recrea."
        # Borra solo el enlace, no el contenido del destino
        [IO.Directory]::Delete($Target)
    } else {
        $backup = "$Target.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Write-Host "Existe una carpeta normal en $Target; se renombra a $backup"
        Rename-Item -LiteralPath $Target -NewName (Split-Path $backup -Leaf)
    }
}

if ($Copy) {
    Copy-Item -Recurse -LiteralPath $Source -Destination $Target
    [Environment]::SetEnvironmentVariable('PODCAST_TTS_HOME', $Root, 'User')
    $env:PODCAST_TTS_HOME = $Root
    Write-Host "Skill copiada en $Target (vuelve a ejecutar con -Copy tras cada cambio)."
    Write-Host "Variable de usuario PODCAST_TTS_HOME = $Root (abre una consola nueva para verla)."
} else {
    # New-Item resuelve -Target como comodin (los [ ] de la ruta del proyecto fallarian): se
    # escapa. -Path, en cambio, se usa tal cual.
    $sourceEscaped = [Management.Automation.WildcardPattern]::Escape($Source)
    New-Item -ItemType Junction -Path $Target -Target $sourceEscaped | Out-Null
    Write-Host "Junction creada: $Target -> $Source"
}

if (-not (Test-Path -LiteralPath (Join-Path $Target 'SKILL.md'))) { throw "Instalacion fallida: no se lee $Target\SKILL.md" }
Write-Host 'OK: SKILL.md accesible.'
