"""StockSelectionStep — step 2 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback

from models import SelectedStock
from pipeline.backends.selectors import SELECTOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


class StockSelectionStep(PipelineStep):
    name = "stock_selection"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "finrl")

        # When --symbols is specified, skip stock selection — pass through
        symbols = ctx.cfg.get("pipeline", {}).get("symbols", [])
        if symbols:
            ctx.logger.info("StockSelectionStep: --symbols set, skipping ML selection (%d tickers)", len(symbols))
            return StepResult(
                step_name=self.name,
                status="success",
                summary={"backend": backend_name, "note": "skipped — using --symbols"},
                payload={"backend": backend_name, "tickers_ranked": [
                    {"ticker": s, "ml_score": 0.0} for s in symbols
                ]},
            )

        try:
            selector_cls = SELECTOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        selector_cfg = sub.get(backend_name, {})
        try:
            selector = selector_cls(cfg=selector_cfg)
            tickers = selector.select(ctx)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        now = dt.datetime.utcnow()
        with open_session(ctx) as session:
            rows = [SelectedStock(
                ticker=t.ticker,
                model_name=backend_name,
                ml_score=t.ml_score,
                bucket=t.bucket,
                weight=t.weight,
                date_selected=now.date(),
                pipeline_run_at=now,
                pipeline_run_id=ctx.run_id,
                sector=t.sector,
                backend=backend_name,
                predicted_return=t.predicted_return,
            ) for t in tickers]
            session.add_all(rows)
            session.commit()

        ranked = [
            {"ticker": t.ticker, "ml_score": t.ml_score, "sector": t.sector}
            for t in tickers
        ]
        summary = {
            "backend": backend_name,
            "count": len(tickers),
        }
        if not tickers:
            summary["note"] = "empty selection — downstream steps will short-circuit"

        return StepResult(
            step_name=self.name,
            status="success",
            summary=summary,
            payload={"backend": backend_name, "tickers_ranked": ranked},
        )
