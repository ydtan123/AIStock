"""Full Pipeline runner page — replaces the old Overview page."""
from __future__ import annotations

import html as _html
import queue
import threading
import time
from collections import deque
from pathlib import Path

import streamlit as st

_LOG_ROW_HEIGHT_PX = 16   # approximate px per monospace line
_LOG_VISIBLE_ROWS = 100
_LOG_HEIGHT_PX = _LOG_ROW_HEIGHT_PX * _LOG_VISIBLE_ROWS


def _render_log(st_ctx, log_text: str) -> None:
    escaped = _html.escape(log_text)
    st_ctx.markdown(
        f'<div style="height:{_LOG_HEIGHT_PX}px;overflow-y:auto;'
        f'background:#0d1117;color:#c9d1d9;font-family:monospace;'
        f'font-size:12px;line-height:{_LOG_ROW_HEIGHT_PX}px;'
        f'padding:12px;border-radius:4px;white-space:pre-wrap;">'
        f'{escaped}</div>',
        unsafe_allow_html=True,
    )


# ── config defaults from config.yaml (API keys excluded) ─────────────────────

def _load_yaml_defaults() -> dict:
    try:
        from config import load_config
        return load_config()
    except Exception:
        return {}


def _flatten_config(cfg: dict, prefix: str = "") -> dict[str, object]:
    """Flatten nested dict to dotted keys, skipping API key fields."""
    out: dict[str, object] = {}
    _SKIP = {"api_key", "database", "common", "alpha_vantage_api_key"}
    for key, value in cfg.items():
        if key in _SKIP:
            continue
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and not (
            isinstance(value, list)
            and all(not isinstance(item, dict) for item in value)
        ):
            out.update(_flatten_config(value, full_key))
        else:
            out[full_key] = value
    return out


# ── step definitions ─────────────────────────────────────────────────────────

