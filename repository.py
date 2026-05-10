from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text

from database import get_session
from models import DailyPrice, Stock, StockIndicator, StockSnapshot, TechnicalIndicator


@dataclass
class ScreenCriteria:
    min_market_cap: int = 0
    min_pe: float = 0.0
    max_pe: float = 100.0
    min_roe: Optional[float] = None
    min_rsi: Optional[float] = None
    max_rsi: Optional[float] = None
    max_beta: Optional[float] = None
    min_div_yield: Optional[float] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None


@dataclass
class StockFilters:
    exchange: Optional[str] = None
    sector: Optional[str] = None
    min_market_cap: float = 0.0
    max_pe: float = 999.0
    min_roe: float = -200.0
    max_beta: float = 10.0
    status: str = "All"


class StockRepository:

    def _get_session(self):
        """Override in test subclasses to inject a test session."""
        return get_session()

    # -- lookup ----------------------------------------------------------------

    def find_stock(self, symbol: str) -> Optional[Stock]:
        session = self._get_session()
        try:
            return session.query(Stock).filter_by(symbol=symbol.upper()).first()
        finally:
            session.close()

    def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
        session = self._get_session()
        try:
            rows = (
                session.query(DailyPrice)
                .filter(DailyPrice.stock_id == stock_id,
                        DailyPrice.date >= start,
                        DailyPrice.date <= end)
                .order_by(DailyPrice.date)
                .all()
            )
            return pd.DataFrame([{
                "date": r.date, "open": r.open, "high": r.high, "low": r.low,
                "close": r.close, "adj_close": r.adj_close, "volume": r.volume,
            } for r in rows])
        finally:
            session.close()

    def get_indicator(self, stock_id: int) -> Optional[StockIndicator]:
        session = self._get_session()
        try:
            return session.query(StockIndicator).filter_by(stock_id=stock_id).first()
        finally:
            session.close()

    def get_tech_indicators(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
        session = self._get_session()
        try:
            rows = (
                session.query(TechnicalIndicator)
                .filter(TechnicalIndicator.stock_id == stock_id,
                        TechnicalIndicator.date >= start,
                        TechnicalIndicator.date <= end)
                .order_by(TechnicalIndicator.date)
                .all()
            )
            records = []
            for r in rows:
                d = {"date": r.date}
                if r.indicators:
                    d.update(r.indicators)
                records.append(d)
            return pd.DataFrame(records)
        finally:
            session.close()

    # -- screener --------------------------------------------------------------

    def screen_stocks(self, criteria: ScreenCriteria) -> pd.DataFrame:
        session = self._get_session()
        try:
            q = """
            SELECT s.symbol, s.name, ss.market_cap, ss.pe_ratio, ss.roe_ttm,
                   ss.rsi_14, ss.beta, ss.dividend_yield, ss.sector, ss.exchange
            FROM stock_snapshots ss
            JOIN stocks s ON s.id = ss.stock_id
            WHERE ss.market_cap >= :min_mc
              AND (ss.pe_ratio IS NULL OR (ss.pe_ratio >= :min_pe AND ss.pe_ratio <= :max_pe))
              AND (ss.roe_ttm IS NULL OR ss.roe_ttm >= :min_roe)
              AND (ss.rsi_14 IS NULL OR (ss.rsi_14 >= :min_rsi AND ss.rsi_14 <= :max_rsi))
              AND (ss.beta IS NULL OR ss.beta <= :max_beta)
              AND (ss.dividend_yield IS NULL OR ss.dividend_yield >= :min_div)
            """
            params = {
                "min_mc": criteria.min_market_cap,
                "min_pe": criteria.min_pe,
                "max_pe": criteria.max_pe,
                "min_roe": (criteria.min_roe / 100) if criteria.min_roe is not None else -999,
                "min_rsi": criteria.min_rsi if criteria.min_rsi is not None else -999,
                "max_rsi": criteria.max_rsi if criteria.max_rsi is not None else 999,
                "max_beta": criteria.max_beta if criteria.max_beta is not None else 999,
                "min_div": (criteria.min_div_yield / 100) if criteria.min_div_yield is not None else -999,
            }
            if criteria.sector:
                q += " AND ss.sector = :sector"
                params["sector"] = criteria.sector
            if criteria.exchange:
                q += " AND ss.exchange = :exchange"
                params["exchange"] = criteria.exchange
            q += " ORDER BY ss.market_cap DESC LIMIT 500"

            rows = session.execute(text(q), params).fetchall()
            return pd.DataFrame(rows, columns=[
                "Symbol", "Name", "Market Cap", "PE", "ROE %", "RSI",
                "Beta", "Div Yield %", "Sector", "Exchange",
            ])
        finally:
            session.close()

    # -- manager ---------------------------------------------------------------

    def list_stocks(self, filters: StockFilters) -> pd.DataFrame:
        session = self._get_session()
        try:
            q = """
            SELECT s.id, s.symbol, s.name, si.market_cap, s.sector, si.pe_ratio,
                   si.roe_ttm, si.beta, s.is_active, s.exchange
            FROM stocks s
            LEFT JOIN stock_indicators si ON si.stock_id = s.id
            WHERE 1=1
            """
            params = {}
            if filters.exchange:
                q += " AND s.exchange = :exchange"
                params["exchange"] = filters.exchange
            if filters.sector:
                q += " AND s.sector = :sector"
                params["sector"] = filters.sector
            if filters.min_market_cap > 0:
                q += " AND si.market_cap >= :min_mc"
                params["min_mc"] = int(filters.min_market_cap * 1_000_000_000)
            if filters.max_pe < 999:
                q += " AND si.pe_ratio <= :max_pe"
                params["max_pe"] = filters.max_pe
            if filters.min_roe > -200:
                q += " AND si.roe_ttm >= :min_roe"
                params["min_roe"] = filters.min_roe / 100
            if filters.max_beta < 10:
                q += " AND si.beta <= :max_beta"
                params["max_beta"] = filters.max_beta
            if filters.status == "Active":
                q += " AND s.is_active = 1"
            elif filters.status == "Inactive":
                q += " AND s.is_active = 0"
            q += " ORDER BY si.market_cap DESC LIMIT 500"

            rows = session.execute(text(q), params).fetchall()
            return pd.DataFrame(rows, columns=[
                "id", "Symbol", "Name", "Mkt Cap", "Sector", "PE", "ROE %",
                "Beta", "Active", "Exchange",
            ])
        finally:
            session.close()

    def count_summary(self) -> dict:
        session = self._get_session()
        try:
            total = session.query(Stock).count()
            active = session.query(Stock).filter_by(is_active=True).count()
            return {"total": total, "active": active, "inactive": total - active}
        finally:
            session.close()

    def bulk_set_active(self, ids: list[int], active: bool):
        if not ids:
            return
        session = self._get_session()
        try:
            now = datetime.utcnow() if active else None
            session.execute(
                text("UPDATE stocks SET is_active=:a, activated_at=:t WHERE id IN :ids"),
                {"a": active, "t": now, "ids": tuple(ids)},
            )
            session.commit()
        finally:
            session.close()

    def get_sectors(self, table: str = "stock_snapshots") -> list[str]:
        session = self._get_session()
        try:
            q = (
                "SELECT DISTINCT sector FROM stock_snapshots WHERE sector IS NOT NULL ORDER BY sector"
                if table == "stock_snapshots"
                else "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL ORDER BY sector"
            )
            return [r[0] for r in session.execute(text(q)).fetchall()]
        finally:
            session.close()

    def get_predictions(self, min_prob: float = 0.0, limit: int = 200) -> pd.DataFrame:
        session = self._get_session()
        try:
            q = """
            SELECT s.symbol, s.name, sp.probability, sp.input_end_date,
                   ss.close, ss.market_cap, ss.sector
            FROM stock_predictions sp
            JOIN stocks s ON s.id = sp.stock_id
            LEFT JOIN stock_snapshots ss ON ss.stock_id = sp.stock_id
            WHERE sp.probability >= :min_p
            ORDER BY sp.probability DESC
            LIMIT :lim
            """
            rows = session.execute(text(q), {"min_p": min_prob, "lim": limit}).fetchall()
            return pd.DataFrame(rows, columns=[
                "Symbol", "Name", "Probability", "Input End", "Close",
                "Market Cap", "Sector",
            ])
        finally:
            session.close()

    def get_all_predictions(self, sector: Optional[str] = None, search: str = "") -> pd.DataFrame:
        session = self._get_session()
        try:
            where = ""
            params: dict = {}
            if sector:
                where += " AND ss.sector = :sector"
                params["sector"] = sector
            if search:
                where += " AND (s.symbol LIKE :search OR s.name LIKE :search)"
                params["search"] = f"%{search}%"
            q = f"""
            SELECT s.symbol, s.name,
                   MAX(CASE WHEN sp.label_method = 'max_high_5pct' THEN sp.probability END) AS p_high,
                   MAX(CASE WHEN sp.label_method = 'beats_spy' THEN sp.probability END) AS p_spy,
                   MAX(sp.input_end_date) AS input_end_date,
                   MAX(sp.predicted_at) AS predicted_at,
                   ss.close, ss.market_cap, ss.sector, ss.rsi_14
            FROM stock_predictions sp
            JOIN stocks s ON s.id = sp.stock_id
            LEFT JOIN stock_snapshots ss ON ss.stock_id = sp.stock_id
            WHERE sp.probability IS NOT NULL
            {where}
            GROUP BY s.id, s.symbol, s.name, ss.close, ss.market_cap, ss.sector, ss.rsi_14
            ORDER BY COALESCE(
                MAX(CASE WHEN sp.label_method = 'max_high_5pct' THEN sp.probability END),
                MAX(CASE WHEN sp.label_method = 'beats_spy' THEN sp.probability END)
            ) DESC
            """
            rows = session.execute(text(q), params).fetchall()
            return pd.DataFrame(rows, columns=[
                "Symbol", "Name", "P(5% high)", "P(beats SPY)", "Input End", "Predicted At",
                "Close", "Market Cap", "Sector", "RSI",
            ])
        finally:
            session.close()
