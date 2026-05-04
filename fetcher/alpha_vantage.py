import io
import time
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from fetcher.base import FetcherBase
from fetcher.rate_limiter import default_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"
MAX_RETRIES = 3


def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _safe_date(val) -> Optional[date]:
    if not val or val == "None":
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        return None


class AlphaVantageFetcher(FetcherBase):

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _get(self, params: dict, retries: int = MAX_RETRIES) -> dict | str:
        params["apikey"] = self._api_key
        # full history responses can be large; give them more time
        timeout = 60 if params.get("outputsize") == "full" else 30
        for attempt in range(retries):
            default_limiter.acquire()
            try:
                resp = requests.get(BASE_URL, params=params, timeout=timeout)
                resp.raise_for_status()
                if params.get("datatype") == "csv":
                    return resp.text
                data = resp.json()
                if "Note" in data or "Information" in data:
                    msg = data.get("Note") or data.get("Information") or ""
                    wait = 15 * (attempt + 1)  # 15s, 30s, 45s — stagger retries
                    logger.warning("AV rate limit (attempt %d), waiting %ds: %s", attempt + 1, wait, msg[:80])
                    time.sleep(wait)
                    continue
                return data
            except requests.Timeout:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                logger.warning("Timeout for %s (attempt %d), retry in %ds", params.get("symbol", "?"), attempt + 1, wait)
                time.sleep(wait)
            except requests.HTTPError as e:
                if e.response.status_code < 500:
                    raise
                wait = 2 ** attempt
                logger.warning("HTTP %s for %s, retry %d in %ds", e.response.status_code, params, attempt + 1, wait)
                time.sleep(wait)
        raise RuntimeError(f"Failed after {retries} retries: {params}")

    def get_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        # compact = last 100 trading days (~5 months); use it when start is recent
        # to avoid downloading the full 20-year history for incremental updates
        cutoff = date.today() - timedelta(days=90)
        outputsize = "compact" if start >= cutoff else "full"
        data = self._get({
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": outputsize,
        })
        ts = data.get("Time Series (Daily)", {})
        rows = []
        for date_str, vals in ts.items():
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if d < start or d > end:
                continue
            rows.append({
                "date": d,
                "open": _safe_float(vals.get("1. open")),
                "high": _safe_float(vals.get("2. high")),
                "low": _safe_float(vals.get("3. low")),
                "close": _safe_float(vals.get("4. close")),
                "adj_close": _safe_float(vals.get("5. adjusted close")),
                "volume": _safe_int(vals.get("6. volume")),
                "dividend_amount": _safe_float(vals.get("7. dividend amount")),
                "split_coefficient": _safe_float(vals.get("8. split coefficient")),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df.sort_values("date", inplace=True)
            df.reset_index(drop=True, inplace=True)
        return df

    def get_overview(self, symbol: str) -> dict:
        data = self._get({"function": "OVERVIEW", "symbol": symbol})
        if not data or "Symbol" not in data:
            return {}
        return {
            "symbol": data.get("Symbol"),
            "name": data.get("Name"),
            "asset_type": data.get("AssetType"),
            "exchange": data.get("Exchange"),
            "currency": data.get("Currency"),
            "country": data.get("Country"),
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),
            "description": data.get("Description"),
            "cik": data.get("CIK"),
            "official_site": data.get("OfficialSite"),
            "address": data.get("Address"),
            "fiscal_year_end": data.get("FiscalYearEnd"),
            "shares_outstanding": _safe_int(data.get("SharesOutstanding")),
            "shares_float": _safe_int(data.get("SharesFloat")),
            "latest_quarter": _safe_date(data.get("LatestQuarter")),
            "market_cap": _safe_int(data.get("MarketCapitalization")),
            "ebitda": _safe_int(data.get("EBITDA")),
            "pe_ratio": _safe_float(data.get("PERatio")),
            "peg_ratio": _safe_float(data.get("PEGRatio")),
            "book_value": _safe_float(data.get("BookValue")),
            "dividend_per_share": _safe_float(data.get("DividendPerShare")),
            "dividend_yield": _safe_float(data.get("DividendYield")),
            "eps": _safe_float(data.get("EPS")),
            "diluted_eps_ttm": _safe_float(data.get("DilutedEPSTTM")),
            "revenue_per_share_ttm": _safe_float(data.get("RevenuePerShareTTM")),
            "profit_margin": _safe_float(data.get("ProfitMargin")),
            "operating_margin_ttm": _safe_float(data.get("OperatingMarginTTM")),
            "roa_ttm": _safe_float(data.get("ReturnOnAssetsTTM")),
            "roe_ttm": _safe_float(data.get("ReturnOnEquityTTM")),
            "revenue_ttm": _safe_int(data.get("RevenueTTM")),
            "gross_profit_ttm": _safe_int(data.get("GrossProfitTTM")),
            "qtr_earnings_growth_yoy": _safe_float(data.get("QuarterlyEarningsGrowthYOY")),
            "qtr_revenue_growth_yoy": _safe_float(data.get("QuarterlyRevenueGrowthYOY")),
            "analyst_target_price": _safe_float(data.get("AnalystTargetPrice")),
            "analyst_strong_buy": _safe_int(data.get("AnalystRatingStrongBuy")),
            "analyst_buy": _safe_int(data.get("AnalystRatingBuy")),
            "analyst_hold": _safe_int(data.get("AnalystRatingHold")),
            "analyst_sell": _safe_int(data.get("AnalystRatingSell")),
            "analyst_strong_sell": _safe_int(data.get("AnalystRatingStrongSell")),
            "trailing_pe": _safe_float(data.get("TrailingPE")),
            "forward_pe": _safe_float(data.get("ForwardPE")),
            "price_to_sales_ttm": _safe_float(data.get("PriceToSalesRatioTTM")),
            "price_to_book": _safe_float(data.get("PriceToBookRatio")),
            "ev_to_revenue": _safe_float(data.get("EVToRevenue")),
            "ev_to_ebitda": _safe_float(data.get("EVToEBITDA")),
            "beta": _safe_float(data.get("Beta")),
            "week_52_high": _safe_float(data.get("52WeekHigh")),
            "week_52_low": _safe_float(data.get("52WeekLow")),
            "ma_50_day": _safe_float(data.get("50DayMovingAverage")),
            "ma_200_day": _safe_float(data.get("200DayMovingAverage")),
            "pct_insiders": _safe_float(data.get("PercentInsiders")),
            "pct_institutions": _safe_float(data.get("PercentInstitutions")),
            "dividend_date": _safe_date(data.get("DividendDate")),
            "ex_dividend_date": _safe_date(data.get("ExDividendDate")),
        }

    def get_listing(self) -> pd.DataFrame:
        text = self._get({"function": "LISTING_STATUS", "datatype": "csv"})
        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        df = df[df["status"] == "Active"]
        df = df[df["exchange"].isin(["NYSE", "NASDAQ"])]
        df = df[df["symbol"].str.len() <= 20]
        df = df[~df["symbol"].str.contains(":", na=False)]
        return df[["symbol", "name", "exchange", "assettype"]].rename(
            columns={"assettype": "asset_type"}
        )
