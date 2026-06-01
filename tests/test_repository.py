"""Tests for repository layer (src/repository.py).

Covers methods currently at 24.2%: get_stocks, get_active_stocks, count_summary,
save_selected_stocks, get_latest_selected_stocks, bulk_set_active, get_job_runs,
get_sectors, and edge cases for empty databases.
"""
import pandas as pd
import pytest

from database import configure, init_db, get_session
from models import ScheduledJobRun, Stock
from repository import StockRepository


@pytest.fixture(autouse=True)
def _setup_db():
    configure("sqlite:///:memory:")
    init_db()


@pytest.fixture
def repo():
    return StockRepository()


def _seed_stock(symbol="AAPL", **kwargs):
    defaults = {"symbol": symbol, "name": f"{symbol} Inc.", "is_active": True}
    defaults.update(kwargs)
    s = get_session()
    stock = Stock(**defaults)
    s.add(stock)
    s.commit()
    sid = stock.id
    s.close()
    return sid


class TestGetStocks:
    def test_empty_database_returns_empty_list(self, repo):
        result = repo.get_stocks()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_list_of_dicts(self, repo):
        _seed_stock("AAPL")
        stocks = repo.get_stocks()
        assert len(stocks) >= 1
        assert isinstance(stocks[0], dict)
        assert stocks[0]["symbol"] == "AAPL"

    def test_returns_all_stocks(self, repo):
        _seed_stock("AAPL")
        _seed_stock("MSFT")
        _seed_stock("GOOGL")
        stocks = repo.get_stocks()
        assert len(stocks) == 3


class TestGetActiveStocks:
    def test_filters_active_only(self, repo):
        _seed_stock("ACTIVE", is_active=True)
        _seed_stock("INACTIVE", is_active=False)
        result = repo.get_active_stocks()
        symbols = {r["symbol"] for r in result}
        assert "ACTIVE" in symbols
        assert "INACTIVE" not in symbols

    def test_no_active_returns_empty(self, repo):
        _seed_stock("INACTIVE1", is_active=False)
        _seed_stock("INACTIVE2", is_active=False)
        result = repo.get_active_stocks()
        assert len(result) == 0


class TestGetActiveSymbols:
    def test_returns_list_of_strings(self, repo):
        _seed_stock("AAPL")
        _seed_stock("MSFT")
        symbols = repo.get_active_symbols()
        assert isinstance(symbols, list)
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_excludes_inactive(self, repo):
        _seed_stock("ACTIVE", is_active=True)
        _seed_stock("INACTIVE", is_active=False)
        symbols = repo.get_active_symbols()
        assert "ACTIVE" in symbols
        assert "INACTIVE" not in symbols


class TestCountSummary:
    def test_returns_total_active_inactive(self, repo):
        _seed_stock("A1", is_active=True)
        _seed_stock("A2", is_active=True)
        _seed_stock("I1", is_active=False)
        summary = repo.count_summary()
        assert summary["total"] == 3
        assert summary["active"] == 2
        assert summary["inactive"] == 1

    def test_empty_database(self, repo):
        summary = repo.count_summary()
        assert summary["total"] == 0
        assert summary["active"] == 0
        assert summary["inactive"] == 0


class TestSaveSelectedStocks:
    def test_inserts_and_retrieves(self, repo):
        records = [{"ticker": "AAPL", "model_name": "test_model", "ml_score": 0.85,
                     "bucket": "tech", "weight": 0.5}]
        count = repo.save_selected_stocks(records)
        assert count == 1

        result = repo.get_latest_selected_stocks()
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"
        assert result[0]["ml_score"] == 0.85

    def test_overwrites_previous_selection(self, repo):
        repo.save_selected_stocks([{"ticker": "OLD", "model_name": "x",
                                     "ml_score": 0.1, "weight": 1.0}])
        repo.save_selected_stocks([{"ticker": "NEW", "model_name": "x",
                                     "ml_score": 0.9, "weight": 1.0}])
        result = repo.get_latest_selected_stocks()
        assert len(result) == 1
        assert result[0]["ticker"] == "NEW"

    def test_get_latest_returns_empty_when_no_selection(self, repo):
        result = repo.get_latest_selected_stocks()
        assert isinstance(result, list)
        assert len(result) == 0


class TestBulkSetActive:
    def test_sets_multiple_stocks_inactive(self, repo):
        sid1 = _seed_stock("B1", is_active=True)
        sid2 = _seed_stock("B2", is_active=True)
        repo.bulk_set_active([sid1, sid2], False)

        s = get_session()
        rows = s.query(Stock).filter(Stock.id.in_([sid1, sid2])).all()
        s.close()
        assert all(not r.is_active for r in rows)

    def test_empty_ids_noop(self, repo):
        repo.bulk_set_active([], True)

    def test_sets_active_with_timestamp(self, repo):
        sid = _seed_stock("B3", is_active=False)
        repo.bulk_set_active([sid], True)
        s = get_session()
        row = s.query(Stock).filter_by(id=sid).first()
        s.close()
        assert row.is_active is True
        assert row.activated_at is not None


class TestGetJobRuns:
    def test_empty_returns_empty_dataframe(self, repo):
        df = repo.get_job_runs()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_returns_recent_runs(self, repo):
        s = get_session()
        s.add(ScheduledJobRun(job_name="test_job", status="completed"))
        s.commit()
        s.close()

        df = repo.get_job_runs()
        assert not df.empty
        assert "test_job" in df["Job Name"].values

    def test_respects_limit(self, repo):
        s = get_session()
        for i in range(5):
            s.add(ScheduledJobRun(job_name=f"job_{i}", status="completed"))
        s.commit()
        s.close()

        df = repo.get_job_runs(limit=3)
        assert len(df) <= 3


class TestGetSectors:
    def test_returns_distinct_sectors(self, repo):
        _seed_stock("S1", sector="Technology")
        _seed_stock("S2", sector="Technology")
        _seed_stock("S3", sector="Healthcare")
        sectors = repo.get_sectors(table="stocks")
        assert "Technology" in sectors
        assert "Healthcare" in sectors
        assert len(sectors) == len(set(sectors))

    def test_empty_returns_empty_list(self, repo):
        sectors = repo.get_sectors(table="stocks")
        assert isinstance(sectors, list)