_STEPS = [
    {
        "name": "data_update",
        "label": "1. Data Update",
        "help": "Fetch daily prices & fundamentals for active stocks.",
        "params": {
            "data_update.source": {
                "label": "Source",
                "type": "select",
                "options": ["alpha_vantage", "yahoo"],
            },
        },
    },
    {
        "name": "stock_selection",
        "label": "2. Stock Selection",
        "help": "ML-based stock ranking using FinRL pipeline.",
        "params": {
            "stock_selection.backend": {
                "label": "Backend", "type": "select", "options": ["finrl"],
            },
            "stock_selection.finrl.source": {
                "label": "Data Source", "type": "select",
                "options": ["AISTOCK_DB", "FMP", "WRDS", "YAHOO"],
            },
            "stock_selection.finrl.start_date": {
                "label": "Start Date", "type": "text",
            },
            "stock_selection.finrl.end_date": {
                "label": "End Date", "type": "text",
            },
            "stock_selection.finrl.top_quantile": {
                "label": "Top Quantile", "type": "number",
                "min": 0.0, "max": 1.0, "step": 0.05,
            },
            "stock_selection.finrl.test_quarters": {
                "label": "Test Quarters", "type": "number",
                "min": 1, "max": 40, "step": 1,
            },
            "stock_selection.finrl.prediction_mode": {
                "label": "Prediction Mode", "type": "select",
                "options": ["regression", "classification", "ensemble",
                            "rolling", "single"],
            },
            "stock_selection.finrl.weight_method": {
                "label": "Weight Method", "type": "select",
                "options": ["equal", "inverse_volatility", "ml_score"],
            },
            "stock_selection.finrl.rebalance_freq": {
                "label": "Rebalance Freq", "type": "select",
                "options": ["Q", "M", "A"],
            },
            "stock_selection.finrl.initial_capital": {
                "label": "Initial Capital ($)", "type": "number",
                "min": 10000, "step": 10000,
            },
            "stock_selection.finrl.benchmarks": {
                "label": "Benchmarks", "type": "multiselect",
                "options": ["SPY", "QQQ", "DIA", "IWM", "VTI"],
            },
        },
    },
    {
        "name": "fast_evaluation",
        "label": "3. Fast Evaluation",
        "help": "Multi-analyst LLM consensus scoring per stock.",
        "params": {
            "fast_evaluation.top_n": {
                "label": "Top N stocks (from Step 2)", "type": "number",
                "min": 1, "max": 50, "step": 1,
            },
            "fast_evaluation.backend": {
                "label": "Backend", "type": "select",
                "options": ["ai_hedge_fund"],
            },
            "fast_evaluation.ai_hedge_fund.start_date": {
                "label": "Start Date", "type": "text",
            },
            "fast_evaluation.ai_hedge_fund.end_date": {
                "label": "End Date", "type": "text",
            },
            "fast_evaluation.ai_hedge_fund.model_name": {
                "label": "Model Name", "type": "text",
            },
            "fast_evaluation.ai_hedge_fund.model_provider": {
                "label": "Model Provider", "type": "select",
                "options": ["DeepSeek", "OpenAI", "Anthropic", "Google"],
            },
            "fast_evaluation.ai_hedge_fund.initial_cash": {
                "label": "Initial Cash", "type": "number",
                "min": 1000.0, "step": 10000.0,
            },
            "fast_evaluation.ai_hedge_fund.margin_requirement": {
                "label": "Margin Requirement", "type": "number",
                "min": 0.0, "max": 1.0, "step": 0.1,
            },
            "fast_evaluation.ai_hedge_fund.show_reasoning": {
                "label": "Show Reasoning", "type": "checkbox",
            },
            "fast_evaluation.ai_hedge_fund.selected_analysts": {
                "label": "Selected Analysts", "type": "multiselect",
                "options": [
                    "aswath_damodaran", "ben_graham", "bill_ackman",
                    "cathie_wood", "charlie_munger", "michael_burry",
                    "mohnish_pabrai", "nassim_taleb", "peter_lynch",
                    "phil_fisher", "rakesh_jhunjhunwala",
                    "stanley_druckenmiller", "warren_buffett",
                    "technical_analyst", "fundamentals_analyst",
                    "growth_analyst", "news_sentiment_analyst",
                    "sentiment_analyst", "valuation_analyst",
                ],
            },
        },
    },
    {
        "name": "deep_evaluation",
        "label": "4. Deep Evaluation",
        "help": "Multi-agent LLM trading firm simulation with debate & risk analysis.",
        "params": {
            "deep_evaluation.top_n": {
                "label": "Top N stocks (from Step 3)", "type": "number",
                "min": 1, "max": 20, "step": 1,
            },
            "deep_evaluation.backend": {
                "label": "Backend", "type": "select",
                "options": ["trading_agents"],
            },
            "deep_evaluation.trading_agents.model_name": {
                "label": "Deep Model", "type": "text",
            },
            "deep_evaluation.trading_agents.quick_model": {
                "label": "Quick Model", "type": "text",
            },
            "deep_evaluation.trading_agents.model_provider": {
                "label": "Model Provider", "type": "select",
                "options": ["deepseek", "openai", "anthropic", "google"],
            },
            "deep_evaluation.trading_agents.selected_analysts": {
                "label": "Analyst Types", "type": "multiselect",
                "options": ["market", "social", "news", "fundamentals"],
            },
            "deep_evaluation.trading_agents.max_debate_rounds": {
                "label": "Max Debate Rounds", "type": "number",
                "min": 1, "max": 5, "step": 1,
            },
            "deep_evaluation.trading_agents.max_risk_discuss_rounds": {
                "label": "Max Risk Rounds", "type": "number",
                "min": 1, "max": 5, "step": 1,
            },
            "deep_evaluation.trading_agents.debug": {
                "label": "Debug Mode", "type": "checkbox",
            },
            "deep_evaluation.trading_agents.checkpoint_enabled": {
                "label": "Checkpointing", "type": "checkbox",
            },
            "deep_evaluation.trading_agents.use_news_cache": {
                "label": "Use News Cache", "type": "checkbox",
            },
            "deep_evaluation.trading_agents.summary_model": {
                "label": "Summary Model", "type": "text",
            },
            "deep_evaluation.trading_agents.summary_provider": {
                "label": "Summary Provider", "type": "select",
                "options": ["deepseek", "openai", "anthropic", "google"],
            },
        },
    },
]


# ── render helpers ───────────────────────────────────────────────────────────

