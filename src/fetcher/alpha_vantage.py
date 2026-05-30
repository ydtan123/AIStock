import io
import time
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from fetcher.base import FetcherBase
from fetcher.rate_limiter import default_limiter
from utils import safe_date, safe_float, safe_int

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"
MAX_RETRIES = 3
_LISTING_CACHE = Path("data/cache/alpha_vantage_listing.parquet")


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
                "open": safe_float(vals.get("1. open")),
                "high": safe_float(vals.get("2. high")),
                "low": safe_float(vals.get("3. low")),
                "close": safe_float(vals.get("4. close")),
                "adj_close": safe_float(vals.get("5. adjusted close")),
                "volume": safe_int(vals.get("6. volume")),
                "dividend_amount": safe_float(vals.get("7. dividend amount")),
                "split_coefficient": safe_float(vals.get("8. split coefficient")),
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
            "shares_outstanding": safe_int(data.get("SharesOutstanding")),
            "shares_float": safe_int(data.get("SharesFloat")),
            "latest_quarter": safe_date(data.get("LatestQuarter")),
            "market_cap": safe_int(data.get("MarketCapitalization")),
            "ebitda": safe_int(data.get("EBITDA")),
            "pe_ratio": safe_float(data.get("PERatio")),
            "peg_ratio": safe_float(data.get("PEGRatio")),
            "book_value": safe_float(data.get("BookValue")),
            "dividend_per_share": safe_float(data.get("DividendPerShare")),
            "dividend_yield": safe_float(data.get("DividendYield")),
            "eps": safe_float(data.get("EPS")),
            "diluted_eps_ttm": safe_float(data.get("DilutedEPSTTM")),
            "revenue_per_share_ttm": safe_float(data.get("RevenuePerShareTTM")),
            "profit_margin": safe_float(data.get("ProfitMargin")),
            "operating_margin_ttm": safe_float(data.get("OperatingMarginTTM")),
            "roa_ttm": safe_float(data.get("ReturnOnAssetsTTM")),
            "roe_ttm": safe_float(data.get("ReturnOnEquityTTM")),
            "revenue_ttm": safe_int(data.get("RevenueTTM")),
            "gross_profit_ttm": safe_int(data.get("GrossProfitTTM")),
            "qtr_earnings_growth_yoy": safe_float(data.get("QuarterlyEarningsGrowthYOY")),
            "qtr_revenue_growth_yoy": safe_float(data.get("QuarterlyRevenueGrowthYOY")),
            "analyst_target_price": safe_float(data.get("AnalystTargetPrice")),
            "analyst_strong_buy": safe_int(data.get("AnalystRatingStrongBuy")),
            "analyst_buy": safe_int(data.get("AnalystRatingBuy")),
            "analyst_hold": safe_int(data.get("AnalystRatingHold")),
            "analyst_sell": safe_int(data.get("AnalystRatingSell")),
            "analyst_strong_sell": safe_int(data.get("AnalystRatingStrongSell")),
            "trailing_pe": safe_float(data.get("TrailingPE")),
            "forward_pe": safe_float(data.get("ForwardPE")),
            "price_to_sales_ttm": safe_float(data.get("PriceToSalesRatioTTM")),
            "price_to_book": safe_float(data.get("PriceToBookRatio")),
            "ev_to_revenue": safe_float(data.get("EVToRevenue")),
            "ev_to_ebitda": safe_float(data.get("EVToEBITDA")),
            "beta": safe_float(data.get("Beta")),
            "week_52_high": safe_float(data.get("52WeekHigh")),
            "week_52_low": safe_float(data.get("52WeekLow")),
            "ma_50_day": safe_float(data.get("50DayMovingAverage")),
            "ma_200_day": safe_float(data.get("200DayMovingAverage")),
            "pct_insiders": safe_float(data.get("PercentInsiders")),
            "pct_institutions": safe_float(data.get("PercentInstitutions")),
            "dividend_date": safe_date(data.get("DividendDate")),
            "ex_dividend_date": safe_date(data.get("ExDividendDate")),
        }

    def get_income_statement(self, symbol: str) -> pd.DataFrame:
        """Fetch quarterly income statements. Returns DataFrame indexed by fiscalDateEnding."""
        data = self._get({"function": "INCOME_STATEMENT", "symbol": symbol})
        reports = data.get("quarterlyReports", [])
        if not reports:
            return pd.DataFrame()
        rows = []
        for r in reports:
            rows.append({
                "fiscal_date": safe_date(r.get("fiscalDateEnding")),
                "total_revenue": safe_float(r.get("totalRevenue")),
                "gross_profit": safe_float(r.get("grossProfit")),
                "cost_of_revenue": safe_float(r.get("costOfRevenue")),
                "operating_income": safe_float(r.get("operatingIncome")),
                "operating_expenses": safe_float(r.get("operatingExpenses")),
                "net_income": safe_float(r.get("netIncome")),
                "ebitda": safe_float(r.get("ebitda")),
                "ebit": safe_float(r.get("ebit")),
                "interest_expense": safe_float(r.get("interestExpense")),
                "income_tax_expense": safe_float(r.get("incomeTaxExpense")),
                "depreciation_amortization": safe_float(r.get("depreciationAndAmortization")),
                "shares_outstanding_is": safe_float(r.get("commonStockSharesOutstanding")),
            })
        df = pd.DataFrame(rows).dropna(subset=["fiscal_date"])
        df.sort_values("fiscal_date", inplace=True)
        return df

    def get_balance_sheet(self, symbol: str) -> pd.DataFrame:
        """Fetch quarterly balance sheets. Returns DataFrame indexed by fiscalDateEnding."""
        data = self._get({"function": "BALANCE_SHEET", "symbol": symbol})
        reports = data.get("quarterlyReports", [])
        if not reports:
            return pd.DataFrame()
        rows = []
        for r in reports:
            rows.append({
                "fiscal_date": safe_date(r.get("fiscalDateEnding")),
                "total_assets": safe_float(r.get("totalAssets")),
                "total_current_assets": safe_float(r.get("totalCurrentAssets")),
                "cash_and_equivalents": safe_float(r.get("cashAndCashEquivalentsAtCarryingValue")),
                "inventory": safe_float(r.get("inventory")),
                "current_receivables": safe_float(r.get("currentNetReceivables")),
                "total_current_liabilities": safe_float(r.get("totalCurrentLiabilities")),
                "total_liabilities": safe_float(r.get("totalLiabilities")),
                "short_term_debt": safe_float(r.get("shortTermDebt")),
                "long_term_debt": safe_float(r.get("longTermDebt")),
                "total_equity": safe_float(r.get("totalShareholderEquity")),
                "retained_earnings": safe_float(r.get("retainedEarnings")),
                "goodwill": safe_float(r.get("goodwill")),
                "intangible_assets": safe_float(r.get("intangibleAssets")),
                "shares_outstanding_bs": safe_float(r.get("commonStockSharesOutstanding")),
            })
        df = pd.DataFrame(rows).dropna(subset=["fiscal_date"])
        df.sort_values("fiscal_date", inplace=True)
        return df

    def get_cash_flow(self, symbol: str) -> pd.DataFrame:
        """Fetch quarterly cash flow statements. Returns DataFrame indexed by fiscalDateEnding."""
        data = self._get({"function": "CASH_FLOW", "symbol": symbol})
        reports = data.get("quarterlyReports", [])
        if not reports:
            return pd.DataFrame()
        rows = []
        for r in reports:
            rows.append({
                "fiscal_date": safe_date(r.get("fiscalDateEnding")),
                "operating_cashflow": safe_float(r.get("operatingCashflow")),
                "capital_expenditures": safe_float(r.get("capitalExpenditures")),
                "dividend_payout": safe_float(
                    r.get("dividendPayoutCommonStock") or r.get("dividendPayout")
                ),
            })
        df = pd.DataFrame(rows).dropna(subset=["fiscal_date"])
        df.sort_values("fiscal_date", inplace=True)
        return df

    def get_earnings(self, symbol: str) -> pd.DataFrame:
        """Fetch quarterly earnings (EPS actuals vs estimates)."""
        data = self._get({"function": "EARNINGS", "symbol": symbol})
        reports = data.get("quarterlyEarnings", [])
        if not reports:
            return pd.DataFrame()
        rows = []
        for r in reports:
            surp_pct = r.get("surprisePercentage", "")
            try:
                surp_pct_val = (
                    float(str(surp_pct).replace("%", ""))
                    if surp_pct not in (None, "None", "")
                    else None
                )
            except (TypeError, ValueError):
                surp_pct_val = None
            rows.append({
                "fiscal_date": safe_date(r.get("fiscalDateEnding")),
                "reported_eps": safe_float(r.get("reportedEPS")),
                "estimated_eps": safe_float(r.get("estimatedEPS")),
                "eps_surprise": safe_float(r.get("surprise")),
                "eps_surprise_pct": surp_pct_val,
            })
        df = pd.DataFrame(rows).dropna(subset=["fiscal_date"])
        df.sort_values("fiscal_date", inplace=True)
        return df

    def _fetch_listing_from_api(self) -> pd.DataFrame:
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

    def get_listing(self) -> pd.DataFrame:
        ttl = timedelta(hours=6)
        if _LISTING_CACHE.exists():
            mtime = datetime.fromtimestamp(_LISTING_CACHE.stat().st_mtime, tz=timezone.utc)
            if datetime.now(timezone.utc) - mtime < ttl:
                return pd.read_parquet(_LISTING_CACHE)
        df = self._fetch_listing_from_api()
        _LISTING_CACHE.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_LISTING_CACHE, index=False)
        return df
