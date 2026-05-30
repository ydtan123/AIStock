"""DeepEvaluationStep — step 4 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback

from sqlalchemy import desc

from models import DeepEvaluationRow, FastEvaluationConclusion
from pipeline.backends.deep_evaluators import DEEP_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


_NAMED_SLOTS = (
    "market_report",
    "bull_argument",
    "bear_argument",
    "research_manager_decision",
    "trader_plan",
)

_REPORT_SECTIONS: list[tuple[str, str]] = [
    ("market_report", "Market Analyst"),
    ("social_report", "Social / Sentiment Analyst"),
    ("news_report", "News Analyst"),
    ("fundamentals_report", "Fundamentals Analyst"),
    ("bull_argument", "Bull Researcher Debate"),
    ("bear_argument", "Bear Researcher Debate"),
    ("research_manager_decision", "Research Manager Decision"),
    ("trader_plan", "Trader Investment Plan"),
    ("risk_aggressive", "Risk Debate — Aggressive"),
    ("risk_conservative", "Risk Debate — Conservative"),
    ("risk_neutral", "Risk Debate — Neutral"),
    ("risk_manager_decision", "Risk Manager Final Decision"),
]


def _write_report(evaluations, report_dir, backend_name):
    """Write per-ticker deep evaluation as markdown reports.

    Creates:
        deep_evaluation_<TICKER>.md  — per-ticker full report
        deep_evaluation.md           — combined all-ticker report
    """
    for ev in evaluations:
        ticker = ev.ticker
        decision = ev.final_decision or "N/A"
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(decision.upper(), "⚪")

        lines = [
            f"# Deep Evaluation: {ticker}",
            "",
            f"**Backend:** {backend_name}",
            f"**Date:** {ev.evaluation_date}",
            f"**Final Decision:** {emoji} {decision}",
            "",
            "---",
            "",
        ]
        for slot_key, section_title in _REPORT_SECTIONS:
            content = ev.agent_outputs.get(slot_key, "").strip()
            if not content:
                continue
            lines.append(f"## {section_title}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        (report_dir / f"deep_evaluation_{ticker}.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    # Combined all-ticker report
    combined = [
        f"# Deep Evaluation Report — {backend_name}",
        "",
        f"**Date:** {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC",
        f"**Tickers evaluated:** {len(evaluations)}",
        "",
        "---",
        "",
    ]
    for ev in evaluations:
        decision = ev.final_decision or "N/A"
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(decision.upper(), "⚪")
        combined.append(f"## {ev.ticker} — {emoji} {decision}")
        combined.append("")
        for slot_key, section_title in _REPORT_SECTIONS:
            content = ev.agent_outputs.get(slot_key, "").strip()
            if not content:
                continue
            combined.append(f"### {section_title}")
            combined.append("")
            combined.append(content)
            combined.append("")
        combined.append("---")
        combined.append("")

    combined_path = report_dir / "deep_evaluation.md"
    combined_path.write_text("\n".join(combined), encoding="utf-8")
    return combined_path


class DeepEvaluationStep(PipelineStep):
    name = "deep_evaluation"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "trading_agents")
        top_n = int(sub.get("top_n", 3))

        try:
            evaluator_cls = DEEP_EVALUATOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        symbols = ctx.cfg.get("pipeline", {}).get("symbols", [])
        if symbols:
            tickers = symbols[:top_n]
            ctx.logger.info("DeepEvaluationStep: using --symbols (%d tickers)", len(tickers))
        else:
            with open_session(ctx) as session:
                rows = (
                    session.query(FastEvaluationConclusion)
                    .filter(FastEvaluationConclusion.pipeline_run_id == ctx.run_id)
                    .order_by(desc(FastEvaluationConclusion.consensus_score))
                    .limit(top_n)
                    .all()
                )
                tickers = [r.ticker for r in rows]

        if not tickers:
            return StepResult(
                step_name=self.name,
                status="success",
                summary={"backend": backend_name, "note": "no upstream tickers"},
                payload={"backend": backend_name, "evaluations": []},
            )

        evaluator_cfg = sub.get(backend_name, {})
        try:
            evaluator = evaluator_cls(cfg=evaluator_cfg)
            evaluations = evaluator.evaluate(tickers, ctx)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        with open_session(ctx) as session:
            rows: list[DeepEvaluationRow] = []
            for ev in evaluations:
                slot_kwargs = {slot: ev.agent_outputs.get(slot) for slot in _NAMED_SLOTS}
                eval_date = (
                    dt.datetime.fromisoformat(ev.evaluation_date)
                    if "T" in ev.evaluation_date
                    else dt.datetime.strptime(ev.evaluation_date, "%Y-%m-%d")
                )
                rows.append(DeepEvaluationRow(
                    pipeline_run_id=ctx.run_id,
                    ticker=ev.ticker,
                    backend=backend_name,
                    evaluation_date=eval_date,
                    extra_outputs=ev.extra_outputs,
                    final_decision=ev.final_decision,
                    model_name=evaluator_cfg.get("model_name"),
                    **slot_kwargs,
                ))
            session.add_all(rows)
            session.commit()

        report_path = _write_report(evaluations, ctx.report_dir, backend_name)
        ctx.logger.info("Deep evaluation report saved → %s", report_path)

        ev_list = [
            {"ticker": ev.ticker, "final_decision": ev.final_decision}
            for ev in evaluations
        ]
        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "tickers_evaluated": len(evaluations),
            },
            payload={"backend": backend_name, "evaluations": ev_list},
        )
