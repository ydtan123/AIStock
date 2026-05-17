"""Smoke test verifying ai-hedge-fund and TradingAgents are importable
in-process from the AIStock venv. If this test fails, deps need install.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ai_hedge_fund_importable():
    sys.path.insert(0, str(REPO_ROOT / "external" / "ai-hedge-fund"))
    try:
        from src.main import run_hedge_fund  # noqa: F401
    finally:
        sys.path.pop(0)


def test_trading_agents_importable():
    from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: F401


def test_langgraph_importable():
    import langgraph  # noqa: F401
    from langgraph.graph import StateGraph, END  # noqa: F401


def test_langchain_core_importable():
    from langchain_core.messages import HumanMessage  # noqa: F401
