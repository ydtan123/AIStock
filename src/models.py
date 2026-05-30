from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey,
    Index, Integer, SmallInteger, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.mysql import DECIMAL, JSON, MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    asset_type: Mapped[Optional[str]] = mapped_column(String(50))
    exchange: Mapped[Optional[str]] = mapped_column(String(20))
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    country: Mapped[Optional[str]] = mapped_column(String(50))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    cik: Mapped[Optional[str]] = mapped_column(String(20))
    official_site: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    fiscal_year_end: Mapped[Optional[str]] = mapped_column(String(20))
    shares_outstanding: Mapped[Optional[int]] = mapped_column(BigInteger)
    shares_float: Mapped[Optional[int]] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_price_fetch: Mapped[Optional[datetime]] = mapped_column(DateTime)

    daily_prices: Mapped[list["DailyPrice"]] = relationship(back_populates="stock")
    indicator: Mapped[Optional["StockIndicator"]] = relationship(back_populates="stock", uselist=False)
    technical_indicators: Mapped[list["TechnicalIndicator"]] = relationship(back_populates="stock")
    snapshot: Mapped[Optional["StockSnapshot"]] = relationship(back_populates="stock", uselist=False)
    __table_args__ = (Index("ix_stocks_is_active", "is_active"),)


class DailyPrice(Base):
    __tablename__ = "daily_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    adj_close: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    dividend_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    split_coefficient: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))

    stock: Mapped["Stock"] = relationship(back_populates="daily_prices")

    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_daily_prices_stock_date"),
        Index("ix_daily_prices_stock_date", "stock_id", "date"),
    )


class StockIndicator(Base):
    __tablename__ = "stock_indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), unique=True, nullable=False)
    latest_quarter: Mapped[Optional[datetime]] = mapped_column(Date)
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger)
    ebitda: Mapped[Optional[int]] = mapped_column(BigInteger)
    pe_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    peg_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    book_value: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    dividend_per_share: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    dividend_yield: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6))
    eps: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    diluted_eps_ttm: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    revenue_per_share_ttm: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    profit_margin: Mapped[Optional[float]] = mapped_column(Float)
    operating_margin_ttm: Mapped[Optional[float]] = mapped_column(Float)
    roa_ttm: Mapped[Optional[float]] = mapped_column(Float)
    roe_ttm: Mapped[Optional[float]] = mapped_column(Float)
    revenue_ttm: Mapped[Optional[int]] = mapped_column(BigInteger)
    gross_profit_ttm: Mapped[Optional[int]] = mapped_column(BigInteger)
    qtr_earnings_growth_yoy: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6))
    qtr_revenue_growth_yoy: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6))
    analyst_target_price: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    analyst_strong_buy: Mapped[Optional[int]] = mapped_column(SmallInteger)
    analyst_buy: Mapped[Optional[int]] = mapped_column(SmallInteger)
    analyst_hold: Mapped[Optional[int]] = mapped_column(SmallInteger)
    analyst_sell: Mapped[Optional[int]] = mapped_column(SmallInteger)
    analyst_strong_sell: Mapped[Optional[int]] = mapped_column(SmallInteger)
    trailing_pe: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    forward_pe: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    price_to_sales_ttm: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    price_to_book: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    ev_to_revenue: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    ev_to_ebitda: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    beta: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 4))
    week_52_high: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    week_52_low: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    ma_50_day: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    ma_200_day: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    pct_insiders: Mapped[Optional[float]] = mapped_column(Float)
    pct_institutions: Mapped[Optional[float]] = mapped_column(Float)
    dividend_date: Mapped[Optional[datetime]] = mapped_column(Date)
    ex_dividend_date: Mapped[Optional[datetime]] = mapped_column(Date)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime)

    stock: Mapped["Stock"] = relationship(back_populates="indicator")


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    indicators: Mapped[Optional[dict]] = mapped_column(JSON)
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    stock: Mapped["Stock"] = relationship(back_populates="technical_indicators")

    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_tech_ind_stock_date"),
        Index("ix_tech_ind_stock_date", "stock_id", "date"),
    )


class StockSnapshot(Base):
    __tablename__ = "stock_snapshots"

    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), primary_key=True)
    latest_date: Mapped[Optional[datetime]] = mapped_column(Date)
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    pe_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4))
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger)
    roe_ttm: Mapped[Optional[float]] = mapped_column(Float)
    dividend_yield: Mapped[Optional[float]] = mapped_column(Float)
    beta: Mapped[Optional[float]] = mapped_column(Float)
    rsi_14: Mapped[Optional[float]] = mapped_column(Float)
    macd: Mapped[Optional[float]] = mapped_column(Float)
    sma_20: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    sma_50: Mapped[Optional[float]] = mapped_column(DECIMAL(14, 4))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    exchange: Mapped[Optional[str]] = mapped_column(String(20))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    stock: Mapped["Stock"] = relationship(back_populates="snapshot")

    __table_args__ = (
        Index("ix_snapshot_market_cap", "market_cap"),
        Index("ix_snapshot_pe_ratio", "pe_ratio"),
        Index("ix_snapshot_roe_ttm", "roe_ttm"),
        Index("ix_snapshot_rsi_14", "rsi_14"),
        Index("ix_snapshot_beta", "beta"),
        Index("ix_snapshot_sector", "sector"),
        Index("ix_snapshot_exchange", "exchange"),
    )


