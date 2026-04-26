from datetime import date
import pandas as pd
import yfinance as yf

from fetcher.base import FetcherBase


class YahooFetcher(FetcherBase):

    def get_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        df = df.rename(columns={
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "adj_close": "adj_close",
            "volume": "volume",
            "dividends": "dividend_amount",
            "stock_splits": "split_coefficient",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.date
        cols = ["date", "open", "high", "low", "close", "adj_close", "volume", "dividend_amount", "split_coefficient"]
        return df[[c for c in cols if c in df.columns]]

    def get_overview(self, symbol: str) -> dict:
        info = yf.Ticker(symbol).info
        return {
            "symbol": symbol,
            "name": info.get("longName"),
            "asset_type": "Common Stock",
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "country": info.get("country"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "shares_float": info.get("floatShares"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "eps": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
            "roe_ttm": info.get("returnOnEquity"),
            "roa_ttm": info.get("returnOnAssets"),
            "profit_margin": info.get("profitMargins"),
        }

    def get_listing(self) -> pd.DataFrame:
        raise NotImplementedError("Yahoo Finance does not provide a listing endpoint. Use Alpha Vantage source for bootstrap.")
