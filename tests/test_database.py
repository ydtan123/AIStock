"""Tests for database module (src/database.py).

Uses in-memory SQLite via configure() override.
"""
import pytest
from sqlalchemy import text


class TestConfigure:
    def test_override_url_resets_engine(self):
        from database import configure, get_engine
        configure("sqlite:///test_override.db")
        engine = get_engine()
        assert "test_override" in str(engine.url)

    def test_switching_urls_resets_factory(self):
        from database import configure, get_engine, get_session_factory
        configure("sqlite:///first.db")
        e1 = get_engine()
        f1 = get_session_factory()
        configure("sqlite:///second.db")
        e2 = get_engine()
        f2 = get_session_factory()
        assert e1 is not e2
        assert f1 is not f2


class TestGetEngine:
    def test_creates_engine_via_configure(self):
        import database
        database._engine = None
        database._url = "sqlite:///engine_test.db"
        engine = database.get_engine()
        assert engine is not None

    def test_reuses_cached_engine(self):
        import database
        database._engine = None
        database._url = "sqlite:///cache_test.db"
        e1 = database.get_engine()
        e2 = database.get_engine()
        assert e1 is e2

    def test_pool_pre_ping_enabled(self):
        import database
        database._engine = None
        database._url = "sqlite:///ping_test.db"
        engine = database.get_engine()
        assert engine.pool._pre_ping is True


class TestGetSession:
    def test_returns_valid_session(self):
        import database
        database._engine = None
        database._url = "sqlite:///session_test.db"
        session = database.get_session()
        assert session is not None
        session.execute(text("SELECT 1"))
        session.close()

    def test_expire_on_commit_disabled(self):
        import database
        database._engine = None
        database._url = "sqlite:///expire_test.db"
        factory = database.get_session_factory()
        assert factory.kw.get("expire_on_commit") is False


class TestInitDb:
    def test_creates_all_tables_without_error(self):
        import database
        from models import Base
        database._engine = None
        database._url = "sqlite:///init_test.db"
        database.init_db()
        engine = database.get_engine()
        inspector_result = set(Base.metadata.tables.keys())
        assert "stocks" in inspector_result
        assert "daily_prices" in inspector_result
