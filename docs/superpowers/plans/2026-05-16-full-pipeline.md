# Full Pipeline Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `src/full_pipeline.py` to orchestrate 4-step stock analysis pipeline (daily data update → FinRL ML selection → ai-hedge-fund evaluation → TradingAgents analysis) saving `.md` + `.json` reports to `reports/full_pipeline/YYYYMMDD-HHMMSS/`.

**Architecture:** Single Python orchestrator; steps 1–2 use direct imports (same `.venv`); steps 3–4 use subprocess. ai-hedge-fund gets a new `--output-json` flag; TradingAgents stdout is already NDJSON. Any step failure stops the pipeline (non-zero exit) after writing a partial `summary.json`.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, subprocess, json, argparse, pathlib, yaml; poetry (ai-hedge-fund env), ta_run.py NDJSON (TradingAgents).

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `external/ai-hedge-fund/main_non_interactive.py` | Modify | Add `--output-json` arg: dump result dict to path when provided |
| `src/full_pipeline.py` | Create | Orchestrator: config load, report dir, 4 step functions, summary writer, main() |
| `tests/test_full_pipeline.py` | Create | Unit tests: `_write_step_report`, `_score_ticker`, `_parse_ta_ndjson` |

---

### Task 1: Add --output-json to main_non_interactive.py

**Files:**
- Modify: `external/ai-hedge-fund/main_non_interactive.py`
- Create: `tests/test_full_pipeline.py` (placeholder)

- [ ] **Step 1: Create test file with placeholder**

Create `tests/test_full_pipeline.py`:

```python
"""Unit tests for full_pipeline helpers."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ORDERING CRITICAL: import AIStock core before FinRL to prevent sys.path pollution
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401


def test_placeholder():
    assert True
```

Run:
```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -v
```
Expected: `test_placeholder PASSED`

- [ ] **Step 2: Add --output-json argument to argparse**

In `external/ai-hedge-fund/main_non_interactive.py`, find the argparse block (around line 179–184) and add after the existing `add_argument` calls:

```python
parser.add_argument(
    "--output-json", type=str, dest="output_json", default=None,
    help="Write result dict as JSON to this file path",
)
```

- [ ] **Step 3: Write result to file when flag is set**

After the `print_trading_output(result)` call (line ~249), add:

```python
if args.output_json:
    import pathlib as _pl
    _pl.Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_json, "w") as _f:
        json.dump(result, _f, indent=2, default=str)
    print(f"[output] Result written to {args.output_json}")
```

- [ ] **Step 4: Verify --help shows the new flag**

```bash
cd /Users/yudongtan/projects/AIStock/external/ai-hedge-fund
poetry run python main_non_interactive.py --help
```
Expected: output includes `--output-json`

- [ ] **Step 5: Commit**

```bash
git add external/ai-hedge-fund/main_non_interactive.py tests/test_full_pipeline.py
git commit -m "feat: add --output-json flag to main_non_interactive.py"
```

---

### Task 2: full_pipeline.py skeleton (argparse + config + report dir + helpers)

**Files:**
- Create: `src/full_pipeline.py`

- [ ] **Step 1: Write test for _write_step_report**

Replace contents of `tests/test_full_pipeline.py`:

```python
"""Unit tests for full_pipeline helpers."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ORDERING CRITICAL: import AIStock core before FinRL to prevent sys.path pollution
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401

from full_pipeline import _write_step_report


def test_write_step_report_creates_json_and_md():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_dir = Path(tmpdir)
        data = {
            "status": "success",
            "started_at": "2026-05-16T10:00:00",
            "finished_at": "2026-05-16T10:05:00",
            "data": {"processed": 42, "errors": 1},
        }
        _write_step_report(report_dir, "step1_daily_update", data)

        json_path = report_dir / "step1_daily_update.json"
        md_path = report_dir / "step1_daily_update.md"

        assert json_path.exists(), "JSON file not created"
        assert md_path.exists(), "MD file not created"

        loaded = json.loads(json_path.read_text())
        assert loaded["status"] == "success"
        assert loaded["data"]["processed"] == 42

        md_text = md_path.read_text().lower()
        assert "step1 daily update" in md_text
        assert "success" in md_text
```

