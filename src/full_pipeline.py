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
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
    raise NotImplementedError


def step2_finrl_selection(cfg: dict, report_dir: Path) -> list[dict]:
    raise NotImplementedError


def _score_ticker(decision: dict) -> float:
    raise NotImplementedError


def step3_hedge_fund(tickers: list[str], cfg: dict, report_dir: Path) -> list[str]:
    raise NotImplementedError


def _parse_ta_ndjson(stdout: str) -> dict[str, dict]:
    raise NotImplementedError


def step4_trading_agents(tickers: list[str], cfg: dict, report_dir: Path) -> dict:
    raise NotImplementedError


def write_summary(results: dict, report_dir: Path) -> None:
    raise NotImplementedError


def main() -> None:
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

    try:
        if not args.skip_step1:
            results["step1"] = step1_daily_update(cfg, report_dir)
        else:
            _LOG.info("Skipping step 1 (--skip-step1 flag set)")

        top10 = step2_finrl_selection(cfg, report_dir)
        results["step2_top10"] = top10

        top3 = step3_hedge_fund([r["ticker"] for r in top10], cfg, report_dir)
        results["step3_top3"] = top3

        step4_result = step4_trading_agents(top3, cfg, report_dir)
        results["step4"] = step4_result

        results["status"] = "success"
        results["steps_completed"] = 4
    except Exception as exc:
        _LOG.error("Pipeline failed: %s", exc, exc_info=True)
        results["status"] = "failed"
        results["error"] = str(exc)
        write_summary(results, report_dir)
        sys.exit(1)

    write_summary(results, report_dir)
    _LOG.info("Pipeline complete. Reports at: %s", report_dir)


if __name__ == "__main__":
    main()
