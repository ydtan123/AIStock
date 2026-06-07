"""BacktestStep — step 5: historical backtest of ML-selected portfolio."""
from __future__ import annotations

import json
import traceback
from datetime import datetime

from models import BacktestResult as BacktestResultModel
from pipeline.backends.backtest_backends import BACKTEST_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


_DEFAULT_WINDOW = "latest"  # "latest" | "full"


class BacktestStep(PipelineStep):
    name = "backtest"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "finrl_bt")
        backend_cls = BACKTEST_REGISTRY.get(backend_name)
        backend = backend_cls(sub)

        # Read weights from configured source
        source_cfg = sub.get("stock_source", {})
        source_type = source_cfg.get("type", "stock_selection")
        if source_type == "fast_evaluation":
            min_consensus = float(source_cfg.get("min_consensus", 0.0))
            tickers, weights = _load_from_fast_eval(ctx, min_consensus)
        elif source_type == "deep_evaluation":
            decision = source_cfg.get("decision", "BUY")
            tickers, weights = _load_from_deep_eval(ctx, decision)
        else:
            tickers, weights = _load_weights_from_db(ctx)

        if not tickers:
            return StepResult(
                step_name=self.name,
                status="skipped",
                summary={"reason": f"no stocks found from source={source_type}"},
            )
        ctx.logger.info("Backtest source=%s: %d tickers", source_type, len(tickers))

        window = sub.get("window", _DEFAULT_WINDOW)
        if window == "latest":
            start_date = _infer_date(ctx, tickers)
        else:
            start_date = ctx.cfg.get("stock_selection", {}).get("finrl", {}).get("start_date", "2020-01-01")

        end_date = _latest_trading_date(ctx, tickers[0])

        ctx.logger.info(
            "Backtest starting: %d tickers, window=%s, %s → %s",
            len(tickers), window, start_date, end_date,
        )

        try:
            bt_result = backend.run_backtest(tickers, weights, start_date, end_date, ctx)
        except Exception:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name, "tickers": len(tickers)},
                error=traceback.format_exc(),
            )

        # Persist to DB
        _persist_result(ctx, bt_result)

        # Write report files
        _write_report(ctx, bt_result, backend_name)

        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "tickers": len(tickers),
                "start_date": bt_result["start_date"],
                "end_date": bt_result["end_date"],
                "annual_return": bt_result["annual_return"],
                "metrics": bt_result["metrics"],
                "benchmark_annualized": bt_result["benchmark_annualized"],
            },
        )


# -- helpers ------------------------------------------------------------------


def _load_from_fast_eval(ctx: StepContext, min_consensus: float) -> tuple[list[str], dict[str, float]]:
    """Return tickers with bullish consensus from fast_evaluation_conclusion."""
    with open_session(ctx) as s:
        from models import FastEvaluationConclusion
        rows = (
            s.query(FastEvaluationConclusion)
            .filter_by(pipeline_run_id=ctx.run_id)
            .filter(FastEvaluationConclusion.consensus_score >= min_consensus)
            .all()
        )
        if not rows:
            ctx.logger.warning(
                "No stocks with consensus >= %s in fast_evaluation for run %d",
                min_consensus, ctx.run_id,
            )
            return [], {}
        tickers = [r.ticker for r in rows]
        # Equal weight
        w = 1.0 / len(tickers)
        return tickers, {t: w for t in tickers}


def _load_from_deep_eval(ctx: StepContext, decision: str) -> tuple[list[str], dict[str, float]]:
    """Return tickers whose final_decision contains *decision* (case-insensitive)."""
    with open_session(ctx) as s:
        from models import DeepEvaluationRow
        rows = (
            s.query(DeepEvaluationRow)
            .filter_by(pipeline_run_id=ctx.run_id)
            .all()
        )
        matches = [
            r for r in rows
            if r.final_decision and decision.lower() in r.final_decision.lower()
        ]
        if not matches:
            ctx.logger.warning(
                "No stocks with decision containing '%s' in deep_evaluation for run %d",
                decision, ctx.run_id,
            )
            return [], {}
        tickers = [r.ticker for r in matches]
        w = 1.0 / len(tickers)
        return tickers, {t: w for t in tickers}


