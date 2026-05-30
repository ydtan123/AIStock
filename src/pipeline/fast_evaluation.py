"""FastEvaluationStep — step 3 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback

from sqlalchemy import desc

from models import (
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    SelectedStock,
)
from pipeline.backends.fast_evaluators import FAST_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


def _count_by_opinion(opinions):
    pos = sum(1 for o in opinions if o.opinion == "bullish")
    neg = sum(1 for o in opinions if o.opinion == "bearish")
    neu = sum(1 for o in opinions if o.opinion == "neutral")
    return pos, neg, neu


def _write_report(evaluations, report_dir, backend_name):
    """Write per-agent detailed analysis as a markdown report."""
    report_path = report_dir / "fast_evaluation.md"
    lines = [
        f"# Fast Evaluation Report — {backend_name}",
        "",
        f"**Date:** {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC",
        f"**Tickers evaluated:** {len(evaluations)}",
        "",
        "---",
        "",
    ]

    for ev in evaluations:
        pos, neg, neu = _count_by_opinion(ev.opinions)
        total = pos + neg + neu
        consensus = ev.consensus_score
        direction = (
            "🟢 Bullish" if consensus > 0.1
            else "🔴 Bearish" if consensus < -0.1
            else "🟡 Neutral"
        )

        lines.append(f"## {ev.ticker} — Consensus: {direction} ({consensus:+.4f})")
        lines.append("")
        lines.append("| | Count | Pct |")
        lines.append("|---|---|---|")
        if total:
            lines.append(f"| 🟢 Bullish | {pos} | {pos/total*100:.0f}% |")
            lines.append(f"| 🔴 Bearish | {neg} | {neg/total*100:.0f}% |")
            lines.append(f"| 🟡 Neutral | {neu} | {neu/total*100:.0f}% |")
        lines.append("")
        lines.append(f"**Period:** {ev.start_date} → {ev.end_date}")
        lines.append("")

        sorted_ops = sorted(ev.opinions, key=lambda o: (
            {"bullish": 0, "bearish": 1, "neutral": 2}.get(o.opinion, 3),
            -o.confidence
        ))
        for op in sorted_ops:
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(op.opinion, "⚪")
            lines.append(
                f"### {emoji} {op.analyst_name} — {op.opinion.upper()}"
                f" (confidence: {op.confidence:.0f}%)"
            )
            lines.append("")
            if op.reasoning:
                lines.append(op.reasoning.strip())
            lines.append("")

        lines.append("---")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


class FastEvaluationStep(PipelineStep):
    name = "fast_evaluation"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "ai_hedge_fund")
        top_n = int(sub.get("top_n", 10))

        try:
            evaluator_cls = FAST_EVALUATOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        with open_session(ctx) as session:
            rows = (
                session.query(SelectedStock)
                .filter(SelectedStock.pipeline_run_id == ctx.run_id)
                .order_by(desc(SelectedStock.ml_score))
                .limit(top_n)
                .all()
            )
            tickers = [r.ticker for r in rows]

        if not tickers:
            return StepResult(
                step_name=self.name,
                status="success",
                summary={"backend": backend_name, "note": "no upstream tickers"},
                payload={"backend": backend_name, "tickers_ranked_by_consensus": []},
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

        now = dt.datetime.utcnow()
        ranked: list[dict] = []

        with open_session(ctx) as session:
            session.query(FastEvaluationAnalyst).filter_by(
                pipeline_run_id=ctx.run_id
            ).delete()
            session.query(FastEvaluationConclusion).filter_by(
                pipeline_run_id=ctx.run_id
            ).delete()

            conclusions: list[FastEvaluationConclusion] = []
            analysts: list[FastEvaluationAnalyst] = []

            for ev in evaluations:
                pos, neg, neu = _count_by_opinion(ev.opinions)
                total = pos + neg + neu
                conclusions.append(FastEvaluationConclusion(
                    pipeline_run_id=ctx.run_id,
                    ticker=ev.ticker,
                    backend=backend_name,
                    start_date=dt.date.fromisoformat(ev.start_date),
                    end_date=dt.date.fromisoformat(ev.end_date),
                    evaluation_date=now,
                    positive_count=pos,
                    negative_count=neg,
                    neutral_count=neu,
                    total_count=total,
                    consensus_score=ev.consensus_score,
                    model_name=evaluator_cfg.get("model_name", ""),
                    model_provider=evaluator_cfg.get("model_provider", ""),
                ))
                for op in ev.opinions:
                    analysts.append(FastEvaluationAnalyst(
                        pipeline_run_id=ctx.run_id,
                        ticker=ev.ticker,
                        backend=backend_name,
                        analyst_name=op.analyst_name,
                        opinion=op.opinion,
                        confidence=op.confidence,
                        reasoning=op.reasoning,
                        start_date=dt.date.fromisoformat(ev.start_date),
                        end_date=dt.date.fromisoformat(ev.end_date),
                        evaluation_date=now,
                    ))

            session.add_all(conclusions)
            session.add_all(analysts)
            session.commit()

            conclusions_sorted = sorted(
                conclusions, key=lambda c: c.consensus_score, reverse=True
            )
            for c in conclusions_sorted:
                ranked.append({
                    "ticker": c.ticker,
                    "consensus_score": c.consensus_score,
                    "positive": c.positive_count,
                    "negative": c.negative_count,
                    "neutral": c.neutral_count,
                })

        report_path = _write_report(evaluations, ctx.report_dir, backend_name)
        ctx.logger.info("Fast evaluation report saved → %s", report_path)

        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "tickers_evaluated": len(evaluations),
            },
            payload={
                "backend": backend_name,
                "tickers_ranked_by_consensus": ranked,
                "report": str(report_path),
            },
        )
