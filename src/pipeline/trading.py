"""TradingStep — step 6: dry-run or submit portfolio rebalance via Alpaca."""
from __future__ import annotations

import json
import traceback

from models import OnlineTransaction, Portfolio, TradingResult as TradingResultModel
from pipeline.backends.trading_backends import TRADING_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


class TradingStep(PipelineStep):
    name = "trading"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)

        auto_submit = sub.get("auto_submit", False)
        if not _has_alpaca_keys(ctx.cfg, sub):
            return StepResult(
                step_name=self.name,
                status="failed" if auto_submit else "skipped",
                summary={"reason": "Alpaca API keys not configured"},
            )

        backend_name = sub.get("backend", "alpaca")
        backend_cls = TRADING_REGISTRY.get(backend_name)
        backend = backend_cls(sub)

        # Ensure portfolio is initialised from Alpaca (lazy, once)
        _ensure_portfolio_initialized(backend, ctx)

        weights = _load_weights_from_db(ctx)
        if not weights:
            return StepResult(
                step_name=self.name,
                status="skipped",
                summary={"reason": "no selected stocks with weights found"},
            )

        ctx.logger.info(
            "Trading step: %d tickers, auto_submit=%s", len(weights), auto_submit,
        )

        try:
            result = backend.execute(weights, dry_run=not auto_submit, ctx=ctx)
        except Exception:
            _persist_result(ctx, status="failed", error=traceback.format_exc())
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=traceback.format_exc(),
            )

        execution_mode = "submitted" if auto_submit else "dry_run"
        account_info = result.get("account_info", {})

        # Save per-transaction rows (planned → will update to submitted if auto_submit)
        cash_before = float(account_info.get("cash", 0))
        _save_transactions(ctx, result.get("orders_plan", {}), cash_before, execution_mode)

        # Save portfolio snapshot
        _save_portfolio(ctx, account_info)

        # Persist aggregate TradingResult
        _persist_result(
            ctx,
            status="executed",
            buys=result.get("buys"),
            sells=result.get("sells"),
            orders_json=json.dumps(result.get("orders_plan", {}), default=str),
            portfolio_before_json=json.dumps(account_info, default=str),
            mode=execution_mode,
        )

        _write_report(ctx, result, backend_name, execution_mode, weights, account_info)

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


def _has_alpaca_keys(cfg: dict, sub: dict) -> bool:
    """Check if Alpaca credentials are configured (trading config or env vars)."""
    import os
    mode = sub.get("alpaca_mode", "paper")
    api_key = (
        sub.get(f"alpaca_api_key_{mode}")
        or sub.get("alpaca_api_key")
        or os.environ.get("APCA_API_KEY")
    )
    return bool(api_key)


# -- portfolio initialisation -------------------------------------------------


def _ensure_portfolio_initialized(backend, ctx: StepContext) -> None:
    """Lazy-init: if portfolio table is empty, sync current state from Alpaca."""
    with open_session(ctx) as s:
        if s.query(Portfolio).first() is not None:
            return  # already initialised

    ctx.logger.info("Portfolio table empty — initialising from Alpaca")
    try:
        acct = backend.fetch_account_snapshot(ctx)
    except Exception:
        ctx.logger.warning("Could not initialise portfolio from Alpaca: %s", traceback.format_exc())
        return

    with open_session(ctx) as s:
        cash = float(acct.get("cash", 0))
        equity = float(acct.get("equity", 0))
        # Cash-only row
        s.add(Portfolio(pipeline_run_id=ctx.run_id, ticker=None, cash=cash, equity=equity))
        # Position rows
        for pos in acct.get("positions", []):
            s.add(Portfolio(
                pipeline_run_id=ctx.run_id,
                ticker=pos["symbol"],
                shares=float(pos["qty"]),
                avg_cost=float(pos["avg_entry_price"]),
                cash=cash,
                equity=equity,
            ))
        s.commit()
    ctx.logger.info("Portfolio initialised: %d positions, cash=$%.2f, equity=$%.2f",
                    len(acct.get("positions", [])), cash, equity)


# -- transaction persistence ---------------------------------------------------


def _save_transactions(
    ctx: StepContext,
    orders_plan: dict,
    cash_before: float,
    mode: str,
) -> None:
    """Save each planned BUY/SELL as an OnlineTransaction row."""
    status = "submitted" if mode == "submitted" else "planned"
    remaining = cash_before

    with open_session(ctx) as s:
        # Sells first (add cash), then buys (subtract cash)
        for side in ("sell", "buy"):
            for order in orders_plan.get(side, []):
                ticker = order.get("symbol", "?")
                qty = float(order.get("qty", 0))
                notional = float(order.get("notional", 0))
                if notional <= 0 and qty > 0:
                    notional = 0.0  # dry-run may omit notional; price becomes 0
                price = notional / qty if qty > 0 else 0.0
                action = side.upper()

                if action == "SELL":
                    remaining += notional
                else:
                    remaining -= notional

                s.add(OnlineTransaction(
                    pipeline_run_id=ctx.run_id,
                    ticker=ticker,
                    action=action,
                    shares=qty,
                    price=price,
                    total_amount=notional,
                    remaining_cash=round(remaining, 2),
                    status=status,
                ))
        s.commit()
    ctx.logger.info("Saved %d transactions (mode=%s, remaining_cash=$%.2f)",
                    sum(len(orders_plan.get(s, [])) for s in ("sell", "buy")),
                    status, remaining)


