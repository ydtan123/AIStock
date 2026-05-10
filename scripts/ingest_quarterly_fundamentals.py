#!/usr/bin/env python3
"""Ingest quarterly fundamentals for S&P 500 from Alpha Vantage into AIStock MySQL.

Usage:
    python scripts/ingest_quarterly_fundamentals.py [--symbols AAPL,MSFT,...] [--start 2010-01-01]

- Fetches INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW, EARNINGS (4 AV calls/stock)
- Aligns fiscal dates to Mar/Jun/Sep/Dec 1st (MJSD convention)
- Computes ~30 financial ratios
- Looks up adj_close from daily_prices on each aligned date
- Computes y_return = log(next_adj_close / this_adj_close)
- Upserts into quarterly_fundamentals (skips rows already present)

Rate limit: 75 calls/min (shared with existing rate_limiter).
500 S&P 500 stocks × 4 calls = 2000 calls ≈ 27 minutes.
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Run from project root: python scripts/ingest_quarterly_fundamentals.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from fetcher.alpha_vantage import AlphaVantageFetcher
from models import Base, QuarterlyFundamentals, Stock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_qfund")


def _align_to_mjsd(d: date) -> date:
    """Map a fiscal quarter-end date to the nearest MJSD 1st (Mar/Jun/Sep/Dec)."""
    m = d.month
    y = d.year
    if m in (12, 1, 2):
        return date(y + 1 if m == 12 else y, 3, 1)
    if m in (3, 4, 5):
        return date(y, 6, 1)
    if m in (6, 7, 8):
        return date(y, 9, 1)
    return date(y, 12, 1)


def _nan_to_none(v):
    """Convert NaN/inf to None for MySQL compatibility."""
    if v is None:
        return None
    try:
        if np.isnan(v) or np.isinf(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    try:
        result = float(a) / float(b)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _build_ratios(is_row: dict, bs_row: dict, cf_row: dict, earn_row: dict,
                  adj_close: Optional[float]) -> dict:
    """Compute all pre-computed ratio columns from raw statement data."""
    rev = is_row.get("total_revenue")
    gp = is_row.get("gross_profit")
    oi = is_row.get("operating_income")
    ni = is_row.get("net_income")
    ebitda = is_row.get("ebitda")
    ebit = is_row.get("ebit")
    interest = is_row.get("interest_expense")

    ta = bs_row.get("total_assets")
    tca = bs_row.get("total_current_assets")
    cash = bs_row.get("cash_and_equivalents")
    inv = bs_row.get("inventory")
    rec = bs_row.get("current_receivables")
    tcl = bs_row.get("total_current_liabilities")
    tl = bs_row.get("total_liabilities")
    std = bs_row.get("short_term_debt")
    ltd = bs_row.get("long_term_debt")
    eq = bs_row.get("total_equity")
    shares = bs_row.get("shares_outstanding_bs") or is_row.get("shares_outstanding_is")

    ocf = cf_row.get("operating_cashflow")
    capex = cf_row.get("capital_expenditures")
    div_paid = cf_row.get("dividend_payout")

    eps = earn_row.get("reported_eps")
    if eps is None and ni is not None and shares:
        eps = _safe_div(ni, shares)

    bps = _safe_div(eq, shares)
    dps = _safe_div(div_paid, shares) if div_paid else None

    fcf = None
    if ocf is not None and capex is not None:
        fcf = ocf - abs(capex)

    mktcap = (adj_close * shares) if (adj_close and shares) else None
    ev = None
    if mktcap is not None and ltd is not None and cash is not None:
        ev = mktcap + ltd - cash

    # Debt total for leverage ratios
    total_debt = (std or 0) + (ltd or 0)

    ratios = {
        "EPS": eps,
        "BPS": bps,
        "DPS": dps,
        "gross_margin": _safe_div(gp, rev),
        "operating_margin": _safe_div(oi, rev),
        "net_income_ratio": _safe_div(ni, rev),
        "ebitda_margin": _safe_div(ebitda, rev),
        "cur_ratio": _safe_div(tca, tcl),
        "quick_ratio": _safe_div((tca - inv) if (tca and inv) else tca, tcl),
        "cash_ratio": _safe_div(cash, tcl),
        "debt_ratio": _safe_div(tl, ta),
        "debt_to_equity": _safe_div(tl, eq),
        "roe": _safe_div(ni, eq),
        "roa": _safe_div(ni, ta),
        "pe": _safe_div(adj_close, eps),
        "pb": _safe_div(adj_close, bps),
        "ps": _safe_div(adj_close, _safe_div(rev, shares)),
        "ev": ev,
        "ev_multiple": _safe_div(ev, ebitda),
        "asset_turnover": _safe_div(rev, ta),
        "inventory_turnover": _safe_div(is_row.get("cost_of_revenue"), inv),
        "acc_rec_turnover": _safe_div(rev, rec),
        "interest_coverage": _safe_div(ebit, interest),
        "debt_to_mktcap": _safe_div(total_debt, mktcap),
        "fcf_per_share": _safe_div(fcf, shares),
        "ocf_per_share": _safe_div(ocf, shares),
        "cash_per_share": _safe_div(cash, shares),
        "capex_per_share": _safe_div(capex, shares),
        "fcf_to_ocf": _safe_div(fcf, ocf),
        "ocf_ratio": _safe_div(ocf, ni),
        "revenue_per_share": _safe_div(rev, shares),
        "dividend_yield": _safe_div(dps, adj_close),
        "solvency_ratio": _safe_div(ni, tl),
        "price_to_fcf": _safe_div(adj_close, _safe_div(fcf, shares)),
        "price_to_ocf": _safe_div(adj_close, _safe_div(ocf, shares)),
        "market_cap": mktcap,
        "free_cash_flow": fcf,
        "shares_outstanding": shares,
    }

    # peg: pe / (earnings_growth * 100) — can't compute without prior EPS, set None
    ratios["peg"] = None
    ratios["payables_turnover"] = None
    ratios["debt_service_coverage"] = None

    return ratios


def _lookup_adj_close(symbol: str, target_date: date, engine,
                      window_days: int = 10) -> Optional[float]:
    """Find adj_close in daily_prices within window_days forward/backward of target_date."""
    lo = target_date - timedelta(days=window_days)
    hi = target_date + timedelta(days=window_days)
    q = text("""
        SELECT dp.adj_close, dp.close, dp.date
        FROM daily_prices dp
        JOIN stocks s ON s.id = dp.stock_id
        WHERE s.symbol = :sym AND dp.date BETWEEN :lo AND :hi
        ORDER BY ABS(DATEDIFF(dp.date, :target))
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(q, {"sym": symbol, "lo": lo, "hi": hi, "target": target_date}).fetchone()
    if row:
        return float(row.adj_close or row.close or 0) or None
    return None


