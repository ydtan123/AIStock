# TradingAgents Developer Manual

`external/TradingAgents/` — Multi-Agent LLM Financial Trading Framework

---

## 1. Overall Functionality

TradingAgents simulates a trading firm's full research and risk management workflow using a pipeline of specialized LLM agents. Given a ticker symbol and a date, it produces a structured investment decision: **Buy / Overweight / Hold / Underweight / Sell** — with an executive summary, investment thesis, optional price target, and optional time horizon.

### What it does

1. **Gathers data** via pluggable data vendors (yfinance, Alpha Vantage, Google News, or local cache).
2. **Produces four independent analyst reports**: market/technical, fundamentals, macro news, social media sentiment.
3. **Runs a Bull vs Bear research debate** using all four reports as evidence.
4. **Synthesizes** the debate into a structured investment plan (Research Manager).
5. **Translates** the plan into a concrete BUY/SELL/HOLD proposal (Trader).
6. **Runs a three-way risk debate** (aggressive / conservative / neutral) on the trader's proposal.
7. **Delivers a final decision** (Portfolio Manager) with full reasoning.
8. **Learns from outcomes**: compares prediction vs actual return after the fact, stores lessons in a ChromaDB memory log that feeds back into future Portfolio Manager calls for the same ticker.

### Primary outputs

| Artifact | Location |
|----------|----------|
| Decision string | `propagate()` return value |
| Full state JSON | `results/<ticker>/<date>/state.json` |
| Analyst report files | `results/<ticker>/<date>/*.md` |
| Memory log | `data_cache/memory/` (ChromaDB) |

### Entry points

```python
# Programmatic
from tradingagents.graph.trading_graph import TradingAgentsGraph
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")

# Interactive CLI (Rich TUI, prompts for model/ticker/date)
python -m cli.main analyze

# Non-interactive batch CLI
python -m cli.main run --ticker AAPL,NVDA --date 2026-01-15 --skip social
```

### Optional live execution

Completed decisions can be executed on Alpaca Markets (paper or live) via `AlpacaTrader` in `tradingagents/agents/trader/alpaca_trader.py`. This is independent of the analysis pipeline — call it manually after reviewing the decision.

---

## 2. Stock Evaluation: How a Conclusion Is Reached

The pipeline runs as a sequential LangGraph `StateGraph`. All state flows through a single `AgentState` TypedDict.

### Stage 1 — Analyst Team (parallel, async)

Four analysts run concurrently via `asyncio.gather`. Each fetches its own data, runs a tool-call loop (up to 10 iterations), and writes a prose report to a dedicated field in `AgentState`.

