@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0GERAR_SOMENTE_SETUP.ps1"
if errorlevel 1 (
    echo.
    echo Falha ao gerar o Setup.
    pause
)
