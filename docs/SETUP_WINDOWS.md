# Setup (Windows 10/11)

## Prerequisites

- Python 3.12+ (tested on 3.14.7). Download from https://python.org if needed.
- Git (optional, for cloning)

## One-time setup

```powershell
cd "C:\path\to\swing-trader-india"
.\scripts\setup.ps1
```

This creates `.venv`, installs dependencies, and copies `.env.example` → `.env`.

## Manual setup (if scripts are blocked)

```powershell
cd "C:\path\to\swing-trader-india"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

## Start the app

```powershell
.\scripts\run.ps1
```

Or double-click `scripts\start_app.bat`.

Opens at **http://127.0.0.1:8501**.

## Run tests

```powershell
.\scripts\test.ps1
```

## Backup database

```powershell
.\scripts\backup.ps1
```

## Troubleshooting

| Problem | Fix |
|---|---|
| "python not found" | Install Python 3.12+ and check "Add to PATH" during install |
| Port 8501 in use | Change port in `src/swingtrader/web/server.py` |
| Blank page | Check browser console; ensure Flask is running |
| Import errors | Run `.\.venv\Scripts\python.exe -m pip install -e .` |
| Tests fail | Run `.\.venv\Scripts\python.exe -m pytest -v` for details |
