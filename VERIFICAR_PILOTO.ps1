param(
    [ValidateSet("Preparation", "VpsTest", "Production")]
    [string]$Profile = "Production",
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

$requiresConfiguredRelay = $Profile -ne "Preparation"
$requiresProductionRelease = $Profile -eq "Production"

Write-Host "ConectaPC 2.1.0 - verificação do perfil $Profile" -ForegroundColor Cyan

try {
    $config = Get-Content -Raw -LiteralPath "relay_config.json" | ConvertFrom-Json
    Pass "relay_config.json possui JSON válido"
} catch {
    Fail "relay_config.json inválido: $($_.Exception.Message)"
    $config = $null
}

if ($config) {
    $hostName = [string]$config.host
    if ($requiresConfiguredRelay) {
        if (-not $config.enabled) { Fail "relay está desabilitado" }
        elseif (-not $hostName -or $hostName.StartsWith("SEU_")) { Fail "domínio do relay não foi configurado" }
        else { Pass "relay configurado para $hostName" }
    } elseif (-not $config.enabled -and $hostName.StartsWith("SEU_")) {
        Pass "configuração permanece neutra até o coordenador informar o domínio"
    } elseif ($config.enabled -and $hostName -and -not $hostName.StartsWith("SEU_")) {
        Pass "relay já configurado para $hostName"
    } else {
        Fail "relay_config.json está parcialmente configurado"
    }

    if (-not $config.tls) { Fail "TLS está desabilitado" } else { Pass "TLS obrigatório no cliente" }
    if ($config.allow_insecure_dev) { Fail "allow_insecure_dev não pode estar ativo no piloto" }
    else { Pass "modo inseguro desabilitado" }

    if ($requiresConfiguredRelay -and $SkipNetwork) {
        Warn "verificação de DNS/TLS foi ignorada explicitamente"
    } elseif ($requiresConfiguredRelay -and $config.enabled -and $hostName -and -not $hostName.StartsWith("SEU_")) {
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

if ($requiresProductionRelease) {
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
} else {
    Pass "assinatura Authenticode e atualização assinada não são exigidas neste perfil"
}

if ($SkipTests) {
    Warn "testes automatizados foram ignorados explicitamente"
} else {
    $python = Join-Path $PSScriptRoot ".buildenv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { Fail "ambiente .buildenv não existe" }
    else {
        $testCountText = & $python -c "import unittest; print(unittest.defaultTestLoader.discover('tests').countTestCases())"
        if ($LASTEXITCODE -ne 0) {
            Fail "não foi possível descobrir os testes automatizados"
        } else {
            $testCount = 0
            if (-not [int]::TryParse(($testCountText | Select-Object -Last 1), [ref]$testCount) -or $testCount -le 0) {
                Fail "nenhum teste automatizado foi encontrado"
            } else {
                & $python -m unittest discover -v
                if ($LASTEXITCODE -ne 0) { Fail "testes automatizados falharam" }
                else { Pass "$testCount testes automatizados" }
            }
        }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) { Fail "dependências possuem conflitos" }
        else { Pass "dependências sem conflitos" }
    }
}

$relayPackage = Join-Path $PSScriptRoot "dist_relay\conectapc-relay-2.1.0.zip"
$relayHashFile = Join-Path $PSScriptRoot "dist_relay\SHA256.txt"
if (-not (Test-Path -LiteralPath $relayPackage)) {
    Fail "pacote do relay ainda não foi gerado"
} elseif (-not (Test-Path -LiteralPath $relayHashFile)) {
    Fail "arquivo SHA256 do pacote do relay não foi gerado"
} else {
    $declaredHash = Get-Content -Raw -LiteralPath $relayHashFile
    $actualHash = (Get-FileHash -LiteralPath $relayPackage -Algorithm SHA256).Hash
    if ($declaredHash -notmatch 'SHA256=([A-Fa-f0-9]{64})') {
        Fail "arquivo SHA256 do relay possui formato inválido"
    } elseif ($Matches[1].ToUpperInvariant() -ne $actualHash) {
        Fail "SHA256 do pacote do relay não confere"
    } else {
        Pass "pacote do relay íntegro ($actualHash)"
    }
}

$setup = Join-Path $PSScriptRoot "dist_installer\ConectaPC_Setup_v2.1.0.exe"
if (Test-Path -LiteralPath $setup) {
    $signature = Get-AuthenticodeSignature -LiteralPath $setup
    if ($signature.Status -eq "Valid") {
        Pass "Setup 2.1.0 possui assinatura válida"
    } elseif ($requiresProductionRelease) {
        Fail "Setup 2.1.0 não possui assinatura válida: $($signature.Status)"
    } else {
        Warn "Setup de homologação não está assinado: $($signature.Status)"
    }
} elseif ($Profile -eq "Preparation") {
    Warn "Setup 2.1.0 ainda não foi gerado"
} else {
    Fail "Setup 2.1.0 ainda não foi gerado"
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "PERFIL $Profile LIBERADO PELO PREFLIGHT" -ForegroundColor Green
    exit 0
}
Write-Host "PERFIL $Profile BLOQUEADO: $($failures.Count) requisito(s) obrigatório(s)." -ForegroundColor Red
exit 2
