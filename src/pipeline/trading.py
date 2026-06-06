"""TradingStep — step 6: dry-run or submit portfolio rebalance via Alpaca."""
from __future__ import annotations

import json
import traceback

from models import TradingResult as TradingResultModel
from pipeline.backends.trading_backends import TRADING_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


class TradingStep(PipelineStep):
    name = "trading"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)

        # ---- guard: check for Alpaca keys early --------------------------------
        auto_submit = sub.get("auto_submit", False)
        if not _has_alpaca_keys():
            return StepResult(
                step_name=self.name,
                status="failed" if auto_submit else "skipped",
                summary={"reason": "Alpaca API keys not configured"},
            )

        backend_name = sub.get("backend", "alpaca")
        backend_cls = TRADING_REGISTRY.get(backend_name)
        backend = backend_cls(sub)

        # Read weights from DB (same as backtest)
        weights = _load_weights_from_db(ctx)
        if not weights:
            return StepResult(
                step_name=self.name,
                status="skipped",
                summary={"reason": "no selected stocks with weights found"},
            )

        ctx.logger.info(
            "Trading step: %d tickers, auto_submit=%s",
            len(weights), auto_submit,
        )

        try:
            result = backend.execute(weights, dry_run=not auto_submit, ctx=ctx)
        except Exception:
            _persist_result(ctx, len(weights), status="failed", error=traceback.format_exc())
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=traceback.format_exc(),
            )

        execution_mode = "submitted" if auto_submit else "dry_run"
        _persist_result(
            ctx, len(weights),
            status="executed",
            buys=result.get("buys"),
            sells=result.get("sells"),
            orders_json=json.dumps(result.get("orders_plan", {}), default=str),
            mode=execution_mode,
        )

        _write_report(ctx, result, backend_name, execution_mode, weights)

        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "mode": execution_mode,
                "tickers": len(weights),
                "buys": result.get("buys"),
                "sells": result.get("sells"),
            },
        )


# -- helpers ------------------------------------------------------------------


def _load_weights_from_db(ctx: StepContext) -> dict[str, float]:
    with open_session(ctx) as s:
        from models import SelectedStock
        rows = (
            s.query(SelectedStock)
            .filter_by(pipeline_run_id=ctx.run_id)
            .filter(SelectedStock.weight.isnot(None))
            .filter(SelectedStock.weight > 0)
            .all()
        )
        weights = {r.ticker: float(r.weight) for r in rows}
        total = sum(weights.values())
        if total > 0:
            weights = {t: w / total for t, w in weights.items()}
        return weights


def _has_alpaca_keys() -> bool:
    import os
    return bool(
        os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    )


def _persist_result(
    ctx: StepContext, num_tickers: int,
    status: str = "pending",
    buys: int | None = None,
    sells: int | None = None,
    orders_json: str | None = None,
    error: str | None = None,
    mode: str = "dry_run",
) -> None:
    with open_session(ctx) as s:
        row = TradingResultModel(
            pipeline_run_id=ctx.run_id,
            execution_mode=mode,
            status=status,
            buys=buys,
            sells=sells,
            orders_json=orders_json,
            error_message=error,
        )
        s.add(row)
        s.commit()


def _write_report(
    ctx: StepContext, result: dict, backend_name: str,
    mode: str, weights: dict[str, float],
) -> None:
    json_path = ctx.report_dir / f"{TradingStep.name}.json"
    json_path.write_text(json.dumps({
        "backend": backend_name,
        "mode": mode,
        "tickers": len(weights),
        "results": result,
    }, indent=2, default=str))

    md = [
        f"# Trading Report",
        "",
        f"**Backend:** {backend_name}",
        f"**Mode:** {mode}",
        f"**Tickers:** {len(weights)}",
        f"**Buys:** {result.get('buys', '?')}",
        f"**Sells:** {result.get('sells', '?')}",
        f"**Market Open:** {result.get('market_open', '?')}",
        "",
        "## Target Weights",
        "| Ticker | Weight |",
        "|---|---|",
    ]
    for t, w in sorted(weights.items(), key=lambda x: -x[1]):
        md.append(f"| {t} | {w:.4%} |")
    (ctx.report_dir / f"{TradingStep.name}.md").write_text("\n".join(md))
