"""Full stock analysis pipeline.

Steps:
  1. Update daily prices, indicators, fundamentals (direct import, same venv)
  2. FinRL ML stock selection (direct import, same venv)
  3. ai-hedge-fund evaluation of top 10 by ML score (subprocess, poetry env)
  4. TradingAgents evaluation of top 3 by consensus (subprocess, ta_run.py)

Reports saved to reports/full_pipeline/YYYYMMDD-HHMMSS/
"""
from __future__ import annotations

# ORDERING CRITICAL: import AIStock core before any FinRL imports to prevent
# FinRL's data_fetcher.py from shadowing src/config.py via sys.path insertion.
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_LOG = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_BASE = PROJECT_ROOT / "reports" / "full_pipeline"


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _make_report_dir() -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = REPORTS_BASE / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def _write_step_report(report_dir: Path, step_name: str, data: dict) -> None:
    """Write JSON + Markdown report for a single pipeline step."""
    json_path = report_dir / f"{step_name}.json"
    md_path = report_dir / f"{step_name}.md"

    json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    title = step_name.replace("_", " ").title()
    lines = [
        f"# {title}\n\n",
        f"**Status:** {data.get('status', 'unknown')}  \n",
        f"**Started:** {data.get('started_at', '')}  \n",
        f"**Finished:** {data.get('finished_at', '')}\n\n",
    ]
    if "data" in data:
        lines.append("## Data\n\n")
        lines.append(f"```json\n{json.dumps(data['data'], indent=2, default=str)}\n```\n")
    md_path.write_text("".join(lines), encoding="utf-8")


def step1_daily_update(cfg: dict, report_dir: Path) -> dict:
    from fetcher.alpha_vantage import AlphaVantageFetcher
    from fetcher.yahoo import YahooFetcher
    from ingestion.pipeline import run_daily_pipeline

    started_at = datetime.now().isoformat()
    _LOG.info("[Step 1] Daily data update starting")

    source = cfg.get("source", "alpha_vantage")
    if source == "alpha_vantage":
        fetcher = AlphaVantageFetcher(cfg["alpha_vantage"]["api_key"])
    else:
        fetcher = YahooFetcher()

    summary = run_daily_pipeline(fetcher)

    finished_at = datetime.now().isoformat()
    step_data = {
        "status": "success",
        "started_at": started_at,
        "finished_at": finished_at,
        "data": {
            "processed": summary.get("processed", 0),
            "errors": summary.get("errors", 0),
            "symbols_sample": (summary.get("symbols") or [])[:20],
        },
    }
    _write_step_report(report_dir, "step1_daily_update", step_data)
    _LOG.info(
        "[Step 1] Done: %d processed, %d errors",
        summary.get("processed", 0),
        summary.get("errors", 0),
    )
    return step_data


def step2_finrl_selection(cfg: dict, report_dir: Path) -> list[dict]:
    from finrl_pipeline import run_pipeline_and_save_report
    from repository import StockRepository

    started_at = datetime.now().isoformat()
    _LOG.info("[Step 2] FinRL ML selection starting")

    fp_cfg = cfg.get("finrl_pipeline", {})
    run_pipeline_and_save_report(fp_cfg)

    repo = StockRepository()
    all_selected = repo.get_latest_selected_stocks()
    top10 = sorted(all_selected, key=lambda r: r.get("ml_score", 0.0), reverse=True)[:10]

    finished_at = datetime.now().isoformat()
    step_data = {
        "status": "success",
        "started_at": started_at,
        "finished_at": finished_at,
        "data": {
            "total_selected": len(all_selected),
            "top10": top10,
        },
    }
    _write_step_report(report_dir, "step2_finrl", step_data)
    _LOG.info("[Step 2] Done: %d total selected, top 10 extracted", len(all_selected))
    return top10