def _save_portfolio(
    ctx: StepContext,
    account_info: dict,
) -> None:
    """Save portfolio snapshot from *account_info* (positions + cash + equity)."""
    cash = float(account_info.get("cash", 0))
    equity = float(account_info.get("equity", 0))
    positions = account_info.get("positions", [])

    with open_session(ctx) as s:
        s.add(Portfolio(pipeline_run_id=ctx.run_id, ticker=None, cash=cash, equity=equity))
        for pos in positions:
            s.add(Portfolio(
                pipeline_run_id=ctx.run_id,
                ticker=pos["symbol"],
                shares=float(pos["qty"]),
                avg_cost=float(pos.get("avg_entry_price", 0)),
                cash=cash,
                equity=equity,
            ))
        s.commit()


# -- persistence + report -----------------------------------------------------


def _persist_result(
    ctx: StepContext,
    status: str = "pending",
    buys: int | None = None,
    sells: int | None = None,
    orders_json: str | None = None,
    portfolio_before_json: str | None = None,
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
            portfolio_before_json=portfolio_before_json,
            error_message=error,
        )
        s.add(row)
        s.commit()


def _get_evaluation_reasons(ctx: StepContext) -> dict[str, str]:
    """Return {ticker: reason} from deep_evaluation (preferred) or fast_evaluation."""
    reasons: dict[str, str] = {}
    with open_session(ctx) as s:
        from models import DeepEvaluationRow
        deep_rows = (
            s.query(DeepEvaluationRow)
            .filter_by(pipeline_run_id=ctx.run_id)
            .all()
        )
        for r in deep_rows:
            if r.ticker and r.final_decision:
                reasons[r.ticker] = f"{r.final_decision.upper()}"

    if not reasons:
        with open_session(ctx) as s:
            from models import FastEvaluationConclusion
            fast_rows = (
                s.query(FastEvaluationConclusion)
                .filter_by(pipeline_run_id=ctx.run_id)
                .all()
            )
            for r in fast_rows:
                direction = "BUY" if (r.consensus_score or 0) > 0 else "SELL" if (r.consensus_score or 0) < 0 else "NEUTRAL"
                reasons[r.ticker] = f"Consensus: {direction} ({r.consensus_score:+.4f})"
    return reasons


def _write_report(
    ctx: StepContext, result: dict, backend_name: str,
    mode: str, weights: dict[str, float], account_info: dict,
) -> None:
    json_path = ctx.report_dir / f"{TradingStep.name}.json"
    json_path.write_text(json.dumps({
        "backend": backend_name,
        "mode": mode,
        "tickers": len(weights),
        "results": result,
    }, indent=2, default=str))

    reasons = _get_evaluation_reasons(ctx)
    orders = result.get("orders_plan", {})
    acct = account_info

    md = [
        f"# Trading Report",
        "",
        f"**Backend:** {backend_name}",
        f"**Mode:** {mode}",
        f"**Market Open:** {result.get('market_open', '?')}",
        f"**Cash:** ${acct.get('cash', 0):,.2f}",
        f"**Equity:** ${acct.get('equity', 0):,.2f}",
        "",
        "## Order Summary",
        f"**Buys:** {result.get('buys', 0)}  |  **Sells:** {result.get('sells', 0)}",
        "",
        "### Sells",
        "| Ticker | Shares | Reason |",
        "|---|---|---|",
    ]
    for order in orders.get("sell", []):
        t = order.get("symbol", "?")
        md.append(f"| {t} | {order.get('qty', '?')} | {reasons.get(t, '-')} |")
    md.append("")
    md.append("### Buys")
    md.append("| Ticker | Shares | Weight | Reason |")
    md.append("|---|---|---|---|")
    for order in orders.get("buy", []):
        t = order.get("symbol", "?")
        md.append(f"| {t} | {order.get('qty', '?')} | {weights.get(t, 0):.2%} | {reasons.get(t, '-')} |")
    md.append("")
    md.append("## Target Weights")
    md.append("| Ticker | Weight |")
    md.append("|---|---|")
    for t, w in sorted(weights.items(), key=lambda x: -x[1]):
        md.append(f"| {t} | {w:.4%} |")
    (ctx.report_dir / f"{TradingStep.name}.md").write_text("\n".join(md))
