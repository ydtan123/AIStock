"""StockSelector ABC + ScoredTicker + registry.

Concrete selectors (e.g. FinrlStockSelector) live in this module as well.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Type

from pipeline.base import StepContext


@dataclass
class ScoredTicker:
    ticker: str
    ml_score: float
    sector: str | None = None
    bucket: str | None = None
    weight: float | None = None
    predicted_return: float | None = None


class _Registry:
    def __init__(self, label: str):
        self._label = label
        self._items: dict[str, Type] = {}

    def register(self, cls: Type) -> Type:
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__} missing required 'name' attribute")
        self._items[cls.name] = cls
        return cls

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def get(self, name: str) -> Type:
        if name not in self._items:
            raise KeyError(f"unknown {self._label}: {name!r}")
        return self._items[name]

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def names(self) -> list[str]:
        return sorted(self._items)


SELECTOR_REGISTRY = _Registry("selector")


class StockSelector(ABC):
    name: str = ""

    def __init__(self):
        if not self.name:
            raise TypeError(
                f"{type(self).__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def select(self, ctx: StepContext) -> list[ScoredTicker]: ...


# --- Concrete backend: FinrlStockSelector ------------------------------------
# NOTE: sys.path hazard — external/FinRL-Trading/src/data/data_fetcher.py
# inserts itself at sys.path[0] on import. We pre-import AIStock's config/
# database/repository/models inside _run_finrl_runner before importing
# finrl_runner.

import logging

from repository import StockRepository

logger = logging.getLogger(__name__)


def _run_finrl_runner(
    cfg_overrides: dict,
    universe_index: str | None = None,
    universe_list: list[str] | None = None,
) -> dict:
    """Indirection seam — tests monkeypatch this."""
    import config  # noqa: F401
    import database  # noqa: F401
    import repository  # noqa: F401
    import models  # noqa: F401

    from finrl_runner import run_pipeline_and_save_report

    csv_path, selected_stocks = run_pipeline_and_save_report(
        cfg_overrides,
        universe_index=universe_index,
        universe_list=universe_list,
    )
    return {"csv_path": str(csv_path), "selected_stocks": selected_stocks}


@SELECTOR_REGISTRY.register
class FinrlStockSelector(StockSelector):
    name = "finrl"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def select(self, ctx: StepContext) -> list[ScoredTicker]:
        sub_cfg = self.cfg or ctx.cfg.get("stock_selection", {}).get("finrl", {})

        # Page-level universe multiselect (list) takes precedence
        pipeline_universe = ctx.cfg.get("pipeline", {}).get("universe")
        if pipeline_universe and isinstance(pipeline_universe, list):
            universe_list = pipeline_universe
            universe_index = None  # single-index path is subsumed
        else:
            universe_list = None
            universe = ctx.cfg.get("stock_selection", {}).get("universe")
            if universe and str(universe).strip() in ("", "All Active Stocks", "None"):
                universe = None
            universe_index = universe

        ctx.logger.info(
            "FinrlStockSelector starting with cfg=%s universe_index=%s universe_list=%s",
            sub_cfg, universe_index, universe_list,
        )
        result = _run_finrl_runner(
            sub_cfg, universe_index=universe_index, universe_list=universe_list,
        )
        selected_stocks = result.get("selected_stocks") or []

        if selected_stocks:
            out: list[ScoredTicker] = [
                ScoredTicker(
                    ticker=rec["ticker"],
                    ml_score=float(rec.get("ml_score") or 0.0),
                    sector=rec.get("bucket"),
                    bucket=rec.get("bucket"),
                    weight=float(rec["weight"]) if rec.get("weight") is not None else None,
                    predicted_return=float(rec.get("ml_score") or 0.0),
                )
                for rec in selected_stocks
            ]
        else:
            repo = StockRepository()
            rows = repo.get_latest_selected_stocks()
            out = [
                ScoredTicker(
                    ticker=row["ticker"],
                    ml_score=float(row.get("ml_score") or 0.0),
                    sector=row.get("sector") or row.get("bucket"),
                    bucket=row.get("bucket"),
                    weight=float(row["weight"]) if row.get("weight") is not None else None,
                    predicted_return=float(row.get("ml_score") or 0.0),
                )
                for row in rows
            ]
        ctx.logger.info("FinrlStockSelector produced %d tickers", len(out))
        return out
