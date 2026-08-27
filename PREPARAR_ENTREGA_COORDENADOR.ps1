$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "ConectaPC 2.1.0 - preparando entrega do relay" -ForegroundColor Cyan

& "$PSScriptRoot\GERAR_PACOTE_RELAY.ps1"

& "$PSScriptRoot\VERIFICAR_PILOTO.ps1" -Profile Preparation -SkipNetwork
if ($LASTEXITCODE -ne 0) {
    throw "A preparação local não passou no preflight."
}

$zipPath = Join-Path $PSScriptRoot "dist_relay\conectapc-relay-2.1.0.zip"
$hashPath = Join-Path $PSScriptRoot "dist_relay\SHA256.txt"

Write-Host ""
Write-Host "ENTREGA LOCAL PREPARADA" -ForegroundColor Green
Write-Host "Envie ao coordenador:" -ForegroundColor Cyan
Write-Host "  $zipPath"
Write-Host "  $hashPath"
Write-Host "  $(Join-Path $PSScriptRoot 'ENTREGA_COORDENADOR.md')"
Write-Host "O instalador Windows deve ser gerado somente após o domínio real ser informado." -ForegroundColor Yellow