class ScheduledJobRun(Base):
    __tablename__ = "job_status"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    stocks_updated: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    error_message: Mapped[Optional[str]] = mapped_column(Text)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    symbols_processed: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="running")


class QuarterlyFundamentals(Base):
    """Quarterly fundamental data for S&P 500 stocks, sourced from Alpha Vantage.

    datadate is aligned to Mar/Jun/Sep/Dec 1st (MJSD convention).
    y_return is the forward log return to the next datadate.
    """

    __tablename__ = "quarterly_fundamentals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    datadate: Mapped[datetime] = mapped_column(Date, nullable=False)
    fiscal_date: Mapped[Optional[datetime]] = mapped_column(Date)

    # Price on datadate
    adj_close_q: Mapped[Optional[float]] = mapped_column(Float)
    market_cap: Mapped[Optional[float]] = mapped_column(Float)

    # Income statement
    total_revenue: Mapped[Optional[float]] = mapped_column(Float)
    gross_profit: Mapped[Optional[float]] = mapped_column(Float)
    cost_of_revenue: Mapped[Optional[float]] = mapped_column(Float)
    operating_income: Mapped[Optional[float]] = mapped_column(Float)
    net_income: Mapped[Optional[float]] = mapped_column(Float)
    ebitda: Mapped[Optional[float]] = mapped_column(Float)
    ebit: Mapped[Optional[float]] = mapped_column(Float)
    interest_expense: Mapped[Optional[float]] = mapped_column(Float)
    depreciation_amortization: Mapped[Optional[float]] = mapped_column(Float)

    # Balance sheet
    total_assets: Mapped[Optional[float]] = mapped_column(Float)
    total_current_assets: Mapped[Optional[float]] = mapped_column(Float)
    cash_and_equivalents: Mapped[Optional[float]] = mapped_column(Float)
    inventory: Mapped[Optional[float]] = mapped_column(Float)
    current_receivables: Mapped[Optional[float]] = mapped_column(Float)
    total_current_liabilities: Mapped[Optional[float]] = mapped_column(Float)
    total_liabilities: Mapped[Optional[float]] = mapped_column(Float)
    short_term_debt: Mapped[Optional[float]] = mapped_column(Float)
    long_term_debt: Mapped[Optional[float]] = mapped_column(Float)
    total_equity: Mapped[Optional[float]] = mapped_column(Float)
    shares_outstanding: Mapped[Optional[float]] = mapped_column(Float)
    retained_earnings: Mapped[Optional[float]] = mapped_column(Float)

    # Cash flow
    operating_cashflow: Mapped[Optional[float]] = mapped_column(Float)
    capital_expenditures: Mapped[Optional[float]] = mapped_column(Float)
    dividend_payout: Mapped[Optional[float]] = mapped_column(Float)
    free_cash_flow: Mapped[Optional[float]] = mapped_column(Float)

    # Earnings (from EARNINGS endpoint)
    reported_eps: Mapped[Optional[float]] = mapped_column(Float)
    estimated_eps: Mapped[Optional[float]] = mapped_column(Float)
    eps_surprise: Mapped[Optional[float]] = mapped_column(Float)
    eps_surprise_pct: Mapped[Optional[float]] = mapped_column(Float)

    # Pre-computed ratios — feature-ready
    EPS: Mapped[Optional[float]] = mapped_column(Float)
    BPS: Mapped[Optional[float]] = mapped_column(Float)
    DPS: Mapped[Optional[float]] = mapped_column(Float)
    gross_margin: Mapped[Optional[float]] = mapped_column(Float)
    operating_margin: Mapped[Optional[float]] = mapped_column(Float)
    net_income_ratio: Mapped[Optional[float]] = mapped_column(Float)
    ebitda_margin: Mapped[Optional[float]] = mapped_column(Float)
    cur_ratio: Mapped[Optional[float]] = mapped_column(Float)
    quick_ratio: Mapped[Optional[float]] = mapped_column(Float)
    cash_ratio: Mapped[Optional[float]] = mapped_column(Float)
    debt_ratio: Mapped[Optional[float]] = mapped_column(Float)
    debt_to_equity: Mapped[Optional[float]] = mapped_column(Float)
    roe: Mapped[Optional[float]] = mapped_column(Float)
    roa: Mapped[Optional[float]] = mapped_column(Float)
    pe: Mapped[Optional[float]] = mapped_column(Float)
    pb: Mapped[Optional[float]] = mapped_column(Float)
    ps: Mapped[Optional[float]] = mapped_column(Float)
    ev: Mapped[Optional[float]] = mapped_column(Float)
    ev_multiple: Mapped[Optional[float]] = mapped_column(Float)
    peg: Mapped[Optional[float]] = mapped_column(Float)
    asset_turnover: Mapped[Optional[float]] = mapped_column(Float)
    inventory_turnover: Mapped[Optional[float]] = mapped_column(Float)
    acc_rec_turnover: Mapped[Optional[float]] = mapped_column(Float)
    payables_turnover: Mapped[Optional[float]] = mapped_column(Float)
    interest_coverage: Mapped[Optional[float]] = mapped_column(Float)
    debt_service_coverage: Mapped[Optional[float]] = mapped_column(Float)
    debt_to_mktcap: Mapped[Optional[float]] = mapped_column(Float)
    fcf_per_share: Mapped[Optional[float]] = mapped_column(Float)
    ocf_per_share: Mapped[Optional[float]] = mapped_column(Float)
    cash_per_share: Mapped[Optional[float]] = mapped_column(Float)
    capex_per_share: Mapped[Optional[float]] = mapped_column(Float)
    fcf_to_ocf: Mapped[Optional[float]] = mapped_column(Float)
    ocf_ratio: Mapped[Optional[float]] = mapped_column(Float)
    revenue_per_share: Mapped[Optional[float]] = mapped_column(Float)
    dividend_yield: Mapped[Optional[float]] = mapped_column(Float)
    solvency_ratio: Mapped[Optional[float]] = mapped_column(Float)
    price_to_fcf: Mapped[Optional[float]] = mapped_column(Float)
    price_to_ocf: Mapped[Optional[float]] = mapped_column(Float)

    # Forward return label
    y_return: Mapped[Optional[float]] = mapped_column(Float)

    ingested_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("stock_id", "datadate", name="uq_qfund_stock_date"),
        Index("ix_qfund_symbol_date", "symbol", "datadate"),
        Index("ix_qfund_datadate", "datadate"),
    )