Run:
```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py::test_write_step_report_creates_json_and_md -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'full_pipeline'`

- [ ] **Step 2: Create src/full_pipeline.py**

Create `src/full_pipeline.py`:

```python
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
```

- [ ] **Step 3: Run test**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py::test_write_step_report_creates_json_and_md -v
```
Expected: PASS

- [ ] **Step 4: Verify --help works**

```bash
PYTHONPATH=src python src/full_pipeline.py --help
```
Expected: prints usage with `--config` and `--skip-step1`, no errors.

- [ ] **Step 5: Commit**

```bash
git add src/full_pipeline.py tests/test_full_pipeline.py
git commit -m "feat: add full_pipeline.py skeleton with helpers, argparse, report dir"
```

---

### Task 3: Implement step1_daily_update

**Files:**
- Modify: `src/full_pipeline.py` (replace `step1_daily_update` stub)

- [ ] **Step 1: Replace the stub**

Replace the `step1_daily_update` function body in `src/full_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run existing tests to confirm no regression**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -v
```
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/full_pipeline.py
git commit -m "feat: implement step1_daily_update in full_pipeline.py"
```

---

### Task 4: Implement step2_finrl_selection

**Files:**
- Modify: `src/full_pipeline.py` (replace `step2_finrl_selection` stub)

- [ ] **Step 1: Replace the stub**

Replace the `step2_finrl_selection` function body in `src/full_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -v
```
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add src/full_pipeline.py
git commit -m "feat: implement step2_finrl_selection in full_pipeline.py"
```

---

### Task 5: Implement _score_ticker and step3_hedge_fund

**Files:**
- Modify: `src/full_pipeline.py` (replace stubs)
- Modify: `tests/test_full_pipeline.py` (add scoring tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_full_pipeline.py` (after existing imports):

```python
from full_pipeline import _score_ticker
```

Add test functions:

```python
def test_score_ticker_buy():
    assert _score_ticker({"action": "buy", "confidence": 80}) == pytest.approx(0.80)


def test_score_ticker_sell():
    assert _score_ticker({"action": "sell", "confidence": 60}) == pytest.approx(-0.60)


def test_score_ticker_short():
    assert _score_ticker({"action": "short", "confidence": 70}) == pytest.approx(-0.70)


def test_score_ticker_hold():
    assert _score_ticker({"action": "hold", "confidence": 50}) == pytest.approx(0.0)


def test_score_ticker_missing_fields():
    assert _score_ticker({}) == pytest.approx(0.0)
```

Run:
```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -k "score_ticker" -v
```
Expected: all 5 FAIL with `NotImplementedError`

- [ ] **Step 2: Replace _score_ticker stub**

Replace the `_score_ticker` function body in `src/full_pipeline.py`:

```python
def _score_ticker(decision: dict) -> float:
    """Convert ai-hedge-fund decision to net score in [-1.0, +1.0].

    buy  → +confidence/100
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
```

- [ ] **Step 3: Run scoring tests**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -k "score_ticker" -v
```
Expected: all 5 PASS.

- [ ] **Step 4: Replace step3_hedge_fund stub**

Replace the `step3_hedge_fund` function body in `src/full_pipeline.py`:

```python
def step3_hedge_fund(tickers: list[str], cfg: dict, report_dir: Path) -> list[str]:
    if not tickers:
        raise ValueError("step3_hedge_fund: no tickers provided")

    started_at = datetime.now().isoformat()
    _LOG.info("[Step 3] ai-hedge-fund evaluation of %d tickers: %s", len(tickers), tickers)

    ahf_dir = PROJECT_ROOT / "external" / "ai-hedge-fund"
    tmp_json = Path(tempfile.mktemp(suffix="_ahf.json"))

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
```

- [ ] **Step 5: Run all tests**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/full_pipeline.py tests/test_full_pipeline.py
git commit -m "feat: implement _score_ticker and step3_hedge_fund in full_pipeline.py"
```

---

### Task 6: Implement _parse_ta_ndjson and step4_trading_agents

**Files:**
- Modify: `src/full_pipeline.py` (replace stubs)
- Modify: `tests/test_full_pipeline.py` (add NDJSON test)

