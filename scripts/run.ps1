# Start the Flask app locally (loopback only — never expose to the internet)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
& ".venv\Scripts\python.exe" -m swingtrader.web.server
