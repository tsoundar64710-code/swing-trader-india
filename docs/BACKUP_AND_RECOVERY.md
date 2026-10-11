# Backup and Recovery

## Automatic backup

```powershell
.\scripts\backup.ps1
```

Creates a timestamped copy in `data/backups/` with integrity check (`PRAGMA integrity_check`).

## Manual backup

1. Close the application
2. Copy `data/swingtrader.db` to a safe location
3. The WAL and SHM files (if present) can be ignored after clean shutdown

## Restore

1. Close the application
2. Replace `data/swingtrader.db` with your backup file
3. Start the application — migrations run automatically

The restore function verifies:
- Backup file is a valid SQLite database
- Backup schema version is compatible

## What's backed up

- Instruments and watchlist
- Imported candle data and metadata
- Signals and strategy configs
- Backtest runs and trades
- Paper-trading orders, fills, positions, cash ledger
- Journal entries
- Settings (also stored in `data/settings.json`)

## What's NOT backed up

- CSV import files (in `data/imports/`)
- Log files (in `data/logs/`)
- `.env` file (keep separately)
