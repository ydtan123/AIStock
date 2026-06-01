# Security Audit Report — AIStock `src/`

**Date:** 2026-05-30 (updated)  
**Scope:** `src/` directory + `config.yaml`  
**Auditor:** Automated scan via Claude Code `/security-audit`

---

## Summary

| Severity | Count | Delta |
|----------|-------|-------|
| 🚨 CRITICAL | 4 | +2 (env injection) |
| ⚠️ HIGH | 3 | +1 (path traversal) |
| 🔵 MEDIUM | 3 | — |
| ✅ LOW / INFO | 4 | — |

---

## 🚨 CRITICAL

### C1 — Live API Keys in `config.yaml`

**File:** `config.yaml` lines 6, 9, 15, 18, 21

Three live API keys in plaintext, duplicated across 3 config sections:

```yaml
common:
  deepseek_api_key: "sk-96c8c56a71f64942bf5c6630bd8a9924"
  google_api_key:   "AIzaSyBWRCPmYpHwI_yF3MHWMCrmMe2A92-QkbU"

data_update:
  alpha_vantage:
    api_key: "FQZDH795B6P1JXSU"

google:     # duplicate of common
  api_key: "AIzaSyBWRCPmYpHwI_yF3MHWMCrmMe2A92-QkbU"

deepseek:   # duplicate of common
  api_key: "sk-96c8c56a71f64942bf5c6630bd8a9924"
```

**Mitigation:** `config.yaml` IS in `.gitignore` (confirmed via `git check-ignore`).  
**Residual risk:** Plaintext keys on disk. Duplicate keys across sections — rotating one leaves others stale.

**Fix:**
1. Rotate all three keys (DeepSeek console, Google Cloud Console, Alpha Vantage).
2. Replace values with empty strings in `config.yaml`; load only from env vars.
3. Remove duplicate `google:` and `deepseek:` top-level sections — use `common:` only.

---

### C2 — Database Credentials Hardcoded in `config.yaml`

**File:** `config.yaml:57`

```yaml
database:
  url: "mysql+pymysql://stockdb:stockdb123@localhost/stockdb"
```

Weak password (`stockdb123`) in plaintext.

**Fix:** Load from `DATABASE_URL` env var. Rotate to strong password for non-localhost deployments.

---

### C3 — Live Alpaca Trading Secret in `external/TradingAgents/.env`

**File:** `external/TradingAgents/.env`

```
ALPACA_API_KEY="PKWM4NUX..."
ALPACA_API_SECRET="6Rrdzuf..."    ← Live trading account secret
ALPACA_PAPER="true"
```

Plus DeepSeek, Google, Alpha Vantage keys. The Alpaca secret grants trading capability — **financial risk** even in paper mode.

**Fix:** Rotate the Alpaca secret immediately. Remove all live keys from submodule `.env` files.

---

### C4 — API Keys Injected into Global `os.environ` [NEW]

**Affected files (3 injection sites):**

| File | Line | Trigger |
|------|------|---------|
| `src/ingestion/pipeline.py` | 28-36 | Module-level — runs on **import** |
| `src/pipeline/backends/fast_evaluators.py` | 89 | Per-evaluation call |
| `src/pipeline/backends/deep_evaluators.py` | 70 | Per-evaluation call |

```python
# ingestion/pipeline.py — module-level side effect on import
for _env_key, _cfg_key in [
    ("GOOGLE_API_KEY", "google_api_key"),
    ("DEEPSEEK_API_KEY", "deepseek_api_key"),
    ("OPENAI_API_KEY", "openai_api_key"),
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
]:
    if _common.get(_cfg_key) and _env_key not in os.environ:
        os.environ[_env_key] = _common[_cfg_key]

# fast_evaluators.py / deep_evaluators.py — identical pattern
for env_var, value in mapping.items():
    if value and not os.environ.get(env_var):
        os.environ[env_var] = value
```

**Risk:**
- Secrets leak to **all child processes** (`subprocess.run`, `fork`)
- Any imported library can read API keys via `os.environ`
- Module-level injection means secrets propagate at import time, not call time
- Python tracebacks from child processes may include env vars

**Fix:**
- Never modify `os.environ` globally. Pass secrets via explicit function parameters or context objects.
- If a library requires env vars, set them in a per-subprocess `env` dict, not globally.
- Wrap in a context manager that saves/restores original env state.

---

## ⚠️ HIGH

### H1 — XSS via `unsafe_allow_html=True` with DB Data [UPDATED — refactored locations]

**Primary risk:** `src/ui/pages/stock_lookup.py:25-32`