| Agent | Report field | Tools used | What it covers |
|-------|-------------|------------|----------------|
| `market_analyst` | `market_report` | `get_stock_data`, `get_indicators` | OHLCV price history, selected technical indicators (SMA-50/200, EMA-10, RSI, Bollinger Bands, MACD, stochastic, etc.) |
| `fundamentals_analyst` | `fundamentals_report` | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` | Revenue, earnings, cash flow, balance sheet ratios, insider transactions |
| `news_analyst` | `news_report` | `get_news`, `get_global_news` | Macro/geopolitical news, company-specific news from the past week |
| `social_media_analyst` | `sentiment_report` | `get_news` | Social media sentiment, public perception, recent company-specific discussions |

Each analyst is prompted to end with a Markdown summary table of key findings.

### Stage 2 — Investment Debate (Bull vs Bear)

The Bull and Bear researchers each receive all four analyst reports and the full debate history. They alternate arguing FOR and AGAINST investing. Each round:

- **Bull Researcher**: argues growth potential, competitive advantages, positive indicators, counters the bear's last point.
- **Bear Researcher**: argues risks, weaknesses, negative indicators, counters the bull's last point.

Rounds repeat `max_debate_rounds` times (default 1). The full transcript is accumulated in `InvestDebateState.history`.

### Stage 3 — Research Manager

Reads the complete debate transcript and produces a structured `ResearchPlan`:

| Field | Description |
|-------|-------------|
| `recommendation` | Buy / Overweight / Hold / Underweight / Sell |
| `rationale` | Which side of the debate carried the argument and why |
| `strategic_actions` | Concrete instructions for the trader (position sizing, entry approach) |

Output stored in `AgentState.investment_plan`.

### Stage 4 — Trader

Reads the Research Manager's plan and translates it to a concrete `TraderProposal`:

| Field | Description |
|-------|-------------|
| `action` | BUY / HOLD / SELL (3-tier, simpler than PortfolioRating) |
| `rationale` | Reasoning anchored in the analysts' reports and the research plan |

Output stored in `AgentState.trader_investment_plan`.

### Stage 5 — Risk Debate (three-way)

Three risk analysts each see the full analyst reports AND the trader's decision. They argue simultaneously for `max_risk_discuss_rounds` rounds:

| Agent | Stance |
|-------|--------|
| `aggressive_debator` | High-reward, bold strategies; challenges conservative and neutral on missed opportunities |
| `conservative_debator` | Asset protection, volatility minimization; challenges aggressive and neutral on overlooked risks |
| `neutral_debator` | Balanced risk/reward; synthesizes both extremes |

Each builds on the previous round's arguments from the other two. The full three-way transcript accumulates in `RiskDebateState.history`.

### Stage 6 — Portfolio Manager (final decision)

Reads: Research Manager's plan + Trader's proposal + full risk debate + `past_context` from memory log.

Produces a structured `PortfolioDecision`:

| Field | Description |
|-------|-------------|
| `rating` | Buy / Overweight / Hold / Underweight / Sell |
| `executive_summary` | Entry strategy, position sizing, key risk levels, time horizon (2–4 sentences) |
| `investment_thesis` | Detailed reasoning anchored in specific analyst evidence |
| `price_target` | Optional target price |
| `time_horizon` | Optional recommended holding period |

This is the final output. Stored in `AgentState.final_trade_decision` as rendered Markdown.

### Stage 7 — Memory and Reflection (deferred)

On the next call to `propagate()` for the same ticker, the system:

1. Fetches the actual price return since the previous decision date.
2. Compares to the prior prediction (alpha vs benchmark).
3. Calls `reflect_and_remember()` — the quick-thinking LLM generates lessons from the outcome.
4. Stores lessons in ChromaDB under the ticker.
5. Injects `past_context` (recent lessons) into the Portfolio Manager prompt for the new run.

This creates a feedback loop: the system learns from its own past mistakes and correct calls.

### Full pipeline at a glance

```
propagate(ticker, date)
  │
  ├─ _resolve_pending_entries()          # fetch actual returns, update memory for prior calls
  │
  ├─ [async] Analyst Team
  │    ├─ market_analyst     → market_report
  │    ├─ fundamentals_analyst → fundamentals_report
  │    ├─ news_analyst       → news_report
  │    └─ social_media_analyst → sentiment_report
  │
  ├─ [loop × max_debate_rounds]
  │    ├─ bull_researcher    → InvestDebateState.history
  │    └─ bear_researcher    → InvestDebateState.history
  │
  ├─ research_manager        → investment_plan (ResearchPlan)
  │
  ├─ trader                  → trader_investment_plan (TraderProposal)
  │
  ├─ [loop × max_risk_discuss_rounds]
  │    ├─ aggressive_debator → RiskDebateState.history
  │    ├─ conservative_debator
  │    └─ neutral_debator
  │
  └─ portfolio_manager       → final_trade_decision (PortfolioDecision)
