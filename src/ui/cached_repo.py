"""Shared @st.cache_data wrappers for StockRepository queries."""
import streamlit as st
from datetime import date

import pandas as pd
from repository import StockRepository


@st.cache_data(ttl=300, show_spinner=False)
def cached_find_stock(symbol: str) -> dict | None:
    stock = StockRepository().find_stock(symbol)
    if stock is None:
        return None
    return {"id": stock.id, "symbol": stock.symbol, "name": stock.name,
            "exchange": stock.exchange, "sector": stock.sector,
            "industry": stock.industry, "is_active": stock.is_active}


@st.cache_data(ttl=60, show_spinner=False)
def cached_get_prices(stock_id: int, start_str: str, end_str: str) -> pd.DataFrame:
    return StockRepository().get_prices(stock_id, date.fromisoformat(start_str), date.fromisoformat(end_str))
