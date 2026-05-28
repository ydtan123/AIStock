"""DataUpdateStep — refreshes price/indicator/fundamental data."""
from __future__ import annotations

import time
import traceback

from pipeline.base import PipelineStep, StepContext, StepResult


def _run_pipeline(source: str, step_cfg: dict) -> dict:
    """Indirection seam — tests monkeypatch this."""
    from config import load_config
    from fetcher import create_fetcher
    from ingestion.pipeline import run_daily_pipeline

    cfg = load_config()
    cfg["source"] = source
    # Bridge OOP namespaced config → flat format create_fetcher expects.
    # step_cfg is the data_update namespace; alpha_vantage may live there.
    for key in ("alpha_vantage",):
        if key in step_cfg and key not in cfg:
            cfg[key] = step_cfg[key]
    fetcher = create_fetcher(cfg)
    result = run_daily_pipeline(fetcher)
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
            stats = _run_pipeline(source, sub)
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
