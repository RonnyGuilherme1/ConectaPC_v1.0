$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
. "$PSScriptRoot\ASSINATURA.ps1"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " ConectaPC 2.1.0 - Gerador de Instalador Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

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
    if ($cmd) {
        return $cmd.Source
    }

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
                    if (Test-Path $candidate) {
                        return (Resolve-Path $candidate).Path
                    }
                }
            }
        } catch {}
    }

    # Busca final limitada a locais comuns.
    $roots = @(
        "${env:ProgramFiles(x86)}",
        "${env:ProgramFiles}",
        "${env:LOCALAPPDATA}\Programs"
    )

    foreach ($root in $roots) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        try {
            $found = Get-ChildItem `
                -Path $root `
                -Filter "ISCC.exe" `
                -File `
                -Recurse `
                -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match "Inno Setup" } |
                Select-Object -First 1

            if ($found) {
                return $found.FullName
            }
        } catch {}
    }

    return $null
}

$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
}

if (-not $python) {
    throw "Python 3.11+ nao foi encontrado no computador de desenvolvimento."
}

Write-Host "[1/5] Preparando ambiente isolado..." -ForegroundColor Green
if (-not (Test-Path ".buildenv")) {
    & $python -m venv .buildenv
}
$venvPython = Join-Path $PSScriptRoot ".buildenv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "O ambiente virtual nao foi criado corretamente."
}

Write-Host "[2/5] Verificando dependencias de compilacao..." -ForegroundColor Green
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip." }

& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias do ConectaPC." }

& $venvPython -m pip install pyinstaller==6.22.2
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar PyInstaller." }

Write-Host "[3/5] Gerando ConectaPC.exe..." -ForegroundColor Green
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue

$pyiArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", "ConectaPC",
    "--icon", "assets\conectapc.ico",
    "--version-file", "version_info.txt",
    "--add-data", "assets;assets",
    "--add-data", "relay_config.json;."
)

if (Test-Path "relay.crt") {
    $pyiArgs += @("--add-data", "relay.crt;.")
}

$pyiArgs += "app.py"
& $venvPython -m PyInstaller @pyiArgs

if ($LASTEXITCODE -ne 0) {
    throw "O PyInstaller terminou com erro."
}

if (-not (Test-Path "dist\ConectaPC\ConectaPC.exe")) {
    throw "Falha ao gerar dist\ConectaPC\ConectaPC.exe"
}

Sign-ConectaPCArtifact (Join-Path $PSScriptRoot "dist\ConectaPC\ConectaPC.exe")

Write-Host "[4/5] Localizando Inno Setup..." -ForegroundColor Green
$iscc = Find-InnoSetupCompiler

if (-not $iscc) {
    Write-Host "Inno Setup 6 nao encontrado." -ForegroundColor Yellow

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Instalando Inno Setup 6 via winget..." -ForegroundColor Yellow

        & winget install `
            --id JRSoftware.InnoSetup `
            -e `
            --silent `
            --accept-source-agreements `
            --accept-package-agreements

        if ($LASTEXITCODE -ne 0) {
            Write-Host "O winget retornou codigo $LASTEXITCODE." -ForegroundColor Yellow
        }

        # O instalador pode terminar antes do arquivo ficar visivel para o processo atual.
        Write-Host "Aguardando o Inno Setup ficar disponivel..." -ForegroundColor DarkGray
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 2
            $iscc = Find-InnoSetupCompiler
            if ($iscc) { break }
        }
    }
}

if (-not $iscc) {
    Write-Host ""
    Write-Host "Nao foi possivel localizar o compilador do Inno Setup." -ForegroundColor Red
    Write-Host ""
    Write-Host "O ConectaPC.exe JA FOI GERADO com sucesso em:" -ForegroundColor Yellow
    Write-Host "  $PSScriptRoot\dist\ConectaPC\ConectaPC.exe" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Se o Inno Setup acabou de ser instalado, feche esta janela" -ForegroundColor White
    Write-Host "e execute GERAR_INSTALADOR.bat novamente." -ForegroundColor White
    Write-Host ""
    throw "ISCC.exe nao encontrado."
}

Write-Host "Inno Setup encontrado:" -ForegroundColor DarkGray
Write-Host "  $iscc" -ForegroundColor DarkGray

Write-Host "[5/5] Gerando instalador final..." -ForegroundColor Green
Remove-Item -Recurse -Force "dist_installer" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "dist_installer" | Out-Null

& $iscc "installer.iss"

if ($LASTEXITCODE -ne 0) {
    throw "O compilador do Inno Setup terminou com erro."
}

$setup = Join-Path $PSScriptRoot "dist_installer\ConectaPC_Setup_v2.1.0.exe"
if (-not (Test-Path $setup)) {
    throw "O instalador final nao foi gerado."
}

Sign-ConectaPCArtifact $setup

$hash = (Get-FileHash $setup -Algorithm SHA256).Hash
$hashFile = Join-Path $PSScriptRoot "dist_installer\SHA256.txt"
"ConectaPC_Setup_v2.1.0.exe  SHA256=$hash" | Set-Content $hashFile -Encoding UTF8

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " INSTALADOR GERADO COM SUCESSO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Arquivo final:" -ForegroundColor White
Write-Host "  $setup" -ForegroundColor Yellow
Write-Host ""
Write-Host "SHA256:" -ForegroundColor White
Write-Host "  $hash" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Esse e o unico arquivo que precisa ser enviado ao cliente." -ForegroundColor Green
Write-Host ""
