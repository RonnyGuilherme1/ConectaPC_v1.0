function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kits) {
        $candidate = Get-ChildItem -LiteralPath $kits -Filter signtool.exe -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    return $null
}

function Sign-ConectaPCArtifact {
    param([Parameter(Mandatory=$true)][string]$Path)

    $releaseRequired = $env:CONECTAPC_RELEASE -eq "1"
    $pfx = $env:CONECTAPC_SIGN_PFX
    if (-not $pfx) {
        if ($releaseRequired) {
            throw "Release bloqueado: configure CONECTAPC_SIGN_PFX e CONECTAPC_SIGN_PASSWORD."
        }
        Write-Host "Build de desenvolvimento sem assinatura: $Path" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path -LiteralPath $pfx)) { throw "Certificado PFX não encontrado." }
    $signTool = Find-SignTool
    if (-not $signTool) { throw "signtool.exe não encontrado no Windows SDK." }

    $arguments = @(
        "sign", "/fd", "SHA256", "/td", "SHA256",
        "/tr", "http://timestamp.digicert.com", "/f", $pfx
    )
    if ($env:CONECTAPC_SIGN_PASSWORD) {
        $arguments += @("/p", $env:CONECTAPC_SIGN_PASSWORD)
    }
    $arguments += $Path
    & $signTool @arguments
    if ($LASTEXITCODE -ne 0) { throw "Falha ao assinar $Path" }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne "Valid") {
        throw "Assinatura Authenticode inválida em ${Path}: $($signature.Status)"
    }
    Write-Host "Assinatura verificada: $Path" -ForegroundColor Green
}
