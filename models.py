from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey,
    Index, Integer, SmallInteger, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.mysql import DECIMAL, JSON
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
    sample_features: Mapped[list["SampleFeature"]] = relationship(back_populates="stock")
    sample_labels: Mapped[list["SampleLabel"]] = relationship(back_populates="stock")

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


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    symbols_processed: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="running")


class StockPrediction(Base):
    __tablename__ = "stock_predictions"

    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), primary_key=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    input_end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    stock: Mapped["Stock"] = relationship()

    __table_args__ = (
        Index("ix_predictions_probability", "probability"),
    )


class SampleFeature(Base):
    __tablename__ = "sample_features"

    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), primary_key=True)
    input_end_date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    stock: Mapped["Stock"] = relationship()

    __table_args__ = (
        Index("ix_sample_features_symbol", "symbol"),
        Index("ix_sample_features_date", "input_end_date"),
    )


class SampleLabel(Base):
    __tablename__ = "sample_labels"

    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), primary_key=True)
    input_end_date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    label_method: Mapped[str] = mapped_column(String(50), primary_key=True)
    label: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    label_version: Mapped[str] = mapped_column(String(10), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    stock: Mapped["Stock"] = relationship()

    __table_args__ = (
        Index("ix_sample_labels_method", "label_method"),
        Index("ix_sample_labels_method_label", "label_method", "label"),
    )