def _fetch_stock_fundamentals(
    symbol: str,
    fetcher: AlphaVantageFetcher,
    start_date: date,
) -> pd.DataFrame:
    """Fetch and join all 4 AV endpoints for one symbol. Returns merged DataFrame."""
    try:
        is_df = fetcher.get_income_statement(symbol)
    except Exception as e:
        logger.warning(f"{symbol}: income_statement failed — {e}")
        is_df = pd.DataFrame()

    try:
        bs_df = fetcher.get_balance_sheet(symbol)
    except Exception as e:
        logger.warning(f"{symbol}: balance_sheet failed — {e}")
        bs_df = pd.DataFrame()

    try:
        cf_df = fetcher.get_cash_flow(symbol)
    except Exception as e:
        logger.warning(f"{symbol}: cash_flow failed — {e}")
        cf_df = pd.DataFrame()

    try:
        earn_df = fetcher.get_earnings(symbol)
    except Exception as e:
        logger.warning(f"{symbol}: earnings failed — {e}")
        earn_df = pd.DataFrame()

    if is_df.empty and bs_df.empty:
        return pd.DataFrame()

    # Merge on fiscal_date
    base = is_df if not is_df.empty else bs_df[["fiscal_date"]]
    for other in [bs_df, cf_df, earn_df]:
        if not other.empty:
            base = base.merge(other, on="fiscal_date", how="outer")

    base = base.sort_values("fiscal_date")
    base = base[base["fiscal_date"] >= start_date]
    return base


def _get_existing_dates(stock_id: int, session: Session) -> set:
    rows = (
        session.query(QuarterlyFundamentals.datadate)
        .filter(QuarterlyFundamentals.stock_id == stock_id)
        .all()
    )
    return {r.datadate for r in rows}


