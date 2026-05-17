"""FastEvaluationStep — step 3 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback
from contextlib import contextmanager

from sqlalchemy import desc

from models import (
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    SelectedStock,
)
from pipeline.backends.fast_evaluators import FAST_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult


@contextmanager
def _open_session(ctx: StepContext):
    s = ctx.session_factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()


def _count_by_opinion(opinions):
    pos = sum(1 for o in opinions if o.opinion == "bullish")
    neg = sum(1 for o in opinions if o.opinion == "bearish")
    neu = sum(1 for o in opinions if o.opinion == "neutral")
    return pos, neg, neu


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

        with _open_session(ctx) as session:
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
        with _open_session(ctx) as session:
            for ev in evaluations:
                pos, neg, neu = _count_by_opinion(ev.opinions)
                total = pos + neg + neu
                session.add(FastEvaluationConclusion(
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
                    session.add(FastEvaluationAnalyst(
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
            session.commit()

        evaluations_sorted = sorted(
            evaluations, key=lambda e: e.consensus_score, reverse=True
        )
        for ev in evaluations_sorted:
            pos, neg, neu = _count_by_opinion(ev.opinions)
            ranked.append({
                "ticker": ev.ticker,
                "consensus_score": ev.consensus_score,
                "positive": pos,
                "negative": neg,
                "neutral": neu,
            })

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
            },
        )
