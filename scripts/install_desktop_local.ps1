# Install the OmniRoute Desktop UI on the COMPUTER running Hermes Desktop.
# It does not connect to the CT, install Python plugins or touch credentials.
# Run in PowerShell from the extracted release directory:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_desktop_local.ps1
[CmdletBinding()]
param(
    [string] $HermesHome = $(Join-Path $env:LOCALAPPDATA 'hermes')
)
$ErrorActionPreference = 'Stop'
$Source = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend\desktop\plugin.js'
if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Arquivo da interface Desktop não encontrado: $Source"
}
$PluginsRoot = Join-Path $HermesHome 'desktop-plugins'
if (-not (Test-Path -LiteralPath $PluginsRoot -PathType Container)) {
    throw "Diretorio de plugins Desktop nao encontrado: $PluginsRoot. Abra a pasta de plugins pelo Hermes Desktop e informe o diretorio pai com -HermesHome."
}
$Target = Join-Path $PluginsRoot 'omniroute-media'
$TargetFile = Join-Path $Target 'plugin.js'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Records = 'C:\Users\lucas\OneDrive\Área de Trabalho\Registros'
if (-not (Test-Path -LiteralPath (Split-Path -Parent $Records))) {
    $Records = Join-Path $HOME 'Documents'
}
New-Item -ItemType Directory -Force -Path $Records | Out-Null
$Log = Join-Path $Records ("OmniRoute_Desktop_Instalacao_{0}.txt" -f $Stamp)
try {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    if (Test-Path -LiteralPath $TargetFile -PathType Leaf) {
        $Backup = Join-Path $Target ("plugin.js.backup-{0}" -f $Stamp)
        Copy-Item -LiteralPath $TargetFile -Destination $Backup -ErrorAction Stop
        "Backup: $Backup" | Add-Content -LiteralPath $Log -Encoding UTF8
    }
    Copy-Item -LiteralPath $Source -Destination $TargetFile -Force -ErrorAction Stop
    $Hash = (Get-FileHash -LiteralPath $TargetFile -Algorithm SHA256).Hash
    @(
        "Instalacao OmniRoute Desktop UI v0.5.0-beta.1: $Stamp",
        "Origem: $Source",
        "Destino: $TargetFile",
        "SHA256 do plugin.js: $Hash",
        "Resultado: COPIADO; habilitacao na interface ainda necessaria.",
        'Abra Hermes Desktop -> Capabilities -> Plugins -> Rescan, habilite OmniRoute.'
    ) | Add-Content -LiteralPath $Log -Encoding UTF8
    Write-Output "Plugin copiado: $TargetFile"
    Write-Output 'No Hermes Desktop, acione Capabilities > Plugins > Rescan e habilite OmniRoute.'
    Write-Output "Relatorio: $Log"
} catch {
    ("ERRO: " + $_.Exception.Message) | Add-Content -LiteralPath $Log -Encoding UTF8
    throw
}
