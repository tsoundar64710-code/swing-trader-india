"""No real order can be placed in this release."""

from __future__ import annotations

import pytest

from swingtrader import LIVE_TRADING_ENABLED
from swingtrader.broker.adapter import BrokerAdapter, DisabledGrowwAdapter
from swingtrader.core.errors import OrderError


def test_release_flag_disables_live_trading() -> None:
    assert LIVE_TRADING_ENABLED is False


@pytest.mark.parametrize("cls", [BrokerAdapter, DisabledGrowwAdapter])
@pytest.mark.parametrize(
    "method,args",
    [
        ("place_order", ({"symbol": "RELIANCE", "side": "BUY", "qty": 1},)),
        ("cancel_order", (1,)),
        ("get_positions", ()),
        ("get_funds", ()),
    ],
)
def test_all_broker_methods_blocked(cls, method, args) -> None:
    with pytest.raises(OrderError):
        getattr(cls(), method)(*args)