def _process_symbol(
    symbol: str,
    stock_id: int,
    sector: Optional[str],
    fetcher: AlphaVantageFetcher,
    engine,
    start_date: date,
    force: bool = False,
) -> int:
    """Fetch, compute, and upsert quarterly fundamentals for one symbol. Returns rows inserted."""
    raw = _fetch_stock_fundamentals(symbol, fetcher, start_date)
    if raw.empty:
        logger.warning(f"{symbol}: no data")
        return 0

    with Session(engine) as session:
        if force:
            session.query(QuarterlyFundamentals).filter(
                QuarterlyFundamentals.stock_id == stock_id
            ).delete()
            session.commit()
            existing = set()
        else:
            existing = _get_existing_dates(stock_id, session)

    rows_inserted = 0
    records: List[QuarterlyFundamentals] = []

    # Collect all (fiscal_date -> adj_close) first so we can compute y_return
    aligned_rows = []
    for _, row in raw.iterrows():
        fd = row.get("fiscal_date")
        if fd is None:
            continue
        datadate = _align_to_mjsd(fd)
        if datadate in existing:
            continue
        adj_close = _lookup_adj_close(symbol, datadate, engine)
        aligned_rows.append((fd, datadate, row.to_dict(), adj_close))

    # Sort by datadate for y_return computation
    aligned_rows.sort(key=lambda x: x[1])

    for i, (fd, datadate, row_dict, adj_close) in enumerate(aligned_rows):
        is_row = {k: row_dict.get(k) for k in [
            "total_revenue", "gross_profit", "cost_of_revenue", "operating_income",
            "operating_expenses", "net_income", "ebitda", "ebit", "interest_expense",
            "income_tax_expense", "depreciation_amortization", "shares_outstanding_is",
        ]}
        bs_row = {k: row_dict.get(k) for k in [
            "total_assets", "total_current_assets", "cash_and_equivalents", "inventory",
            "current_receivables", "total_current_liabilities", "total_liabilities",
            "short_term_debt", "long_term_debt", "total_equity", "retained_earnings",
            "shares_outstanding_bs",
        ]}
        cf_row = {k: row_dict.get(k) for k in [
            "operating_cashflow", "capital_expenditures", "dividend_payout",
        ]}
        earn_row = {k: row_dict.get(k) for k in [
            "reported_eps", "estimated_eps", "eps_surprise", "eps_surprise_pct",
        ]}

        ratios = _build_ratios(is_row, bs_row, cf_row, earn_row, adj_close)

        # y_return: log(next_adj_close / this_adj_close)
        y_return = None
        if i + 1 < len(aligned_rows) and adj_close:
            next_adj_close = aligned_rows[i + 1][3]
            if next_adj_close and adj_close > 0:
                try:
                    y_return = float(np.log(next_adj_close / adj_close))
                except Exception:
                    pass

        def _g(d, k):
            return _nan_to_none(d.get(k))

        record = QuarterlyFundamentals(
            stock_id=stock_id,
            symbol=symbol,
            sector=sector,
            datadate=datadate,
            fiscal_date=fd,
            adj_close_q=_nan_to_none(adj_close),
            # Income statement
            total_revenue=_g(is_row, "total_revenue"),
            gross_profit=_g(is_row, "gross_profit"),
            cost_of_revenue=_g(is_row, "cost_of_revenue"),
            operating_income=_g(is_row, "operating_income"),
            net_income=_g(is_row, "net_income"),
            ebitda=_g(is_row, "ebitda"),
            ebit=_g(is_row, "ebit"),
            interest_expense=_g(is_row, "interest_expense"),
            depreciation_amortization=_g(is_row, "depreciation_amortization"),
            # Balance sheet
            total_assets=_g(bs_row, "total_assets"),
            total_current_assets=_g(bs_row, "total_current_assets"),
            cash_and_equivalents=_g(bs_row, "cash_and_equivalents"),
            inventory=_g(bs_row, "inventory"),
            current_receivables=_g(bs_row, "current_receivables"),
            total_current_liabilities=_g(bs_row, "total_current_liabilities"),
            total_liabilities=_g(bs_row, "total_liabilities"),
            short_term_debt=_g(bs_row, "short_term_debt"),
            long_term_debt=_g(bs_row, "long_term_debt"),
            total_equity=_g(bs_row, "total_equity"),
            shares_outstanding=_nan_to_none(ratios.get("shares_outstanding")),
            retained_earnings=_g(bs_row, "retained_earnings"),
            # Cash flow
            operating_cashflow=_g(cf_row, "operating_cashflow"),
            capital_expenditures=_g(cf_row, "capital_expenditures"),
            dividend_payout=_g(cf_row, "dividend_payout"),
            free_cash_flow=_nan_to_none(ratios.get("free_cash_flow")),
            # Earnings
            reported_eps=_g(earn_row, "reported_eps"),
            estimated_eps=_g(earn_row, "estimated_eps"),
            eps_surprise=_g(earn_row, "eps_surprise"),
            eps_surprise_pct=_g(earn_row, "eps_surprise_pct"),
            # Ratios
            market_cap=_nan_to_none(ratios.get("market_cap")),
            EPS=_nan_to_none(ratios.get("EPS")),
            BPS=_nan_to_none(ratios.get("BPS")),
            DPS=_nan_to_none(ratios.get("DPS")),
            gross_margin=_nan_to_none(ratios.get("gross_margin")),
            operating_margin=_nan_to_none(ratios.get("operating_margin")),
            net_income_ratio=_nan_to_none(ratios.get("net_income_ratio")),
            ebitda_margin=_nan_to_none(ratios.get("ebitda_margin")),
            cur_ratio=_nan_to_none(ratios.get("cur_ratio")),
            quick_ratio=_nan_to_none(ratios.get("quick_ratio")),
            cash_ratio=_nan_to_none(ratios.get("cash_ratio")),
            debt_ratio=_nan_to_none(ratios.get("debt_ratio")),
            debt_to_equity=_nan_to_none(ratios.get("debt_to_equity")),
            roe=_nan_to_none(ratios.get("roe")),
            roa=_nan_to_none(ratios.get("roa")),
            pe=_nan_to_none(ratios.get("pe")),
            pb=_nan_to_none(ratios.get("pb")),
            ps=_nan_to_none(ratios.get("ps")),
            ev=_nan_to_none(ratios.get("ev")),
            ev_multiple=_nan_to_none(ratios.get("ev_multiple")),
            peg=_nan_to_none(ratios.get("peg")),
            asset_turnover=_nan_to_none(ratios.get("asset_turnover")),
            inventory_turnover=_nan_to_none(ratios.get("inventory_turnover")),
            acc_rec_turnover=_nan_to_none(ratios.get("acc_rec_turnover")),
            payables_turnover=_nan_to_none(ratios.get("payables_turnover")),
            interest_coverage=_nan_to_none(ratios.get("interest_coverage")),
            debt_service_coverage=_nan_to_none(ratios.get("debt_service_coverage")),
            debt_to_mktcap=_nan_to_none(ratios.get("debt_to_mktcap")),
            fcf_per_share=_nan_to_none(ratios.get("fcf_per_share")),
            ocf_per_share=_nan_to_none(ratios.get("ocf_per_share")),
            cash_per_share=_nan_to_none(ratios.get("cash_per_share")),
            capex_per_share=_nan_to_none(ratios.get("capex_per_share")),
            fcf_to_ocf=_nan_to_none(ratios.get("fcf_to_ocf")),
            ocf_ratio=_nan_to_none(ratios.get("ocf_ratio")),
            revenue_per_share=_nan_to_none(ratios.get("revenue_per_share")),
            dividend_yield=_nan_to_none(ratios.get("dividend_yield")),
            solvency_ratio=_nan_to_none(ratios.get("solvency_ratio")),
            price_to_fcf=_nan_to_none(ratios.get("price_to_fcf")),
            price_to_ocf=_nan_to_none(ratios.get("price_to_ocf")),
            y_return=_nan_to_none(y_return),
            ingested_at=datetime.utcnow(),
        )
        records.append(record)

    if records:
        with Session(engine) as session:
            session.add_all(records)
            session.commit()
        rows_inserted = len(records)

    return rows_inserted


