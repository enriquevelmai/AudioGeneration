<#
.SYNOPSIS
  Instala (idempotente) la skill de Claude Code `podcast-tts` creando una junction
  %USERPROFILE%\.claude\skills\podcast-tts -> <repo>\skill\podcast-tts.

  Las junctions no requieren permisos de administrador. Si ya existe una junction/symlink
  correcta no hace nada; si apunta a otro sitio la recrea; si es una carpeta normal (copia antigua)
  la renombra a podcast-tts.bak-<fecha> antes de crear la junction.

.PARAMETER Copy
  En lugar de junction, copia la carpeta (habrá que volver a ejecutar el script tras cada cambio).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1
#>
param([switch]$Copy)
$ErrorActionPreference = 'Stop'

$Source = (Resolve-Path (Join-Path $PSScriptRoot '..\skill\podcast-tts')).Path
$SkillsDir = Join-Path $env:USERPROFILE '.claude\skills'
$Target = Join-Path $SkillsDir 'podcast-tts'

if (-not (Test-Path (Join-Path $Source 'SKILL.md'))) { throw "No existe $Source\SKILL.md" }
New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null

$item = Get-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue
if ($item) {
    $isLink = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    if ($isLink -and -not $Copy) {
        $current = @($item.Target)[0]
        if ($current -and ((Resolve-Path -LiteralPath $current).Path.TrimEnd('\') -eq $Source.TrimEnd('\'))) {
            Write-Host "La skill ya está instalada: $Target -> $Source"
            exit 0
        }
        Write-Host "La junction apunta a '$current'; se recrea."
        # Borra solo el enlace, no el contenido del destino
        [IO.Directory]::Delete($Target)
    } elseif ($isLink) {
        [IO.Directory]::Delete($Target)
    } else {
        $backup = "$Target.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Write-Host "Existe una carpeta normal en $Target; se renombra a $backup"
        Rename-Item -LiteralPath $Target -NewName (Split-Path $backup -Leaf)
    }
}

if ($Copy) {
    Copy-Item -Recurse -Path $Source -Destination $Target
    Write-Host "Skill copiada en $Target (vuelve a ejecutar con -Copy tras cada cambio)."
} else {
    New-Item -ItemType Junction -Path $Target -Target $Source | Out-Null
    Write-Host "Junction creada: $Target -> $Source"
}

if (-not (Test-Path (Join-Path $Target 'SKILL.md'))) { throw "Instalación fallida: no se lee $Target\SKILL.md" }
Write-Host 'OK: SKILL.md accesible.'
