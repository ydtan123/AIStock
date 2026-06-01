"""FastEvaluationStep — step 3 of the pipeline."""
from __future__ import annotations

import ast
import datetime as dt
import json
import traceback

from sqlalchemy import desc

from models import (
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    SelectedStock,
)
from pipeline.backends.fast_evaluators import FAST_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


def _try_parse_dict(text: str) -> dict | None:
    """Return parsed dict if text is a JSON or Python dict literal, else None."""
    t = text.strip()
    if not t.startswith("{"):
        return None
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        val = ast.literal_eval(t)
        if isinstance(val, dict):
            return val
    except (ValueError, SyntaxError):
        pass
    return None


def _explain_dict_reasoning(analyst_name: str, data: dict) -> str:
    """Generate a prose explanation from a parsed analyst output dict."""
    # news_sentiment_agent: {'news_sentiment': {signal, confidence, metrics}}
    if set(data.keys()) == {"news_sentiment"}:
        ns = data["news_sentiment"]
        m = ns.get("metrics", {})
        total = m.get("total_articles", 0)
        bull = m.get("bullish_articles", 0)
        bear = m.get("bearish_articles", 0)
        neu = m.get("neutral_articles", 0)
        sig = ns.get("signal", "neutral")
        conf = ns.get("confidence", 0)
        return (
            f"Based on {total} news article{'s' if total != 1 else ''} analyzed "
            f"({bull} bullish, {bear} bearish, {neu} neutral), "
            f"the overall sentiment signal is **{sig}** with {conf:.1f}% confidence."
        )

    # sentiment_analyst_agent: insider_trading + news_sentiment + combined_analysis
    if {"insider_trading", "news_sentiment", "combined_analysis"} <= set(data.keys()):
        it = data["insider_trading"]
        ns = data["news_sentiment"]
        ca = data["combined_analysis"]
        it_m = it.get("metrics", {})
        ns_m = ns.get("metrics", {})
        it_trades = it_m.get("total_trades", 0)
        ns_arts = ns_m.get("total_articles", 0)
        det = ca.get("signal_determination", "")
        return (
            f"Insider trading: {it_trades} trade{'s' if it_trades != 1 else ''} recorded "
            f"(signal: **{it.get('signal', 'neutral')}**, confidence: {it.get('confidence', 0):.0f}%). "
            f"News sentiment: {ns_arts} article{'s' if ns_arts != 1 else ''} analyzed "
            f"(signal: **{ns.get('signal', 'neutral')}**, confidence: {ns.get('confidence', 0):.0f}%). "
            f"Combined weighted analysis: {det}."
        )

    # fundamentals_analyst_agent / valuation / risk: has a 'summary' field
    if "summary" in data:
        lines = [data["summary"]]
        signal_keys = [k for k in data if k.endswith("_signal")]
        for key in signal_keys:
            sig = data[key]
            label = key.replace("_signal", "").replace("_", " ").title()
            detail = sig.get("details", "") or sig.get("reasoning", "")
            entry = f"**{label}** ({sig.get('signal', '').upper()})"
            if detail:
                entry += f": {detail}"
            lines.append(entry)
        return "\n\n".join(lines)

    # Generic fallback: describe each top-level key that looks like a signal sub-dict
    lines = []
    for key, val in data.items():
        label = key.replace("_", " ").title()
        if isinstance(val, dict):
            sig = val.get("signal", "")
            detail = val.get("details", "") or val.get("reasoning", "") or val.get("description", "")
            conf = val.get("confidence")
            entry = f"**{label}**"
            if sig:
                entry += f": {sig.upper()}"
            if conf is not None:
                entry += f" ({conf:.0f}% confidence)" if isinstance(conf, (int, float)) else f" ({conf})"
            if detail:
                entry += f" — {detail}"
            lines.append(entry)
        elif isinstance(val, str) and val:
            lines.append(f"**{label}**: {val}")
    return "\n\n".join(lines)


def _format_reasoning(analyst_name: str, reasoning: str) -> list[str]:
    """Return markdown lines for an analyst's reasoning.

    If the reasoning is a raw dict/JSON string, prepend a prose explanation
    and render the raw data as a fenced code block.
    """
    raw = reasoning.strip()
    parsed = _try_parse_dict(raw)
    if parsed is None:
        return [raw]

    explanation = _explain_dict_reasoning(analyst_name, parsed)
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    out: list[str] = []
    if explanation:
        out.append(explanation)
        out.append("")
    out.append("```json")
    out.append(pretty)
    out.append("```")
    return out


def _count_by_opinion(opinions):
    pos = sum(1 for o in opinions if o.opinion == "bullish")
    neg = sum(1 for o in opinions if o.opinion == "bearish")
    neu = sum(1 for o in opinions if o.opinion == "neutral")
    return pos, neg, neu


def _write_report(evaluations, report_dir, backend_name):
    """Write per-ticker fast evaluation as markdown reports.

    Creates:
        <TICKER>/fast_evaluation/fast_evaluation.md  — per-ticker report
        fast_evaluation.md                            — combined all-ticker report (legacy)
    """
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

        sorted_ops = sorted(ev.opinions, key=lambda o: (
            {"bullish": 0, "bearish": 1, "neutral": 2}.get(o.opinion, 3),
            -o.confidence
        ))

        ticker_lines = [
            f"# Fast Evaluation: {ev.ticker}",
            "",
            f"**Backend:** {backend_name}",
            f"**Consensus:** {direction} ({consensus:+.4f})",
            f"**Period:** {ev.start_date} → {ev.end_date}",
            "",
            "---",
            "",
            "## Analyst Opinions",
            "",
            "| | Count | Pct |",
            "|---|---|---|",
        ]
        if total:
            ticker_lines.append(f"| 🟢 Bullish | {pos} | {pos/total*100:.0f}% |")
            ticker_lines.append(f"| 🔴 Bearish | {neg} | {neg/total*100:.0f}% |")
            ticker_lines.append(f"| 🟡 Neutral | {neu} | {neu/total*100:.0f}% |")
        ticker_lines.append("")
        for op in sorted_ops:
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(op.opinion, "⚪")
            ticker_lines.append(
                f"### {emoji} {op.analyst_name} — {op.opinion.upper()}"
                f" (confidence: {op.confidence:.0f}%)"
            )
            ticker_lines.append("")
            if op.reasoning:
                ticker_lines.extend(_format_reasoning(op.analyst_name, op.reasoning))
            ticker_lines.append("")

        # Per-ticker output under <TICKER>/fast_evaluation/
        ticker_dir = report_dir / ev.ticker / "fast_evaluation"
        ticker_dir.mkdir(parents=True, exist_ok=True)
        (ticker_dir / "fast_evaluation.md").write_text(
            "\n".join(ticker_lines), encoding="utf-8"
        )

        # Combined report
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

        for op in sorted_ops:
            emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(op.opinion, "⚪")
            lines.append(
                f"### {emoji} {op.analyst_name} — {op.opinion.upper()}"
                f" (confidence: {op.confidence:.0f}%)"
            )
            lines.append("")
            if op.reasoning:
                lines.extend(_format_reasoning(op.analyst_name, op.reasoning))
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

        symbols = ctx.cfg.get("pipeline", {}).get("symbols", [])
        if symbols:
            tickers = symbols[:top_n]
            ctx.logger.info("FastEvaluationStep: using --symbols (%d tickers)", len(tickers))
        else:
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
