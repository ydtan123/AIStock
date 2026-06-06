"""DataUpdateStep — refreshes price/indicator/fundamental data."""
from __future__ import annotations

import time
import traceback

from pipeline.base import PipelineStep, StepContext, StepResult


def _run_pipeline(source: str, step_cfg: dict, full_cfg: dict) -> dict:
    """Indirection seam — tests monkeypatch this."""
    from fetcher import create_fetcher
    from ingestion.pipeline import run_daily_pipeline

    cfg = dict(full_cfg)  # shallow copy to avoid mutating orchestrator's config
    cfg["source"] = source
    # Bridge OOP namespaced config → flat format create_fetcher expects.
    for key in ("alpha_vantage",):
        if key in step_cfg and key not in cfg:
            cfg[key] = step_cfg[key]
    fetcher = create_fetcher(cfg)

    pipeline_cfg = full_cfg.get("pipeline", {})
    # --symbols takes precedence over --universe
    symbols = pipeline_cfg.get("symbols") or None
    universe_label = None
    if not symbols:
        universe_list = pipeline_cfg.get("universe")
        if universe_list:
            from repository import StockRepository
            repo = StockRepository()
            universe_syms, _ = repo.resolve_universe_to_symbols(universe_list)
            symbols = sorted(universe_syms)
            universe_label = ", ".join(universe_list)

    result = run_daily_pipeline(
        fetcher, symbols=symbols, universe_label=universe_label,
    )
    symbols = result.get("symbols", [])
    failed_symbols = [s["symbol"] for s in symbols if s.get("error")]
    return {
        "symbols_attempted": result.get("processed", 0),
        "symbols_succeeded": result.get("processed", 0) - result.get("errors", 0),
        "symbols_failed": result.get("errors", 0),
        "failed_symbols": failed_symbols,
    }


class DataUpdateStep(PipelineStep):
    name = "data_update"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        source = sub.get("source", "alpha_vantage")
        start = time.monotonic()

        try:
            stats = _run_pipeline(source, sub, ctx.cfg)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"source": source},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        duration = time.monotonic() - start
        attempted = stats["symbols_attempted"]
        failed = stats["symbols_failed"]
        succeeded = stats["symbols_succeeded"]
        status = "failed" if (attempted > 0 and succeeded == 0) else "success"

        summary = {
            "source": source,
            "symbols_attempted": attempted,
            "symbols_succeeded": succeeded,
            "symbols_failed": failed,
            "failed_symbols": stats["failed_symbols"],
            "duration_s": round(duration, 2),
        }
        return StepResult(
            step_name=self.name,
            status=status,
            summary=summary,
        )
