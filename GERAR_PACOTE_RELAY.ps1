$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$outputDir = Join-Path $PSScriptRoot "dist_relay"
$stageDir = Join-Path $outputDir "conectapc-relay-2.1.0"
$zipPath = Join-Path $outputDir "conectapc-relay-2.1.0.zip"

$resolvedOutput = [IO.Path]::GetFullPath($outputDir)
$resolvedStage = [IO.Path]::GetFullPath($stageDir)
if (-not $resolvedStage.StartsWith($resolvedOutput + [IO.Path]::DirectorySeparatorChar) -or
    (Split-Path $resolvedStage -Leaf) -ne "conectapc-relay-2.1.0") {
    throw "Diretório temporário do pacote fora do escopo esperado."
}

if (Test-Path -LiteralPath $resolvedStage) { Remove-Item -LiteralPath $resolvedStage -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $resolvedStage "systemd") | Out-Null

Copy-Item -LiteralPath "server\relay_server.py" -Destination $resolvedStage
Copy-Item -LiteralPath "server\security_store.py" -Destination $resolvedStage
Copy-Item -LiteralPath "server\manage_security.py" -Destination $resolvedStage
Copy-Item -LiteralPath "server\install_relay.sh" -Destination $resolvedStage
Copy-Item -LiteralPath "server\DEPLOY_VPS.md" -Destination $resolvedStage
Copy-Item -LiteralPath "server\systemd\conectapc-relay.service" -Destination (Join-Path $resolvedStage "systemd")

if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -LiteralPath $resolvedStage -DestinationPath $zipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
"conectapc-relay-2.1.0.zip  SHA256=$hash" | Set-Content -LiteralPath (Join-Path $outputDir "SHA256.txt") -Encoding UTF8

Write-Host "Pacote do relay criado: $zipPath" -ForegroundColor Green
Write-Host "SHA256: $hash"
