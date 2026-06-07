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


def _ensure_finrl_path() -> list:
    """Temporarily insert FinRL paths; returns saved path list for restore."""
    import sys
    from pathlib import Path
    _finrl_root = str(Path(__file__).resolve().parents[3] / "external" / "FinRL-Trading")
    _finrl_src = _finrl_root + "/src"
    _finrl_trading = _finrl_src + "/trading"

    saved = list(sys.path)
    for p in (_finrl_trading, _finrl_src, _finrl_root):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    return saved


def _restore_path(saved: list) -> None:
    import sys
    sys.path[:] = saved


@TRADING_REGISTRY.register
class AlpacaTradingBackend(TradingBackend):
    name = "alpaca"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def _get_alpaca_manager(self):
        """Return AlpacaManager configured from trading config section."""
        from trading.alpaca_manager import AlpacaManager, AlpacaAccount

        trading_cfg = self.cfg or {}
        mode = trading_cfg.get("alpaca_mode", "paper")
        api_key = trading_cfg.get(f"alpaca_api_key_{mode}") or trading_cfg.get("alpaca_api_key")
        api_secret = (
            trading_cfg.get(f"alpaca_api_secret_{mode}")
            or trading_cfg.get("alpaca_api_secret")
        )
        base_url = (
            trading_cfg.get(f"alpaca_base_url_{mode}")
            or trading_cfg.get("alpaca_base_url")
            or "https://paper-api.alpaca.markets"
        ).rstrip("/v2").rstrip("/")
        if not api_key or not api_secret:
            missing = []
            if not api_key:
                missing.append(f"alpaca_api_key_{mode}")
            if not api_secret:
                missing.append(f"alpaca_api_secret_{mode}")
            raise ValueError(
                f"Alpaca {mode} credentials incomplete: missing {', '.join(missing)}. "
                f"Set trading.alpaca_api_key_{mode} and trading.alpaca_api_secret_{mode} in config.yaml"
            )
        account = AlpacaAccount(
            name="default",
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
        )
        return AlpacaManager([account])

    def fetch_account_snapshot(self, ctx: StepContext) -> dict:
        """Return current Alpaca account state without generating a rebalance plan."""
        saved = _ensure_finrl_path()
        try:
            mgr = self._get_alpaca_manager()
            acct = mgr.get_account_info("default")
            positions = mgr.get_positions("default")
            return {
                "cash": float(acct.get("cash", 0)),
                "equity": float(acct.get("portfolio_value", 0)),
                "buying_power": float(acct.get("buying_power", 0)),
                "positions": [
                    {
                        "symbol": p["symbol"],
                        "qty": float(p["qty"]),
                        "market_value": float(p["market_value"]),
                        "avg_entry_price": float(p["avg_entry_price"]),
                    }
                    for p in positions
                ],
            }
        finally:
            _restore_path(saved)

    def execute(
        self,
        target_weights: dict[str, float],
        dry_run: bool,
        ctx: StepContext,
    ) -> dict:
        saved = _ensure_finrl_path()
        try:
            mgr = self._get_alpaca_manager()
            ctx.logger.info("Alpaca manager initialised — account: default")

            # Snapshot account state BEFORE rebalance
            acct = mgr.get_account_info("default")
            positions = mgr.get_positions("default")
            account_info = {
                "cash": float(acct.get("cash", 0)),
                "equity": float(acct.get("portfolio_value", 0)),
                "buying_power": float(acct.get("buying_power", 0)),
                "positions": [
                    {
                        "symbol": p["symbol"],
                        "qty": float(p["qty"]),
                        "market_value": float(p["market_value"]),
                        "avg_entry_price": float(p["avg_entry_price"]),
                    }
                    for p in positions
                ],
            }

            plan = mgr.execute_portfolio_rebalance(
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
                "account_info": account_info,
            }
        finally:
            _restore_path(saved)