def _get_sp500_symbols(engine) -> List[tuple]:
    """Return list of (symbol, stock_id, sector) from AIStock DB (active stocks)."""
    q = text("SELECT symbol, id, sector FROM stocks WHERE is_active = 1 ORDER BY symbol")
    with engine.connect() as conn:
        rows = conn.execute(q).fetchall()
    return [(r.symbol, r.id, r.sector) for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Ingest quarterly fundamentals into AIStock DB")
    parser.add_argument("--symbols", help="Comma-separated symbols (default: all active stocks)")
    parser.add_argument("--start", default="2010-01-01", help="Earliest fiscal date to include")
    parser.add_argument("--force", action="store_true", help="Re-ingest even if data exists")
    args = parser.parse_args()

    cfg = load_config()
    db_url = cfg["database"]["url"]
    api_key = cfg["alpha_vantage"]["api_key"]

    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)

    # Ensure table exists
    Base.metadata.create_all(engine, tables=[QuarterlyFundamentals.__table__])

    fetcher = AlphaVantageFetcher(api_key=api_key)
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()

    if args.symbols:
        requested = [s.strip().upper() for s in args.symbols.split(",")]
        all_stocks = _get_sp500_symbols(engine)
        symbol_map = {sym: (sid, sec) for sym, sid, sec in all_stocks}
        stocks = []
        for sym in requested:
            if sym in symbol_map:
                sid, sec = symbol_map[sym]
                stocks.append((sym, sid, sec))
            else:
                logger.warning(f"{sym}: not in AIStock DB, skipping")
    else:
        stocks = _get_sp500_symbols(engine)

    total = len(stocks)
    logger.info(f"Processing {total} symbols from {args.start}")

    total_inserted = 0
    for i, (symbol, stock_id, sector) in enumerate(stocks, 1):
        logger.info(f"[{i}/{total}] {symbol}")
        try:
            n = _process_symbol(symbol, stock_id, sector, fetcher, engine, start_date, args.force)
            total_inserted += n
            logger.info(f"  → {n} rows inserted")
        except Exception as e:
            logger.error(f"{symbol}: failed — {e}")

    logger.info(f"Done. Total rows inserted: {total_inserted}")


if __name__ == "__main__":
    main()
