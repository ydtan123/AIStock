"""BacktestBackend ABC + FinrlBacktestBackend wrapping BacktestEngine."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from pipeline.backends.selectors import _Registry
from pipeline.base import RegisteredBackend, StepContext

logger = logging.getLogger(__name__)

BACKTEST_REGISTRY = _Registry("backtest")


class BacktestBackend(RegisteredBackend):
    name: str = ""

    @abstractmethod
    def run_backtest(
        self,
        tickers: list[str],
        weights: dict[str, float],
        start_date: str,
        end_date: str,
        ctx: StepContext,
    ) -> dict: ...


# --- Concrete: FinrlBacktestBackend ---------------------------------------------


def _fetch_price_data_from_db(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Read daily_prices from AIStock DB, return wide-format DataFrame (dates x tickers)."""
    from repository import StockRepository

    repo = StockRepository()
    prices: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        rows = repo.get_daily_prices_by_ticker(ticker, start, end)
        for row in rows:
            date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
            prices.setdefault(date_str, {})[ticker] = row["close"]
    if not prices:
        raise ValueError(f"No price data found for {len(tickers)} tickers in [{start}, {end}]")
    df = pd.DataFrame.from_dict(prices, orient="index").sort_index()
    df.index = pd.to_datetime(df.index)
    return df


def _build_weight_signals(
    daily_prices_df: pd.DataFrame,
    target_weights: dict[str, float],
    rebalance_date: str,
) -> pd.DataFrame:
    """Create a weight-signal DataFrame: one row per trading day from *rebalance_date* onward.

    Each row holds the same target weights, re-normalized to tickers with prices that day.
    """
    trading_days = daily_prices_df.index[daily_prices_df.index >= rebalance_date]
    if len(trading_days) == 0:
        raise ValueError(f"No trading data on or after {rebalance_date}")

    tickers = [t for t in target_weights if t in daily_prices_df.columns]
    ws = pd.DataFrame(0.0, index=trading_days, columns=list(daily_prices_df.columns))
    for t in tickers:
        ws[t] = target_weights[t]
    # Row-normalise (drop days where all target tickers are NaN)
    ws = ws.div(ws.sum(axis=1), axis=0).fillna(0.0)
    return ws


@BACKTEST_REGISTRY.register
class FinrlBacktestBackend(BacktestBackend):
    name = "finrl_bt"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    # ------------------------------------------------------------------
    # sys.path hazard: FinRL-Trading src inserts itself at sys.path[0].
    # Pre-import AIStock modules before touching FinRL.
    # ------------------------------------------------------------------
    @staticmethod
    def _import_finrl():
        import config  # noqa: F401
        import database  # noqa: F401
        import repository  # noqa: F401
        import models  # noqa: F401

        from backtest.backtest_engine import BacktestConfig, BacktestEngine
        return BacktestConfig, BacktestEngine

    def run_backtest(
        self,
        tickers: list[str],
        weights: dict[str, float],
        start_date: str,
        end_date: str,
        ctx: StepContext,
    ) -> dict:
        BacktestConfig, BacktestEngine = self._import_finrl()

        sub = self.cfg or ctx.cfg.get("backtest", {}).get("finrl_bt", {})
        benchmarks = list(sub.get("benchmarks", ["SPY", "QQQ"]))
        initial_capital = float(sub.get("initial_capital", 1_000_000))
        rebalance_freq = sub.get("rebalance_freq", "Q")

        cfg = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            rebalance_freq=rebalance_freq,
            initial_capital=initial_capital,
            benchmark_tickers=benchmarks,
        )

        # Fetch price data: strategy tickers + benchmark tickers
        all_tickers = list(dict.fromkeys(tickers + benchmarks))  # dedup preserving order
        ctx.logger.info("Fetching price data for %d tickers (%s → %s)", len(all_tickers), start_date, end_date)
        price_data = _fetch_price_data_from_db(all_tickers, start_date, end_date)
        ctx.logger.info("Price data: %d days × %d tickers", len(price_data), len(price_data.columns))

        weight_signals = _build_weight_signals(price_data, weights, start_date)

        engine = BacktestEngine(cfg)
        result = engine.run_backtest("ML Weights Strategy", price_data, weight_signals)

        return {
            "annual_return": result.annualized_return,
            "metrics": result.metrics,
            "benchmark_annualized": result.benchmark_annualized,
            "benchmark_metrics": result.benchmark_metrics,
            "start_date": start_date,
            "end_date": end_date,
            "num_tickers": len(tickers),
            "initial_capital": initial_capital,
            "final_value": float(result.portfolio_values.iloc[-1]) if len(result.portfolio_values) > 0 else None,
        }