```

---

## 3. Configuring Data Sources and LLMs

All configuration lives in `tradingagents/default_config.py`. Pass a modified copy to `TradingAgentsGraph(config=...)`.

### 3.1 LLM Provider

```python
config["llm_provider"] = "openai"   # see table below
config["deep_think_llm"] = "o4-mini"       # complex reasoning: Research Manager, Portfolio Manager
config["quick_think_llm"] = "gpt-4o-mini"  # fast tasks: reflection, summarization
config["backend_url"] = "https://api.openai.com/v1"  # override for Azure, Ollama, etc.
```

| Provider value | API key env var | Notes |
|----------------|----------------|-------|
| `openai` | `OPENAI_API_KEY` | Default |
| `anthropic` | `ANTHROPIC_API_KEY` | Uses tool-use for structured output |
| `google` | `GOOGLE_API_KEY` | Uses response_schema for structured output |
| `xai` | `XAI_API_KEY` | Grok models |
| `deepseek` | `DEEPSEEK_API_KEY` | |
| `qwen` | `DASHSCOPE_API_KEY` | Alibaba DashScope |
| `glm` | `ZHIPU_API_KEY` | Zhipu |
| `openrouter` | `OPENROUTER_API_KEY` | Routes to many models |
| `ollama` | none | Local; set `backend_url` to Ollama endpoint |
| `azure` | see `.env.enterprise.example` | Set `backend_url` to Azure endpoint |

Provider-specific reasoning controls:

```python
config["openai_reasoning_effort"] = "high"   # openai o-series models
config["google_thinking_level"] = "high"      # Gemini thinking models
config["anthropic_effort"] = "high"           # Anthropic extended thinking
```

Set API keys via environment variables or `.env` file:

```bash
cp .env.example .env
# fill in keys
```

### 3.2 Data Vendors

Four data categories, each independently configurable:

```python
config["data_vendors"] = {
    "core_stock_apis":       "yfinance",      # OHLCV price + volume data
    "technical_indicators":  "yfinance",      # indicator computation
    "fundamental_data":      "alpha_vantage", # balance sheet, earnings, etc.
    "news_data":             "alpha_vantage", # news articles
}
```

| Category | Options |
|----------|---------|
| `core_stock_apis` | `yfinance`, `alpha_vantage`, `local` |
| `technical_indicators` | `yfinance`, `alpha_vantage`, `local` |
| `fundamental_data` | `openai` (web search), `alpha_vantage`, `local` |
| `news_data` | `alpha_vantage`, `google`, `openai` (web search), `local` |

**Per-tool overrides** (take precedence over category defaults):

```python
config["tool_vendors"] = {
    "get_news": "google",          # override news to Google News
    "get_fundamentals": "openai",  # override fundamentals to OpenAI web search
}
```

Routing is implemented in `tradingagents/dataflows/interface.py` — the `TOOL_VENDOR_MAP` and `TOOL_CATEGORY_MAP` dicts map every tool name to its vendor-specific implementation function.

### 3.3 Required API keys by data vendor

| Vendor | Key |
|--------|-----|
| yfinance | none (free) |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` |
| Google News | `GOOGLE_API_KEY` |
| Alpaca (live/paper trading) | `ALPACA_API_KEY` + `ALPACA_API_SECRET` |

**Minimum viable setup (no paid data APIs):**

```python
config["data_vendors"] = {
    "core_stock_apis":      "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data":     "yfinance",
    "news_data":            "yfinance",
}
```

Only requires one LLM provider API key. Alpha Vantage provides richer fundamentals and news; yfinance fundamentals coverage is adequate for most use cases.

### 3.4 Debate depth and recursion

```python
config["max_debate_rounds"] = 1       # Bull vs Bear rounds (higher = deeper but more LLM calls)
config["max_risk_discuss_rounds"] = 1  # Risk team rounds
config["max_recur_limit"] = 100        # LangGraph recursion guard
```

### 3.5 Output language

```python
config["output_language"] = "English"  # or "Chinese", "Japanese", etc.
```

All analyst reports and decisions will be generated in this language.

### 3.6 Checkpoint/resume

```python
config["checkpoint_enabled"] = True  # persist state after each node via SqliteSaver
```

If a run crashes, re-running the same ticker+date resumes from the last successful node instead of restarting from scratch. Use `--checkpoint` flag in the CLI.

---

## 4. Code Architecture

### 4.1 Package structure