- [ ] **Step 1: Write failing test**

Add import at the top of `tests/test_full_pipeline.py`:

```python
from full_pipeline import _parse_ta_ndjson
```

Add test function:

```python
def test_parse_ta_ndjson_extracts_ticker_results():
    ndjson = "\n".join([
        json.dumps({"type": "start", "tickers": ["AAPL", "NVDA"]}),
        json.dumps({"type": "ticker_start", "ticker": "AAPL"}),
        json.dumps({
            "type": "ticker_result",
            "ticker": "AAPL",
            "decision": "BUY",
            "bullet_summaries": {"Market": ["Bullish trend"]},
            "investment_plan": "Go long",
            "final_decision": "Strong buy",
            "llm_calls": 12,
        }),
        json.dumps({"type": "ticker_error", "ticker": "NVDA", "error": "timeout"}),
        json.dumps({"type": "done", "total_llm_calls": 12, "summary": []}),
        "this is not json and should be skipped",
    ])
    results = _parse_ta_ndjson(ndjson)

    assert "AAPL" in results
    assert results["AAPL"]["decision"] == "BUY"
    assert results["AAPL"]["bullet_summaries"]["Market"] == ["Bullish trend"]
    assert results["AAPL"]["llm_calls"] == 12
    assert "NVDA" not in results  # error event is not a ticker_result
```

Run:
```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py::test_parse_ta_ndjson_extracts_ticker_results -v
```
Expected: FAIL with `NotImplementedError`

- [ ] **Step 2: Replace _parse_ta_ndjson stub**

Replace the `_parse_ta_ndjson` function body in `src/full_pipeline.py`:

```python
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
```

- [ ] **Step 3: Run NDJSON test**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py::test_parse_ta_ndjson_extracts_ticker_results -v
```
Expected: PASS.

- [ ] **Step 4: Replace step4_trading_agents stub**

Replace the `step4_trading_agents` function body in `src/full_pipeline.py`:

```python
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
```

- [ ] **Step 5: Run all tests**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/full_pipeline.py tests/test_full_pipeline.py
git commit -m "feat: implement _parse_ta_ndjson and step4_trading_agents in full_pipeline.py"
```

---

### Task 7: Implement write_summary and complete main()

**Files:**
- Modify: `src/full_pipeline.py` (replace write_summary stub; main() already wired)

- [ ] **Step 1: Replace write_summary stub**

Replace the `write_summary` function body in `src/full_pipeline.py`:

```python
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
```

- [ ] **Step 2: Verify --help and module import still clean**

```bash
PYTHONPATH=src python src/full_pipeline.py --help
PYTHONPATH=src python -c "import full_pipeline; print('import OK')"
```
Expected: help text prints, then `import OK`.

- [ ] **Step 3: Run all unit tests**

```bash
PYTHONPATH=src pytest tests/test_full_pipeline.py -v
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/full_pipeline.py
git commit -m "feat: implement write_summary and complete full_pipeline.py orchestrator"
```

---

## Self-Review

Spec coverage:
- ✅ Step 1 daily update with fetcher selection — Task 3
- ✅ Step 2 FinRL selection + top-10 DB read — Task 4
- ✅ ai-hedge-fund `--output-json` flag — Task 1
- ✅ Step 3 subprocess → parse decisions → score → top3 — Tasks 1 + 5
- ✅ Consensus scoring formula (buy/sell/short/hold) — Task 5
- ✅ Step 4 TradingAgents NDJSON stdout parsing — Task 6
- ✅ `.md` + `.json` reports per step — Task 2
- ✅ `summary.{md,json}` with top10 + top3 — Task 7
- ✅ Fail fast + partial summary on error — Task 2 (main())
- ✅ `--skip-step1` flag — Task 2
- ✅ `--config` flag — Task 2
- ✅ Environment isolation for steps 3–4 via subprocess — Tasks 5–6
- ✅ AIStock import ordering guard — Task 2 (module-level comments)

No placeholders. Function names consistent across all tasks: `_write_step_report`, `_score_ticker`, `_parse_ta_ndjson`, `step1_daily_update`, `step2_finrl_selection`, `step3_hedge_fund`, `step4_trading_agents`, `write_summary`.
