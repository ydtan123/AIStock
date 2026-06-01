# Performance Optimization — 24 Fixes

**Date:** 2026-05-30
**Source:** docs/performance-analysis-v6.md
**Strategy:** Approach A — Sequential Batched

## Overview

Apply all 24 performance findings from the v6 audit in 4 sequential batches.
Each batch is self-contained, verified with `py_compile`, and committed atomically.

## Batch 1: Critical N+1 DB Fixes

### #1-2: `session.add()` → `add_all()` in pipeline steps
- **Files:** `pipeline/fast_evaluation.py:85,101`, `pipeline/deep_evaluation.py:89`
- **Change:** Collect ORM objects into list, call `session.add_all()` once instead of per-row `add()`
- **Impact:** ~98% fewer ORM dispatch cycles for fast eval; similar for deep eval

### #3-4: `add()` → `add_all()` in repository
- **File:** `repository.py` (`save_selected_stocks`, `save_predict_only_results`)
- **Change:** Build list of SelectedStock rows, call `add_all()` once
- **Impact:** N `add()` calls → 1 `add_all()` per method

### #5: Batch stock lookup in predict-only path
- **Files:** `repository.py` (new `find_stocks_batch`), `app.py:175-190`
- **Change:** Add `find_stocks_batch(symbols)` method; replace per-ticker `find_stock()` + `iterrows()` with single batch query + `itertuples()`
- **Impact:** 100 DB calls → 2 (+ N for get_prices)

## Batch 2: Memory Leak Fixes

### #15: Cap `ml_log_lines`
- **File:** `app.py:53-54`
- **Change:** Trim to `MAX_LOG_LINES=1000`; clear on pipeline start
- **Impact:** Stable memory across repeated pipeline runs

### #16: Clear stale queue sentinels
- **File:** `app.py:63`
- **Change:** Drain `ml_log_queue` before starting new pipeline
- **Impact:** No cross-run sentinel contamination

## Batch 3: UI Caching

### #7: `@st.cache_data` on all 13 UI pages
- **Files:** 8 `ui/pages/*.py` files
- **Change:** Wrap DB queries and file reads with `@st.cache_data(ttl=...)`
- **TTLs:** 60s (prices/indicators), 300s (screener/lookup), 3600s (ML results)
- **Impact:** 80-95% fewer DB queries per user session

## Batch 4: Remaining

### #6: Parallel deep evaluation
- **File:** `backends/deep_evaluators.py:148`
- **Change:** Replace serial `for ticker in tickers` with `ThreadPoolExecutor(max_workers=3)`
- **Impact:** ~3× wall-clock speedup for multi-ticker deep eval

### #8: Batch symbol refresh
- **File:** `ingestion/symbols.py:35-65`
- **Change:** Batch INSERT in chunks of 200 instead of per-row
- **Impact:** 6000 `execute()` → 30 batches

### #9-10,21-22: `iterrows()` antipatterns (5 locations)
- **Files:** `app.py`, `ingestion/pipeline.py`, `ingestion/symbols.py`, `ingestion/indicators.py`, `ui/pages/paper_trading.py`
- **Change:** `iterrows()` → `itertuples()` or vectorized `to_dict(orient="records")`
- **Impact:** 10-100× iteration speedup

### #11: ML results CSV cache
- **File:** `ui/pages/ml_pipeline.py`
- **Change:** Covered by Batch 3 `@st.cache_data`

### #12-14,17-24: Low-impact + medium fixes (11 locations)
- `fetcher/alpha_vantage.py`: listing disk cache
- `config.py`: mtime revalidation
- `database.py`: pool size 8→15
- `pipeline/fast_evaluation.py`: `_count_by_opinion()` dedup
- `ingestion/pipeline.py`: merge session, prefetch indicator existence, remove redundant `load_config()`
- `app.py`: queue drop warning
- `ui/pages/stock_lookup.py`: covered by Batch 3

## Rollback

All changes are self-contained per batch. To revert: `git checkout` the modified files.

## Verification

- Batch 1-2: `py_compile` + `PYTHONPATH=src python src/full_pipeline.py --dry-run`
- Batch 3: `py_compile` on all UI pages
- Batch 4: `py_compile` + full pipeline dry-run
