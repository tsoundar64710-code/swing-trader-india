# PowerShell setup for Windows 10/11
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

Write-Host "==> Creating virtual environment (.venv)"
if (-not (Test-Path ".venv")) { python -m venv .venv }

Write-Host "==> Installing pinned dependencies"
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "==> Installing package in editable mode"
& ".venv\Scripts\python.exe" -m pip install -e .

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "==> Created .env from .env.example (placeholders only)"
}

Write-Host "Setup complete. Next: .\scripts\run.ps1"
