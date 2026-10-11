# Backup the SQLite database to data/backups with integrity check
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
& ".venv\Scripts\python.exe" -c @"
import sys; sys.path.insert(0, 'src')
from pathlib import Path
from swingtrader.db.database import backup_database
from swingtrader.core.settings import DB_PATH, DATA_DIR
if not DB_PATH.exists():
    print('No database yet at', DB_PATH); sys.exit(0)
p = backup_database(DB_PATH, DATA_DIR / 'backups')
print('Backup OK:', p)
"@
