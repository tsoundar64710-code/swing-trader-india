# Run the automated test suite and linter
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
Write-Host "==> pytest"
& ".venv\Scripts\python.exe" -m pytest
Write-Host "==> ruff check"
& ".venv\Scripts\python.exe" -m ruff check src tests
