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
Copy-Item -LiteralPath "server\TESTAR_RELAY_LOCAL.py" -Destination $resolvedStage
Copy-Item -LiteralPath "server\requirements-server.txt" -Destination $resolvedStage
Copy-Item -LiteralPath "server\install_relay.sh" -Destination $resolvedStage
Copy-Item -LiteralPath "server\DEPLOY_VPS.md" -Destination $resolvedStage
Copy-Item -LiteralPath "ENTREGA_COORDENADOR.md" -Destination (Join-Path $resolvedStage "LEIA-ME_COORDENADOR.md")
Copy-Item -LiteralPath "server\systemd\conectapc-relay.service" -Destination (Join-Path $resolvedStage "systemd")

if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -LiteralPath $resolvedStage -DestinationPath $zipPath -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression.FileSystem
$expectedFiles = @(
    "relay_server.py",
    "security_store.py",
    "manage_security.py",
    "TESTAR_RELAY_LOCAL.py",
    "requirements-server.txt",
    "install_relay.sh",
    "DEPLOY_VPS.md",
    "LEIA-ME_COORDENADOR.md",
    "systemd/conectapc-relay.service"
)
$archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/").TrimStart("/") })
    foreach ($expected in $expectedFiles) {
        $found = @($entryNames | Where-Object { $_ -eq $expected -or $_.EndsWith("/$expected") }).Count -gt 0
        if (-not $found) { throw "Pacote incompleto: $expected não foi encontrado no ZIP." }
    }
} finally {
    $archive.Dispose()
}

$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
"conectapc-relay-2.1.0.zip  SHA256=$hash" | Set-Content -LiteralPath (Join-Path $outputDir "SHA256.txt") -Encoding UTF8

Write-Host "Pacote do relay criado: $zipPath" -ForegroundColor Green
Write-Host "Conteúdo obrigatório validado: $($expectedFiles.Count) arquivos" -ForegroundColor Green
Write-Host "SHA256: $hash"
