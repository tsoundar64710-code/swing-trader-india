"""Validated application settings.

Settings are stored as JSON in the data directory. Secrets (API keys) are
never stored here or in the database; they may only be read from environment
variables when a future feature needs them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from swingtrader.core.errors import SettingsError

APP_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("SWINGTRADER_DATA_DIR", APP_DIR / "data"))
SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "swingtrader.db"


class RiskLimits(BaseModel):
    """Portfolio and per-trade risk limits (conservative defaults)."""

    max_capital_committed_pct: float = Field(50.0, gt=0, le=100)
    max_position_pct: float = Field(20.0, gt=0, le=100)
    max_portfolio_exposure_pct: float = Field(50.0, gt=0, le=100)
    max_risk_per_trade_pct: float = Field(1.0, gt=0, le=10)
    max_open_positions: int = Field(3, ge=1, le=50)
    max_drawdown_pct: float = Field(15.0, gt=0, le=100)
    daily_loss_limit_pct: float = Field(3.0, gt=0, le=100)
    loss_cooldown_sessions: int = Field(2, ge=0, le=60)
    min_avg_daily_value_inr: float = Field(1_000_000.0, ge=0)


class CostAssumptions(BaseModel):
    """Transaction-cost assumptions. Rates are dated in cost_config table;
    these are fallback defaults only and may be outdated — always shown to
    the user as estimates, never as guaranteed figures."""

    brokerage_pct: float = Field(0.03, ge=0)
    brokerage_min_inr: float = Field(20.0, ge=0)
    stt_buy_pct: float = Field(0.001, ge=0)
    stt_sell_pct: float = Field(0.001, ge=0)
    exchange_txn_charge_pct: float = Field(0.0000345, ge=0)
    gst_pct: float = Field(18.0, ge=0)
    sebi_charge_pct: float = Field(0.000001, ge=0)
    stamp_duty_buy_pct: float = Field(0.0015, ge=0)
    slippage_pct: float = Field(0.05, ge=0)
    config_verified_date: str = "UNVERIFIED"


class DataSettings(BaseModel):
    interval: str = "1d"
    timezone: str = "Asia/Kolkata"
    stale_after_days: int = Field(7, ge=1)
    max_import_rows: int = Field(500_000, ge=100, le=5_000_000)
    max_import_file_mb: float = Field(50.0, gt=0, le=500)


class StrategySettings(BaseModel):
    sma_fast: int = Field(20, ge=2)
    sma_slow: int = Field(50, ge=5)
    rsi_period: int = Field(14, ge=2)
    rsi_ob: float = Field(70.0, gt=0, lt=100)
    rsi_os: float = Field(30.0, gt=0, lt=100)
    atr_period: int = Field(14, ge=2)
    atr_stop_multiplier: float = Field(2.0, gt=0)
    min_reward_risk: float = Field(1.5, gt=0)
    volume_sma_period: int = Field(20, ge=2)

    @field_validator("sma_slow")
    @classmethod
    def _slow_gt_fast(cls, v: int, info: Any) -> int:
        fast = info.data.get("sma_fast")
        if fast is not None and v <= fast:
            raise ValueError("sma_slow must be greater than sma_fast")
        return v


class AppSettings(BaseModel):
    """Root settings object."""

    version: int = 1
    initial_capital_inr: float = Field(10_000.0, gt=0)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    data: DataSettings = Field(default_factory=DataSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    ai_explanation_enabled: bool = False  # optional LLM, off by default

    @property
    def live_trading_enabled(self) -> bool:
        """Always False in this release. Not user-configurable."""
        return False


def load_settings(path: Path | None = None) -> AppSettings:
    """Load settings from JSON, creating defaults on first run."""
    p = path or SETTINGS_PATH
    if not p.exists():
        s = AppSettings()
        save_settings(s, p)
        return s
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return AppSettings.model_validate(raw)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        raise SettingsError(
            f"Settings file is invalid: {p}. Fix or delete it to reset to defaults. ({exc})"
        ) from exc


def save_settings(s: AppSettings, path: Path | None = None) -> None:
    p = path or SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(p)


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Minimal .env loader (KEY=VALUE). Values are returned, never logged."""
    p = path or (APP_DIR / ".env")
    out: dict[str, str] = {}
    if not p.exists():
        return out
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        return out
    return out
