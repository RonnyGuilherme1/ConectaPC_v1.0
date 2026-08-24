param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9.-]+$')][string]$RelayHost,
    [ValidateRange(1,65535)][int]$RelayPort = 443,
    [string]$UpdateManifestUrl = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($RelayHost.StartsWith("SEU_") -or -not $RelayHost.Contains(".")) {
    throw "Informe um domínio válido, por exemplo relay.suaempresa.com.br."
}
if ($UpdateManifestUrl -and -not $UpdateManifestUrl.StartsWith("https://")) {
    throw "A URL do manifesto deve usar HTTPS."
}

$config = [ordered]@{
    enabled = $true
    host = $RelayHost
    port = $RelayPort
    tls = $true
    server_name = $RelayHost
    ca_file = ""
    allow_insecure_dev = $false
    enrollment_token = ""
    updates = [ordered]@{
        manifest_url = $UpdateManifestUrl
        public_key = ""
        allow_insecure_dev = $false
    }
}

$json = $config | ConvertTo-Json -Depth 4
$json | Set-Content -LiteralPath "relay_config.json" -Encoding UTF8
Write-Host "Cliente configurado para $RelayHost`:$RelayPort com TLS obrigatório." -ForegroundColor Green
Write-Host "Execute .\VERIFICAR_PILOTO.ps1 antes do build de release." -ForegroundColor Yellow