def _load_weights_from_db(ctx: StepContext) -> tuple[list[str], dict[str, float]]:
    """Return (tickers, {ticker: weight}) from selected_stocks for this run."""
    with open_session(ctx) as s:
        from models import SelectedStock
        rows = (
            s.query(SelectedStock)
            .filter_by(pipeline_run_id=ctx.run_id)
            .filter(SelectedStock.weight.isnot(None))
            .filter(SelectedStock.weight > 0)
            .all()
        )
        tickers = [r.ticker for r in rows]
        weights = {r.ticker: float(r.weight) for r in rows}
        # Normalise
        total = sum(weights.values())
        if total > 0:
            weights = {t: w / total for t, w in weights.items()}
        return tickers, weights


def _infer_date(ctx: StepContext, tickers: list[str]) -> str:
    """Infer the rebalance date from config or the latest selected_stock date."""
    # Use config end_date (ML training end) as the rebalance start
    finrl_cfg = ctx.cfg.get("stock_selection", {}).get("finrl", {})
    end_date = finrl_cfg.get("end_date") or finrl_cfg.get("start_date") or "2020-01-01"
    return end_date


def _latest_trading_date(ctx: StepContext, ticker: str) -> str:
    """Return the most recent trading date available in daily_prices."""
    from repository import StockRepository
    repo = StockRepository()
    rows = repo.get_daily_prices_by_ticker(ticker, "2020-01-01", "2099-01-01")
    if rows:
        return rows[-1]["date"].strftime("%Y-%m-%d") if hasattr(rows[-1]["date"], "strftime") else str(rows[-1]["date"])[:10]
    return datetime.now().strftime("%Y-%m-%d")


def _persist_result(ctx: StepContext, bt_result: dict) -> None:
    """Write backtest metrics to backtest_results table."""
    with open_session(ctx) as s:
        row = BacktestResultModel(
            pipeline_run_id=ctx.run_id,
            annual_return=bt_result.get("annual_return"),
            sharpe_ratio=bt_result.get("metrics", {}).get("sharpe_ratio"),
            sortino_ratio=bt_result.get("metrics", {}).get("sortino_ratio"),
            max_drawdown=bt_result.get("metrics", {}).get("max_drawdown"),
            volatility=bt_result.get("metrics", {}).get("volatility"),
            calmar_ratio=bt_result.get("metrics", {}).get("calmar_ratio"),
            start_date=bt_result.get("start_date"),
            end_date=bt_result.get("end_date"),
            initial_capital=bt_result.get("initial_capital"),
            final_value=bt_result.get("final_value"),
            num_tickers=bt_result.get("num_tickers"),
            benchmark_metrics=json.dumps(bt_result.get("benchmark_metrics", {}), default=str),
        )
        s.add(row)
        s.commit()


def _write_report(ctx: StepContext, bt_result: dict, backend_name: str) -> None:
    json_path = ctx.report_dir / f"{BacktestStep.name}.json"
    json_path.write_text(json.dumps(bt_result, indent=2, default=str))

    md = [
        f"# Backtest Report",
        "",
        f"**Backend:** {backend_name}",
        f"**Period:** {bt_result['start_date']} → {bt_result['end_date']}",
        f"**Tickers:** {bt_result.get('num_tickers', '?')}",
        f"**Annual Return:** {bt_result.get('annual_return', 0):.4%}" if bt_result.get('annual_return') is not None else "",
        "",
        "## Strategy Metrics",
        "| Metric | Value |",
        "|---|---|",
    ]
    for k, v in (bt_result.get("metrics") or {}).items():
        md.append(f"| {k} | {v:.4f} |" if isinstance(v, float) else f"| {k} | {v} |")
    md.append("")
    md.append("## Benchmark Comparison")
    bm = bt_result.get("benchmark_annualized") or {}
    if bm:
        md.append("| Benchmark | Annual Return |")
        md.append("|---|---|")
        for name, val in bm.items():
            md.append(f"| {name} | {val:.4%} |" if isinstance(val, float) else f"| {name} | {val} |")
    (ctx.report_dir / f"{BacktestStep.name}.md").write_text("\n".join(md))