def _render_param(key: str, meta: dict, defaults: dict, session_key: str) -> None:
    """Render a single config parameter widget, prefilled from defaults."""
    default_val = defaults.get(key)
    ptype = meta.get("type", "text")

    if ptype == "select":
        options = meta.get("options", [])
        idx = options.index(default_val) if default_val in options else 0
        st.session_state[session_key] = st.selectbox(
            meta["label"], options, key=f"fp_{session_key}", index=idx,
        )
    elif ptype == "multiselect":
        options = meta.get("options", [])
        if isinstance(default_val, list):
            default_list = default_val
        elif default_val is None:
            default_list = options
        else:
            default_list = []
        st.session_state[session_key] = st.multiselect(
            meta["label"], options, default=default_list, key=f"fp_{session_key}",
        )
    elif ptype == "number":
        v = default_val
        step = meta.get("step")
        # Streamlit requires min/max/value/step all same numeric type
        if isinstance(step, int) or (isinstance(step, float) and step == int(step) and step >= 1.0):
            cast = int
        else:
            cast = float
        st.session_state[session_key] = st.number_input(
            meta["label"],
            min_value=cast(meta["min"]) if meta.get("min") is not None else None,
            max_value=cast(meta["max"]) if meta.get("max") is not None else None,
            value=cast(v) if v is not None else None,
            step=cast(step) if step is not None else None,
            key=f"fp_{session_key}",
        )
    elif ptype == "checkbox":
        st.session_state[session_key] = st.checkbox(
            meta["label"], value=bool(default_val), key=f"fp_{session_key}",
        )
    else:
        st.session_state[session_key] = st.text_input(
            meta["label"],
            value=str(default_val) if default_val is not None else "",
            key=f"fp_{session_key}",
        )


# ── main render ──────────────────────────────────────────────────────────────

