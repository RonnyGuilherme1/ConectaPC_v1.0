param(
    [switch]$SkipNetwork,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Pass([string]$Text) { Write-Host "[OK] $Text" -ForegroundColor Green }
function Fail([string]$Text) { Write-Host "[BLOQUEIO] $Text" -ForegroundColor Red; $failures.Add($Text) }
function Warn([string]$Text) { Write-Host "[PENDENTE] $Text" -ForegroundColor Yellow; $warnings.Add($Text) }

Write-Host "ConectaPC 2.1.0 - verificação para piloto" -ForegroundColor Cyan

try {
    $config = Get-Content -Raw -LiteralPath "relay_config.json" | ConvertFrom-Json
    Pass "relay_config.json possui JSON válido"
} catch {
    Fail "relay_config.json inválido: $($_.Exception.Message)"
    $config = $null
}

if ($config) {
    $hostName = [string]$config.host
    if (-not $config.enabled) { Fail "relay está desabilitado" }
    elseif (-not $hostName -or $hostName.StartsWith("SEU_")) { Fail "domínio do relay não foi configurado" }
    else { Pass "relay configurado para $hostName" }

    if (-not $config.tls) { Fail "TLS está desabilitado" } else { Pass "TLS obrigatório no cliente" }
    if ($config.allow_insecure_dev) { Fail "allow_insecure_dev não pode estar ativo no piloto" }
    else { Pass "modo inseguro desabilitado" }

    if (-not $SkipNetwork -and $config.enabled -and $hostName -and -not $hostName.StartsWith("SEU_")) {
        try {
            $addresses = [System.Net.Dns]::GetHostAddresses($hostName)
            if (-not $addresses) { throw "nenhum endereço encontrado" }
            Pass "DNS resolve $hostName"

            $tcp = [System.Net.Sockets.TcpClient]::new()
            try {
                $connectTask = $tcp.ConnectAsync($hostName, [int]$config.port)
                if (-not $connectTask.Wait([TimeSpan]::FromSeconds(8))) { throw "timeout TCP" }
                $ssl = [System.Net.Security.SslStream]::new($tcp.GetStream(), $false)
                try {
                    $ssl.AuthenticateAsClient($hostName)
                    $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($ssl.RemoteCertificate)
                    if ($certificate.NotAfter -lt (Get-Date).AddDays(14)) {
                        Fail "certificado TLS vence em menos de 14 dias: $($certificate.NotAfter)"
                    } else {
                        Pass "TLS válido até $($certificate.NotAfter.ToString('yyyy-MM-dd'))"
                    }
                    Pass "protocolo negociado: $($ssl.SslProtocol)"
                } finally { $ssl.Dispose() }
            } finally { $tcp.Dispose() }
        } catch {
            Fail "relay/TLS não acessível: $($_.Exception.Message)"
        }
    }
}

$updateSource = Get-Content -Raw -LiteralPath "updates.py"
if ($updateSource -match 'PINNED_UPDATE_PUBLIC_KEY\s*=\s*"([^"]*)"' -and $Matches[1]) {
    Pass "chave pública de atualização fixada no executável"
} else {
    Fail "PINNED_UPDATE_PUBLIC_KEY ainda não foi configurada"
}

$pfx = $env:CONECTAPC_SIGN_PFX
if (-not $pfx) {
    Fail "CONECTAPC_SIGN_PFX não está configurado"
} elseif (-not (Test-Path -LiteralPath $pfx)) {
    Fail "arquivo PFX configurado não existe"
} else {
    Pass "certificado Authenticode configurado"
}
if (-not $env:CONECTAPC_SIGN_PASSWORD) { Warn "CONECTAPC_SIGN_PASSWORD não está configurada" }

if (-not $SkipTests) {
    $python = Join-Path $PSScriptRoot ".buildenv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { Fail "ambiente .buildenv não existe" }
    else {
        & $python -m unittest discover -v
        if ($LASTEXITCODE -ne 0) { Fail "testes automatizados falharam" }
        else { Pass "testes automatizados" }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) { Fail "dependências possuem conflitos" }
        else { Pass "dependências sem conflitos" }
    }
}

$setup = Join-Path $PSScriptRoot "dist_installer\ConectaPC_Setup_v2.1.0.exe"
if (Test-Path -LiteralPath $setup) {
    $signature = Get-AuthenticodeSignature -LiteralPath $setup
    if ($signature.Status -eq "Valid") { Pass "Setup 2.1.0 possui assinatura válida" }
    else { Fail "Setup 2.1.0 não possui assinatura válida: $($signature.Status)" }
} else {
    Warn "Setup 2.1.0 ainda não foi gerado"
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "PILOTO LIBERADO PELO PREFLIGHT" -ForegroundColor Green
    exit 0
}
Write-Host "PILOTO BLOQUEADO: $($failures.Count) requisito(s) obrigatório(s)." -ForegroundColor Red
exit 2
