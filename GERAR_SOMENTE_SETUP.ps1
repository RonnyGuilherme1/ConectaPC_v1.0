$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
. "$PSScriptRoot\ASSINATURA.ps1"

function Find-InnoSetupCompiler {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $registryPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    )

    foreach ($regPath in $registryPaths) {
        try {
            if (Test-Path $regPath) {
                $entry = Get-ItemProperty $regPath
                if ($entry.InstallLocation) {
                    $candidate = Join-Path $entry.InstallLocation "ISCC.exe"
                    if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
                }
            }
        } catch {}
    }

    return $null
}

if (-not (Test-Path "dist\ConectaPC\ConectaPC.exe")) {
    throw "dist\ConectaPC\ConectaPC.exe nao existe. Execute GERAR_INSTALADOR.bat primeiro."
}

Sign-ConectaPCArtifact (Join-Path $PSScriptRoot "dist\ConectaPC\ConectaPC.exe")

$iscc = Find-InnoSetupCompiler
if (-not $iscc) {
    throw "Inno Setup 6/ISCC.exe nao foi encontrado neste computador."
}

Write-Host "Inno Setup encontrado em:" -ForegroundColor Green
Write-Host $iscc -ForegroundColor DarkGray
Write-Host ""

Remove-Item -Recurse -Force "dist_installer" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "dist_installer" | Out-Null

& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao compilar o instalador."
}

$setup = Join-Path $PSScriptRoot "dist_installer\ConectaPC_Setup_v2.1.0.exe"
if (-not (Test-Path $setup)) {
    throw "O instalador nao foi criado."
}

Sign-ConectaPCArtifact $setup

Write-Host ""
Write-Host "Instalador criado:" -ForegroundColor Green
Write-Host $setup -ForegroundColor Yellow
