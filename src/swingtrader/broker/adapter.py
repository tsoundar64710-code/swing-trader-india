"""Broker adapter interface.

Phase 1 status: interface only. Every method that could place or modify a real
order raises NotImplementedError. Live trading is intentionally DISABLED and
must not be enabled without a separate reviewed plan (docs/GROWW_INTEGRATION_PLAN.md).
"""

from __future__ import annotations

from typing import Any

from swingtrader.core.errors import OrderError


class BrokerAdapter:
    """Abstract broker surface. No live implementation ships in this release."""

    name: str = "none"

    def place_order(self, *args: Any, **kwargs: Any) -> Any:
        raise OrderError(
            "Live order submission is DISABLED in this release. "
            "Use paper trading. See docs/GROWW_INTEGRATION_PLAN.md."
        )

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        raise OrderError("Live order cancellation is DISABLED in this release.")

    def get_positions(self, *args: Any, **kwargs: Any) -> Any:
        raise OrderError("Live broker position queries are DISABLED in this release.")

    def get_funds(self, *args: Any, **kwargs: Any) -> Any:
        raise OrderError("Live broker fund queries are DISABLED in this release.")


class DisabledGrowwAdapter(BrokerAdapter):
    """Placeholder for a future verified Groww adapter. Never constructed with credentials."""

    name = "groww-disabled"
