# Start the app locally (loopback only — never expose to the internet)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
& ".venv\Scripts\python.exe" -m streamlit run "src\swingtrader\ui\app.py" `
  --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
