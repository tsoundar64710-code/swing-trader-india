"""Settings validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from swingtrader.core.errors import SettingsError
from swingtrader.core.settings import AppSettings, load_settings, save_settings


def test_defaults_are_conservative(settings: AppSettings) -> None:
    assert settings.initial_capital_inr == 10_000
    assert settings.risk.max_risk_per_trade_pct <= 2.0
    assert settings.ai.enabled is False
    assert settings.live_trading_enabled is False


def test_live_trading_never_enabled() -> None:
    s = AppSettings()
    assert s.live_trading_enabled is False  # property, no public setter
    with pytest.raises(AttributeError):
        s.live_trading_enabled = True  # type: ignore[misc]


def test_invalid_strategy_params_rejected() -> None:
    with pytest.raises(ValidationError):
        AppSettings.model_validate({"strategy": {"sma_fast": 50, "sma_slow": 20}})


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    s = AppSettings(initial_capital_inr=25_000)
    save_settings(s, p)
    loaded = load_settings(p)
    assert loaded.initial_capital_inr == 25_000


def test_corrupt_settings_raise_clear_error(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(p)


def test_first_run_creates_defaults(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    s = load_settings(p)
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == 1
    assert s.risk.max_open_positions >= 1
