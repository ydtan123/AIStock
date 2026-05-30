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