class SelectedStock(Base):
    """Stocks selected by the ML pipeline, persisted for predict-only mode."""

    __tablename__ = "selected_stocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    ml_score: Mapped[float] = mapped_column(Float, nullable=False)
    bucket: Mapped[Optional[str]] = mapped_column(String(50))
    weight: Mapped[Optional[float]] = mapped_column(Float)
    date_selected: Mapped[datetime] = mapped_column(Date, nullable=False)
    model_file: Mapped[Optional[str]] = mapped_column(String(255))
    pipeline_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    predicted_return: Mapped[Optional[float]] = mapped_column(Float)
    predicted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_return: Mapped[Optional[float]] = mapped_column(Float)
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("pipeline_runs.id"), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    backend: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_selected_stocks_ticker", "ticker"),
        Index("ix_selected_stocks_run_at", "pipeline_run_at"),
        Index("ix_selected_stocks_run_score", "pipeline_run_id", "ml_score"),
    )


class StockNews(Base):
    """Persistent cache for TradingAgents news tool calls (get_news, get_global_news, get_insider_transactions)."""

    __tablename__ = "stock_news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    start_date: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    end_date: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    result: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("tool_name", "ticker", "start_date", "end_date", name="uq_stock_news_key"),
        Index("ix_stock_news_ticker", "ticker"),
        Index("ix_stock_news_fetched_at", "fetched_at"),
    )




class FastEvaluationConclusion(Base):
    """Per-ticker consensus output from the fast evaluation step (ai-hedge-fund)."""

    __tablename__ = "fast_evaluation_conclusion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pipeline_runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    evaluation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consensus_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "ticker", "backend", name="uq_fec_run_ticker_backend"),
        Index("ix_fec_ticker", "ticker"),
    )


class FastEvaluationAnalyst(Base):
    """Per-analyst opinion output from the fast evaluation step."""

    __tablename__ = "fast_evaluation_analysts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pipeline_runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    analyst_name: Mapped[str] = mapped_column(String(64), nullable=False)
    opinion: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    evaluation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_fea_run_ticker", "pipeline_run_id", "ticker"),
    )


class DeepEvaluationRow(Base):
    """Deep-dive analysis output from the deep evaluation step (TradingAgents)."""

    __tablename__ = "deep_evaluation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pipeline_runs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    market_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bull_argument: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bear_argument: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_manager_decision: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trader_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_decision: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extra_outputs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_de_ticker", "ticker"),
        Index("ix_de_run", "pipeline_run_id"),
    )


class SchemaMigration(Base):
    """Tracks applied schema migrations so the migration runner can be idempotent."""

    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
