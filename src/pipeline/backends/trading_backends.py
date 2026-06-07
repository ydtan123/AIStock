"""TradingBackend ABC + AlpacaTradingBackend wrapping AlpacaManager."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from pipeline.backends.selectors import _Registry
from pipeline.base import RegisteredBackend, StepContext

logger = logging.getLogger(__name__)

TRADING_REGISTRY = _Registry("trading")


class TradingBackend(RegisteredBackend):
    name: str = ""

    @abstractmethod
    def execute(
        self,
        target_weights: dict[str, float],
        dry_run: bool,
        ctx: StepContext,
    ) -> dict: ...


# --- Concrete: AlpacaTradingBackend -------------------------------------------


def _import_alpaca():
    """Lazy import with temporary FinRL path insertion."""
    import config  # noqa: F401
    import database  # noqa: F401
    import repository  # noqa: F401
    import models  # noqa: F401

    import sys
    from pathlib import Path
    _finrl_root = str(Path(__file__).resolve().parents[3] / "external" / "FinRL-Trading")
    _finrl_src = _finrl_root + "/src"

    saved = list(sys.path)
    for p in (_finrl_src, _finrl_root):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)

    try:
        from trading.trade_executor import create_trade_executor_from_env
    finally:
        sys.path[:] = saved
    return create_trade_executor_from_env


@TRADING_REGISTRY.register
class AlpacaTradingBackend(TradingBackend):
    name = "alpaca"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def execute(
        self,
        target_weights: dict[str, float],
        dry_run: bool,
        ctx: StepContext,
    ) -> dict:
        factory = _import_alpaca()
        executor = factory()

        ctx.logger.info("Alpaca executor initialised — accounts: %s",
                        executor.alpaca.get_available_accounts())

        plan = executor.alpaca.execute_portfolio_rebalance(
            target_weights,
            account_name="default",
            dry_run=dry_run,
        )

        buys = len(plan.get("orders_plan", {}).get("buy", []))
        sells = len(plan.get("orders_plan", {}).get("sell", []))
        ctx.logger.info("Rebalance plan: %d buys, %d sells (dry_run=%s)", buys, sells, dry_run)

        return {
            "dry_run": dry_run,
            "market_open": plan.get("market_open"),
            "buys": buys,
            "sells": sells,
            "orders_plan": plan.get("orders_plan", {}),
        }