def render(ctx) -> None:
    """Full Pipeline runner page."""
    ctx.st.header("Full Pipeline")

    yaml_cfg = _load_yaml_defaults()
    flat_defaults = _flatten_config(yaml_cfg)

    # ── step checkboxes ──────────────────────────────────────────────────
    col_steps = ctx.st.columns(len(_STEPS))
    selected_steps: list[str] = []
    for i, step_def in enumerate(_STEPS):
        with col_steps[i]:
            if ctx.st.checkbox(
                step_def["label"], value=True,
                key=f"fp_step_{step_def['name']}",
            ):
                selected_steps.append(step_def["name"])

    ctx.st.divider()

    # ── per-step config expanders ────────────────────────────────────────
    overrides: dict[str, object] = {}
    for step_def in _STEPS:
        if step_def["name"] not in selected_steps:
            continue
        with ctx.st.expander(
            step_def["label"],
            expanded=(len(selected_steps) <= 2),
        ):
            ctx.st.caption(step_def.get("help", ""))
            cols = ctx.st.columns(3)
            param_items = list(step_def.get("params", {}).items())
            for j, (key, meta) in enumerate(param_items):
                with cols[j % 3]:
                    session_key = f"fp_cfg_{key}"
                    if session_key not in st.session_state:
                        st.session_state[session_key] = flat_defaults.get(key)
                    _render_param(key, meta, flat_defaults, session_key)
                    val = st.session_state[session_key]
                    default_val = flat_defaults.get(key)
                    if val is not None and val != "" and val != default_val:
                        overrides[key] = val

    ctx.st.divider()

    # ── run / stop buttons ────────────────────────────────────────────────
    status = ctx.session_state.get("fp_status", "Idle")
    if "fp_log_lines" not in ctx.session_state:
        ctx.session_state.fp_log_lines = deque(maxlen=500)

    c1, c2 = ctx.st.columns([1, 1])
    with c1:
        run_clicked = ctx.st.button(
            "Run Pipeline", type="primary",
            disabled=(status == "Running" or not selected_steps),
        )
    with c2:
        stop_clicked = ctx.st.button(
            "Stop", type="secondary",
            disabled=(status != "Running"),
        )

    if run_clicked and status != "Running":
        ctx.session_state.fp_stop_requested = False
        ctx.session_state.fp_stop_event = threading.Event()
        ctx.session_state.fp_log_lines = deque(maxlen=500)
        ctx.session_state.fp_error = None
        ctx.session_state.fp_report_path = None
        ctx.session_state.fp_log_queue = queue.Queue()
        ctx.session_state.fp_status = "Running"
        ctx.session_state.fp_start_time = time.time()
        ctx.session_state.fp_selected_steps = selected_steps
        ctx.session_state.fp_current_step = None
        ctx.session_state.fp_completed_steps = []

        threading.Thread(
            target=ctx.full_pipeline_thread_target,
            args=(overrides, selected_steps, ctx.session_state.fp_log_queue, ctx.session_state.fp_stop_event),
            daemon=True,
        ).start()
        ctx.st.rerun()

    if stop_clicked and status == "Running":
        ctx.session_state.fp_stop_requested = True
        ctx.session_state.fp_stop_event.set()
        ctx.session_state.fp_status = "Idle"
        ctx.st.rerun()

    # ── real-time log + results fragment ─────────────────────────────────
    @st.fragment(run_every=2)
    def _pipeline_log_fragment():
        fp_queue = ctx.session_state.get("fp_log_queue")
        while fp_queue is not None:
            try:
                line = fp_queue.get_nowait()
            except queue.Empty:
                break
            if line.startswith("__REPORT__:"):
                ctx.session_state.fp_report_path = line.split(":", 1)[1]
                ctx.session_state.fp_status = "Complete"
                # Finalize step progress on completion
                cur = ctx.session_state.get("fp_current_step")
                if cur:
                    done = list(ctx.session_state.get("fp_completed_steps", []))
                    if cur not in done:
                        done.append(cur)
                    ctx.session_state.fp_completed_steps = done
                ctx.session_state.fp_current_step = None
            elif line.startswith("__STOP__:"):
                ctx.session_state.fp_status = "Idle"
            elif line.startswith("__ERROR__:"):
                ctx.session_state.fp_error = line.split(":", 1)[1]
                ctx.session_state.fp_status = "Error"
            else:
                # Parse step transitions from orchestrator log lines
                if "running step:" in line:
                    for step_def in _STEPS:
                        if f"running step: {step_def['name']}" in line:
                            prev = ctx.session_state.get("fp_current_step")
                            if prev:
                                done = list(ctx.session_state.get("fp_completed_steps", []))
                                if prev not in done:
                                    done.append(prev)
                                ctx.session_state.fp_completed_steps = done
                            ctx.session_state.fp_current_step = step_def["name"]
                            break
                elif "step complete:" in line:
                    cur = ctx.session_state.get("fp_current_step")
                    if cur:
                        done = list(ctx.session_state.get("fp_completed_steps", []))
                        if cur not in done:
                            done.append(cur)
                        ctx.session_state.fp_completed_steps = done
                ctx.session_state.fp_log_lines.append(line)

        current_status = ctx.session_state.get("fp_status", "Idle")
        if current_status == "Running":
            elapsed = time.time() - ctx.session_state.get("fp_start_time", time.time())
            ctx.st.info(f"Running...  Elapsed: {elapsed:.0f}s")

            # Step progress indicator
            sel_steps = ctx.session_state.get("fp_selected_steps", [s["name"] for s in _STEPS])
            current_step = ctx.session_state.get("fp_current_step")
            completed_steps = set(ctx.session_state.get("fp_completed_steps", []))
            sel_defs = [s for s in _STEPS if s["name"] in sel_steps]
            if sel_defs:
                step_cols = ctx.st.columns(len(sel_defs))
                for i, sdef in enumerate(sel_defs):
                    with step_cols[i]:
                        if sdef["name"] in completed_steps:
                            ctx.st.markdown(f"✅ **{sdef['label']}**")
                        elif sdef["name"] == current_step:
                            ctx.st.markdown(f"⏳ **{sdef['label']}**")
                        else:
                            ctx.st.markdown(f"⬜ {sdef['label']}")

            ctx.st.subheader("Log Output")
            if ctx.session_state.fp_log_lines:
                log_text = "\n".join(ctx.session_state.fp_log_lines)
                _render_log(ctx.st, log_text)
            else:
                ctx.st.info("Pipeline starting...")

        # Completion — show reports
        fp_report = ctx.session_state.get("fp_report_path")
        if current_status == "Complete" and fp_report:
            ctx.st.subheader("Log Output")
            log_text = "\n".join(ctx.session_state.fp_log_lines)
            _render_log(ctx.st, log_text)
            report_dir = Path(fp_report)
            if report_dir.exists():
                ctx.st.subheader("Reports")
                for ticker_dir in sorted(report_dir.iterdir()):
                    if ticker_dir.is_dir():
                        with ctx.st.expander(str(ticker_dir.name)):
                            deep_eval = ticker_dir / "deep_evaluation" / "summary.md"
                            fast_eval = ticker_dir / "fast_evaluation" / "fast_evaluation.md"
                            if deep_eval.exists():
                                with open(deep_eval) as f:
                                    ctx.st.markdown(f.read())
                            if fast_eval.exists():
                                with open(fast_eval) as f:
                                    ctx.st.markdown(f.read())

    _pipeline_log_fragment()