def _score_ticker(decision: dict) -> float:
    """Convert ai-hedge-fund decision to net score in [-1.0, +1.0].

    buy → +confidence/100
    sell / short → -confidence/100
    hold / anything else → 0.0
    """
    action = (decision.get("action") or "hold").lower()
    confidence = float(decision.get("confidence") or 0) / 100.0
    if action == "buy":
        return confidence
    if action in ("sell", "short"):
        return -confidence
    return 0.0


def step3_hedge_fund(tickers: list[str], cfg: dict, report_dir: Path) -> list[str]:
    if not tickers:
        raise ValueError("step3_hedge_fund: no tickers provided")

    started_at = datetime.now().isoformat()
    _LOG.info("[Step 3] ai-hedge-fund evaluation of %d tickers: %s", len(tickers), tickers)

    ahf_dir = PROJECT_ROOT / "external" / "ai-hedge-fund"
    tmp_file = tempfile.NamedTemporaryFile(suffix="_ahf.json", delete=False)
    tmp_file.close()
    tmp_json = Path(tmp_file.name)

    cmd = [
        "poetry", "run", "python", "main_non_interactive.py",
        "--tickers", ",".join(tickers),
        "--output-json", str(tmp_json),
    ]
    _LOG.info("[Step 3] Command: %s (cwd=%s)", " ".join(cmd), ahf_dir)

    proc = subprocess.run(cmd, cwd=str(ahf_dir), text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ai-hedge-fund subprocess failed (exit {proc.returncode})")
    if not tmp_json.exists():
        raise RuntimeError(f"ai-hedge-fund did not write {tmp_json}")

    ahf_result = json.loads(tmp_json.read_text())
    tmp_json.unlink(missing_ok=True)

    decisions: dict = ahf_result.get("decisions") or {}
    scored: dict[str, float] = {}
    for ticker, dec in decisions.items():
        if dec:
            scored[ticker] = _score_ticker(dec)

    top3 = sorted(scored, key=lambda t: scored[t], reverse=True)[:3]

    finished_at = datetime.now().isoformat()
    step_data = {
        "status": "success",
        "started_at": started_at,
        "finished_at": finished_at,
        "data": {
            "tickers_evaluated": tickers,
            "decisions": {
                t: {
                    "action": (decisions.get(t) or {}).get("action"),
                    "confidence": (decisions.get(t) or {}).get("confidence"),
                    "net_score": scored.get(t, 0.0),
                }
                for t in tickers
            },
            "top3": top3,
        },
    }
    _write_step_report(report_dir, "step3_hedge_fund", step_data)
    _LOG.info("[Step 3] Done: top3 by net consensus = %s", top3)
    return top3


def _parse_ta_ndjson(stdout: str) -> dict[str, dict]:
    """Parse ta_run.py NDJSON stdout → {ticker: result_dict} for ticker_result events."""
    results: dict[str, dict] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "ticker_result":
            ticker = event.get("ticker")
            if ticker:
                results[ticker] = {
                    "decision": event.get("decision"),
                    "bullet_summaries": event.get("bullet_summaries") or {},
                    "investment_plan": event.get("investment_plan", ""),
                    "final_decision": event.get("final_decision", ""),
                    "llm_calls": event.get("llm_calls", 0),
                }
    return results


def step4_trading_agents(tickers: list[str], cfg: dict, report_dir: Path) -> dict:
    if not tickers:
        raise ValueError("step4_trading_agents: no tickers provided")

    started_at = datetime.now().isoformat()
    date_str = datetime.now().strftime("%Y-%m-%d")
    _LOG.info("[Step 4] TradingAgents evaluation: %s (date=%s)", tickers, date_str)

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "src" / "ta_run.py"),
        "--tickers", ",".join(tickers),
        "--date", date_str,
    ]
    _LOG.info("[Step 4] Command: %s", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    # Log stderr (ta_run.py sends logs there)
    if proc.stderr:
        for line in proc.stderr.splitlines():
            _LOG.info("[ta_run stderr] %s", line)

    ta_results = _parse_ta_ndjson(proc.stdout)

    if proc.returncode != 0 and not ta_results:
        raise RuntimeError(
            f"TradingAgents failed (exit {proc.returncode}). "
            f"Stderr tail: {proc.stderr[-500:]}"
        )

    finished_at = datetime.now().isoformat()
    step_data = {
        "status": "success",
        "started_at": started_at,
        "finished_at": finished_at,
        "data": {
            "tickers_evaluated": tickers,
            "date": date_str,
            "results": ta_results,
        },
    }
    _write_step_report(report_dir, "step4_trading_agents", step_data)
    _LOG.info("[Step 4] Done: %d tickers analysed", len(ta_results))
    return step_data


def write_summary(results: dict, report_dir: Path) -> None:
    status = results.get("status", "unknown")
    top10_records = results.get("step2_top10") or []
    top10 = [r.get("ticker") for r in top10_records if r.get("ticker")]
    top3 = results.get("step3_top3") or []

    summary = {
        "run_id": results.get("run_id"),
        "status": status,
        "steps_completed": results.get("steps_completed", 0),
        "report_dir": str(report_dir),
        "top10_finrl": top10,
        "top3_consensus": top3,
        "failed_at": results.get("failed_at"),
        "error": results.get("error"),
    }

    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"

    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Full Pipeline Summary\n\n",
        f"**Run ID:** {summary['run_id']}  \n",
        f"**Status:** {summary['status']}  \n",
        f"**Steps completed:** {summary['steps_completed']}/4\n\n",
        "## FinRL Top 10\n\n",
        "| Rank | Ticker |\n|------|--------|\n",
    ]
    for i, t in enumerate(top10, 1):
        lines.append(f"| {i} | {t} |\n")
    lines.append("\n## TradingAgents Final (Top 3)\n\n")
    for t in top3:
        lines.append(f"- **{t}**\n")
    if summary.get("error"):
        lines.append(f"\n---\n**Error:** {summary['error']}\n")

    md_path.write_text("".join(lines), encoding="utf-8")
    _LOG.info("Summary written to %s", report_dir)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Run full 4-step stock analysis pipeline")
    parser.add_argument(
        "--config", default=str(PROJECT_ROOT / "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument("--skip-step1", action="store_true", help="Skip daily data update")
    args = parser.parse_args()

    cfg = _load_config(args.config)
    report_dir = _make_report_dir()
    _LOG.info("Report directory: %s", report_dir)

    results: dict[str, Any] = {"run_id": report_dir.name, "report_dir": str(report_dir)}

    current_step = "init"
    try:
        if not args.skip_step1:
            current_step = "step1_daily_update"
            results["step1"] = step1_daily_update(cfg, report_dir)
        else:
            _LOG.info("Skipping step 1 (--skip-step1 flag set)")

        current_step = "step2_finrl_selection"
        top10 = step2_finrl_selection(cfg, report_dir)
        results["step2_top10"] = top10

        current_step = "step3_hedge_fund"
        top3 = step3_hedge_fund([r["ticker"] for r in top10], cfg, report_dir)
        results["step3_top3"] = top3

        current_step = "step4_trading_agents"
        step4_result = step4_trading_agents(top3, cfg, report_dir)
        results["step4"] = step4_result

        results["status"] = "success"
        results["steps_completed"] = 4
    except Exception as exc:
        _LOG.error("Pipeline failed at %s: %s", current_step, exc, exc_info=True)
        results["status"] = "failed"
        results["failed_at"] = current_step
        results["error"] = str(exc)
        try:
            write_summary(results, report_dir)
        except Exception as summary_exc:
            _LOG.warning("Could not write failure summary: %s", summary_exc)
        sys.exit(1)

    write_summary(results, report_dir)
    _LOG.info("Pipeline complete. Reports at: %s", report_dir)


if __name__ == "__main__":
    main()