```
tradingagents/
├── default_config.py           # DEFAULT_CONFIG dict — single source of truth
├── llm_clients/
│   ├── factory.py              # create_llm_client(provider, model, ...) dispatcher
│   └── <provider>_client.py   # one file per LLM provider (openai, anthropic, google, ...)
├── dataflows/
│   ├── interface.py            # vendor routing: TOOL_VENDOR_MAP, TOOL_CATEGORY_MAP
│   ├── config.py               # get_config() / set_config() — runtime config accessor
│   ├── alpha_vantage_*.py      # Alpha Vantage API wrappers (stock, indicator, fundamentals, news)
│   ├── yfinance_*.py           # yfinance wrappers
│   ├── googlenews_utils.py     # Google News wrapper
│   └── stockstats_utils.py     # stockstats indicator computation
├── agents/
│   ├── schemas.py              # Pydantic: ResearchPlan, TraderProposal, PortfolioDecision
│   ├── analysts/
│   │   ├── analyst_team.py     # async parallel launcher for all selected analysts
│   │   ├── fundamentals_analyst.py
│   │   ├── market_analyst.py
│   │   ├── news_analyst.py
│   │   └── social_media_analyst.py
│   ├── researchers/
│   │   ├── bull_researcher.py
│   │   └── bear_researcher.py
│   ├── managers/
│   │   ├── research_manager.py # synthesizes debate → ResearchPlan
│   │   └── portfolio_manager.py # synthesizes risk debate → PortfolioDecision (final)
│   ├── risk_mgmt/
│   │   ├── aggressive_debator.py
│   │   ├── conservative_debator.py
│   │   └── neutral_debator.py
│   ├── trader/
│   │   ├── trader.py           # ResearchPlan → TraderProposal
│   │   └── alpaca_trader.py    # optional live/paper order execution
│   └── utils/
│       ├── agent_states.py     # AgentState, InvestDebateState, RiskDebateState TypedDicts
│       ├── agent_utils.py      # tool wrapper functions exposed to LLM agents
│       ├── core_stock_tools.py
│       ├── fundamental_data_tools.py
│       ├── news_data_tools.py
│       ├── technical_indicators_tools.py
│       ├── memory.py           # TradingMemoryLog (ChromaDB wrapper)
│       ├── structured.py       # bind_structured / invoke_structured_or_freetext helpers
│       └── rating.py
└── graph/
    ├── trading_graph.py        # TradingAgentsGraph — main class, initialize + propagate()
    ├── setup.py                # GraphSetup — LangGraph StateGraph node/edge wiring
    ├── conditional_logic.py    # ConditionalLogic — debate round routing
    ├── propagation.py          # Propagator — AgentState initialization
    ├── reflection.py           # Reflector — post-trade lessons via ChromaDB
    ├── signal_processing.py    # SignalProcessor — extracts decision string from final state
    └── checkpointer.py         # SqliteSaver checkpoint management
cli/
├── main.py                     # Typer app: `analyze` (interactive TUI) + `run` (batch)
├── models.py                   # AnalystType enum, config models
├── utils.py                    # questionary prompts for interactive mode
└── stats_handler.py            # LangChain callback handler for LLM call counting
```

### 4.2 State objects

Three TypedDicts are passed through the graph:

**`AgentState`** — top-level state:
- `company_of_interest`, `trade_date` — inputs
- `messages` — LangChain message list (used by analyst tool-call loops)
- `market_report`, `sentiment_report`, `news_report`, `fundamentals_report` — analyst outputs
- `investment_plan` — Research Manager output (rendered `ResearchPlan`)
- `trader_investment_plan` — Trader output (rendered `TraderProposal`)
- `final_trade_decision` — Portfolio Manager output (rendered `PortfolioDecision`)
- `investment_debate_state` — nested `InvestDebateState`
- `risk_debate_state` — nested `RiskDebateState`
- `past_context` — prior lessons from memory log

**`InvestDebateState`**:
- `history`, `bull_history`, `bear_history` — full and per-side transcripts
- `current_response` — last argument (next agent responds to this)
- `count` — current round number

**`RiskDebateState`**:
- `history`, `aggressive_history`, `conservative_history`, `neutral_history`
- `current_aggressive_response`, `current_conservative_response`, `current_neutral_response`
- `count` — current round number

### 4.3 Graph wiring (`setup.py`)

`GraphSetup.build_graph()` constructs a LangGraph `StateGraph(AgentState)`:

```
START
  │
  ▼
analyst_team_node          (async parallel — all selected analysts)
  │
  ▼
[bull_node → bear_node] × max_debate_rounds   (conditional edge via ConditionalLogic)
  │
  ▼
research_manager_node
  │
  ▼
trader_node
  │
  ▼
[aggressive_node → conservative_node → neutral_node] × max_risk_discuss_rounds
  │
  ▼
portfolio_manager_node
  │
  ▼
END
```

`ConditionalLogic` routes back to the start of each debate loop until the round counter reaches the configured maximum.

### 4.4 Structured output (`schemas.py` + `structured.py`)