```python
ctx.st.markdown(f"""
<div ...>
  <div ...>{stock.name or symbol}</div>      ← from DB, unsanitized
  <div>{stock.exchange or '—'} · {stock.sector or '—'}</div>
  <div>{stock.industry or '—'}</div>         ← from DB, unsanitized
</div>
""", unsafe_allow_html=True)
```

If attacker poisons DB fields (stock name, exchange, sector, industry), HTML/JS executes in Streamlit dashboard.

**All `unsafe_allow_html=True` sites scanned:**

| File | Line(s) | Data source | Risk |
|------|---------|-------------|------|
| `src/ui/pages/stock_lookup.py` | 25-32 | DB text fields | **XSS** |
| `src/ui/pages/stock_lookup.py` | 53-62 | Numeric (format specifiers) | Low |
| `src/ui/pages/stock_screener.py` | 9 | Static string | None |
| `src/ui/pages/stock_manager.py` | 11 | Static string | None |
| `src/ui/pages/stock_technical.py` | 11 | Static string | None |
| `src/ui/pages/job_history.py` | 8 | Static string | None |
| `src/app.py` | 47, 268-269 | Static HTML | None |

**Fix:**
```python
from html import escape
ctx.st.markdown(f'...{escape(stock.name or symbol)}...', unsafe_allow_html=True)
```
Or replace with native Streamlit components (`st.metric`, `st.container`) that don't require `unsafe_allow_html`.

---

### H2 — File Access via User-Selected Path [NEW]

**File:** `src/ui/pages/strategy_backtest.py:30`

```python
with open(selected_path) as f:
```

`selected_path` comes from `st.selectbox` populated by directory listing. No path validation — if options are manipulated, this becomes path traversal.

**Fix:**
```python
import os
allowed_dir = os.path.abspath("data")
resolved = os.path.abspath(selected_path)
if not resolved.startswith(allowed_dir):
    raise ValueError("Path traversal blocked")
```

---

### H3 — No Input Validation on User Inputs

**Files:** `src/app.py`, `src/ui/pages/` (multiple)

Streamlit text inputs, number inputs lack server-side validation:
- Symbol inputs: no length/alphanumeric check
- Date inputs: no range validation
- File uploads: no size limit or type verification

**Fix:** Add validation:
```python
import re
if not re.match(r'^[A-Z]{1,5}$', symbol):
    st.error("Invalid symbol")
    return
```

---

## 🔵 MEDIUM

### M1 — No Pre-commit Secret Scanning

No `.pre-commit-config.yaml` found. API keys can be accidentally committed via `git add -f` or if `.gitignore` is modified.

**Fix:**
```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

---

### M2 — No Encryption At Rest for Secrets

All API keys stored as plaintext:
- `config.yaml` — YAML plaintext
- `external/*/.env` — shell variable plaintext
- Loaded into `os.environ` — visible to entire process tree

**Fix:** Use OS keychain (`keyring` library) for local dev. At minimum, `chmod 600` on secret files.

---

### M3 — Commented-Out Old API Key

**File:** `external/TradingAgents/.env`

```bash
#OPENAI_API_KEY="sk-proj-VHa6exQ..." ← Old key visible in comment
```

If this key was once live, rotate it and remove the comment.

---

## ✅ Confirmed-Safe Patterns

| Pattern | Location | Status |
|---------|----------|--------|
| `yaml.safe_load` | `src/pipeline/config.py` | ✅ Safe |
| SQLAlchemy parameterized queries | `src/repository.py` | ✅ No SQL injection |
| No `pickle.load` in `src/` | All `src/` files | ✅ Safe |
| `.env` in `.gitignore` | `.gitignore:12` | ✅ Protected |
| `config.yaml` in `.gitignore` | `.gitignore:13` | ✅ Protected |

---

## Remediation Priority

| # | Finding | Sev | Effort |
|---|---------|-----|--------|
| 1 | C3 — Rotate Alpaca API secret | 🚨 | 30 min |
| 2 | C1 — Rotate DeepSeek, Google, AV keys | 🚨 | 30 min |
| 3 | C2 — Move DB URL to env var | 🚨 | 30 min |
| 4 | C4 — Replace `os.environ` injection | 🚨 | 2 h |
| 5 | H1 — Add `html.escape()` to XSS vectors | ⚠️ | 1 h |
| 6 | H2 — Add path traversal guard | ⚠️ | 15 min |
| 7 | M2 — `chmod 600` on secret files | 🔵 | 5 min |
| 8 | H3 — Add input validation layer | ⚠️ | 1 h |
| 9 | M1 — Add `detect-secrets` pre-commit | 🔵 | 30 min |
| 10 | M3 — Remove commented-out keys | 🔵 | 5 min |

---

*Report generated by `/security-audit` skill. Scope: `src/` + `config.yaml`. Prior audit: `docs/security-audit-domino.md`.*
