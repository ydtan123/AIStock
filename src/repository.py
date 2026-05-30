from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text

from database import get_session
from models import DailyPrice, ScheduledJobRun, SelectedStock, Stock, StockIndicator, StockSnapshot, TechnicalIndicator


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

    def _with_session(self, fn):
        """Run *fn(session)* inside a managed session lifecycle."""
        session = self._get_session()
        try:
            return fn(session)
        finally:
            session.close()

    # -- lookup ----------------------------------------------------------------

    def find_stock(self, symbol: str) -> Optional[Stock]:
        return self._with_session(
            lambda s: s.query(Stock).filter_by(symbol=symbol.upper()).first()
        )

    def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
        """Look up multiple stocks in a single query. Returns {SYMBOL: Stock}."""
        def _query(s):
            rows = s.query(Stock).filter(
                Stock.symbol.in_([str(x).upper() for x in symbols])
            ).all()
            return {r.symbol: r for r in rows}
        return self._with_session(_query)

    def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
        return self._with_session(lambda s: pd.DataFrame([{
            "date": r.date, "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "adj_close": r.adj_close, "volume": r.volume,
        } for r in (
            s.query(DailyPrice)
            .filter(DailyPrice.stock_id == stock_id,
                    DailyPrice.date >= start,
                    DailyPrice.date <= end)
            .order_by(DailyPrice.date)
            .all()
        )]))

    def get_indicator(self, stock_id: int) -> Optional[StockIndicator]:
        return self._with_session(
            lambda s: s.query(StockIndicator).filter_by(stock_id=stock_id).first()
        )

    def get_snapshot(self, stock_id: int) -> Optional[StockSnapshot]:
        return self._with_session(
            lambda s: s.query(StockSnapshot).filter_by(stock_id=stock_id).first()
        )

    def get_tech_indicators(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
        def _query(s):
            rows = (
                s.query(TechnicalIndicator)
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
        return self._with_session(_query)

    # -- screener --------------------------------------------------------------

    def screen_stocks(self, criteria: ScreenCriteria) -> pd.DataFrame:
        def _query(s):
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
            rows = s.execute(text(q), params).fetchall()
            return pd.DataFrame(rows, columns=[
                "Symbol", "Name", "Market Cap", "PE", "ROE %", "RSI",
                "Beta", "Div Yield %", "Sector", "Exchange",
            ])
        return self._with_session(_query)

    # -- manager ---------------------------------------------------------------

    def list_stocks(self, filters: StockFilters) -> pd.DataFrame:
        def _query(s):
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
            rows = s.execute(text(q), params).fetchall()
            return pd.DataFrame(rows, columns=[
                "id", "Symbol", "Name", "Mkt Cap", "Sector", "PE", "ROE %",
                "Beta", "Active", "Exchange",
            ])
        return self._with_session(_query)

    def count_summary(self) -> dict:
        def _query(s):
            total = s.query(Stock).count()
            active = s.query(Stock).filter_by(is_active=True).count()
            return {"total": total, "active": active, "inactive": total - active}
        return self._with_session(_query)

    def bulk_set_active(self, ids: list[int], active: bool):
        if not ids:
            return
        def _query(s):
            now = datetime.utcnow() if active else None
            s.execute(
                text("UPDATE stocks SET is_active=:a, activated_at=:t WHERE id IN :ids"),
                {"a": active, "t": now, "ids": tuple(ids)},
            )
            s.commit()
        self._with_session(_query)

    def get_sectors(self, table: str = "stock_snapshots") -> list[str]:
        def _query(s):
            q = (
                "SELECT DISTINCT sector FROM stock_snapshots WHERE sector IS NOT NULL ORDER BY sector"
                if table == "stock_snapshots"
                else "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL ORDER BY sector"
            )
            return [r[0] for r in s.execute(text(q)).fetchall()]
        return self._with_session(_query)

    def save_selected_stocks(self, records: list[dict], pipeline_run_id: int | None = None) -> int:
        def _query(s):
            # Only delete rows for this pipeline run (or all if no run_id).
            if pipeline_run_id is not None:
                s.query(SelectedStock).filter_by(pipeline_run_id=pipeline_run_id).delete()
            else:
                s.query(SelectedStock).delete()
            run_at = datetime.now()
            rows = []
            for rec in records:
                ml_score = float(rec.get("ml_score", 0))
                rows.append(SelectedStock(
                    ticker=rec["ticker"],
                    model_name=rec.get("model_name", ""),
                    ml_score=ml_score,
                    bucket=rec.get("bucket"),
                    weight=float(rec["weight"]) if rec.get("weight") is not None else None,
                    date_selected=rec.get("date_selected", date.today()),
                    model_file=rec.get("model_file"),
                    pipeline_run_at=run_at,
                    predicted_return=ml_score,
                    predicted_at=run_at,
                    pipeline_run_id=pipeline_run_id,
                ))
            s.add_all(rows)
            s.commit()
            return len(rows)
        return self._with_session(_query)

    def save_predict_only_results(self, predictions: list[dict]) -> int:
        """Persist FinRL predict-only results to selected_stocks table."""
        def _query(s):
            run_at = datetime.now()
            rows = []
            for pred in predictions:
                rows.append(SelectedStock(
                    ticker=pred["ticker"],
                    model_name=pred.get("model_name", ""),
                    ml_score=float(pred.get("ml_score", 0)),
                    bucket=pred.get("bucket"),
                    weight=float(pred["weight"]) if pred.get("weight") is not None else None,
                    date_selected=pred.get("date_selected", date.today()),
                    model_file=pred.get("model_file"),
                    pipeline_run_at=run_at,
                    predicted_return=float(pred.get("predicted_return", 0)),
                    predicted_at=run_at,
                ))
            s.add_all(rows)
            s.commit()
            return len(rows)
        return self._with_session(_query)

    def get_latest_selected_stocks(self) -> list[dict]:
        def _query(s):
            latest_run = (
                s.query(SelectedStock.pipeline_run_at)
                .order_by(SelectedStock.pipeline_run_at.desc())
                .limit(1)
                .scalar()
            )
            if not latest_run:
                return []
            rows = (
                s.query(SelectedStock)
                .filter(SelectedStock.pipeline_run_at == latest_run)
                .all()
            )
            return [
                {
                    "ticker": r.ticker,
                    "model_name": r.model_name,
                    "ml_score": r.ml_score,
                    "bucket": r.bucket,
                    "weight": r.weight,
                    "date_selected": r.date_selected,
                    "model_file": r.model_file,
                    "pipeline_run_at": r.pipeline_run_at,
                }
                for r in rows
            ]
        return self._with_session(_query)

    def get_job_runs(self, limit: int = 100) -> pd.DataFrame:
        def _query(s):
            rows = (
                s.query(ScheduledJobRun)
                .order_by(ScheduledJobRun.started_at.desc())
                .limit(limit)
                .all()
            )
            recs = [{
                "id": r.id,
                "Job Name": r.job_name,
                "Start Time": r.started_at,
                "End Time": r.finished_at,
                "Stocks Updated": r.stocks_updated,
                "Status": r.status,
                "Error": r.error_message,
            } for r in rows]
            return pd.DataFrame(recs, columns=[
                "id", "Job Name", "Start Time", "End Time", "Stocks Updated", "Status", "Error",
            ])
        return self._with_session(_query)