Three agents produce structured Pydantic objects instead of free text:
- `ResearchPlan` (Research Manager)
- `TraderProposal` (Trader)
- `PortfolioDecision` (Portfolio Manager)

`bind_structured(llm, Schema, agent_name)` wraps the LLM with `with_structured_output` using the provider's native mechanism (json_schema for OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic). `invoke_structured_or_freetext` gracefully falls back to free-text parsing when structured output is unavailable.

`render_*(obj)` functions convert parsed Pydantic instances back to the Markdown format the rest of the pipeline and report files already consume — no format changes downstream.

### 4.5 Data vendor routing (`dataflows/interface.py`)

`TOOL_VENDOR_MAP` maps each tool name to its vendor-specific implementation:

```python
# Example routing
"get_stock_data" → {
    "yfinance":       get_yfin_data_online,
    "alpha_vantage":  get_alpha_vantage_stock,
    "local":          get_yfin_data_local,
}
"get_news" → {
    "alpha_vantage":  get_alpha_vantage_news,
    "google":         get_googlenews,
    "openai":         get_openai_news,
    "yfinance":       get_news_yfinance,
}
```

At runtime, `interface.py` checks `tool_vendors` for a per-tool override first, then falls back to the `data_vendors` category default. The agent code always calls the abstract wrapper (e.g., `get_news`) — it never knows which vendor supplies the data.

### 4.6 LLM client factory (`llm_clients/factory.py`)

`create_llm_client(provider, model, base_url, **kwargs)` returns a provider-specific client object with a `.get_llm()` method that returns the LangChain chat model. Provider kwargs (thinking levels, reasoning effort) are passed through as constructor arguments.

Two LLM instances are created at startup:
- `deep_thinking_llm`: used by Research Manager, Portfolio Manager, and complex analyst prompts
- `quick_thinking_llm`: used by Trader, Reflector, report summarization

### 4.7 Memory log (`agents/utils/memory.py`)

`TradingMemoryLog` wraps a ChromaDB collection stored in `data_cache_dir/memory/`:

| Method | Purpose |
|--------|---------|
| `store_decision(ticker, date, decision)` | Saves pending decision; awaits actual return |
| `batch_update_with_outcomes(updates)` | When actual returns arrive: LLM generates lessons, stores to ChromaDB |
| `get_past_context(ticker)` | Retrieves recent lessons for Portfolio Manager prompt |

### 4.8 CLI modes

**Interactive (`analyze`)**: Rich TUI with `questionary` prompts. Selects ticker, date, LLM provider, deep/quick models, analysts, debate depth, output language, and checkpoint mode. Streams the graph in real time with a live panel showing agent activity, token counts, and accumulated messages.

**Batch (`run`)**: Non-interactive. All settings from `DEFAULT_CONFIG`. Accepts multiple tickers via `--ticker AAPL,NVDA`. Skips individual analysts with `--skip social`. Outputs a Rich summary table with BUY/SELL/HOLD per ticker and LLM-generated 3-bullet summaries of each analyst report.

---

## 5. Quick-Start Examples

### Minimum viable (yfinance only, OpenAI)

```bash
export OPENAI_API_KEY=sk-...
cd external/TradingAgents
pip install -e .
python -m cli.main run --ticker AAPL --date 2026-01-15
```

### Custom provider and data sources

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "anthropic"
config["deep_think_llm"] = "claude-opus-4-7"
config["quick_think_llm"] = "claude-haiku-4-5-20251001"
config["max_debate_rounds"] = 2
config["max_risk_discuss_rounds"] = 2
config["data_vendors"]["news_data"] = "google"
config["data_vendors"]["fundamental_data"] = "alpha_vantage"

ta = TradingAgentsGraph(
    selected_analysts=["market", "fundamentals", "news"],  # skip social
    config=config,
    debug=True,
)
_, decision = ta.propagate("TSLA", "2026-01-15")
print(decision)

# After position is closed, reflect on the outcome
ta.reflect_and_remember(pct_return=0.08)  # 8% return
```

### Skip slow analysts

```bash
python -m cli.main run --ticker MSFT --skip social --skip news
```

### Checkpoint/resume after crash

```bash
python -m cli.main analyze --checkpoint
# If it crashes mid-run, re-run the same command — it resumes from last completed node
python -m cli.main analyze --checkpoint --clear-checkpoints  # force fresh start
```
