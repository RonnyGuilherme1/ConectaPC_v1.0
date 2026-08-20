@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0GERAR_INSTALADOR.ps1"
if errorlevel 1 (
    echo.
    echo O build terminou com erro.
    pause
)
