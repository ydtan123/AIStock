"""Migration runner tests: applies once, idempotent, tracks version."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from migrations.run import MigrationRunner
from models import SchemaMigration


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    # Only create schema_migrations — Base.metadata.create_all fails
    # on SQLite due to MySQL-specific types (MEDIUMTEXT).
    with e.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version VARCHAR(128) PRIMARY KEY,"
            "  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.commit()
    return e


def test_migration_applies_and_records(tmp_path, engine):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "2026_05_17_test.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY);"
    )
    runner = MigrationRunner(engine, mig_dir)
    runner.run_pending()

    with Session(engine) as s:
        rows = s.query(SchemaMigration).all()
        assert [r.version for r in rows] == ["2026_05_17_test"]
        s.execute(text("INSERT INTO foo (id) VALUES (1)"))
        s.commit()


def test_migration_is_idempotent(tmp_path, engine):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "2026_05_17_test.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY);"
    )
    runner = MigrationRunner(engine, mig_dir)
    runner.run_pending()
    # Running again should not re-apply (CREATE TABLE would fail otherwise)
    runner.run_pending()
    with Session(engine) as s:
        assert s.query(SchemaMigration).count() == 1


def test_skips_already_applied(tmp_path, engine):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "a.sql").write_text("CREATE TABLE t1 (id INTEGER);")
    (mig_dir / "b.sql").write_text("CREATE TABLE t2 (id INTEGER);")
    runner = MigrationRunner(engine, mig_dir)
    runner.run_pending()
    # Manually delete one version and check it re-applies; the other stays
    with Session(engine) as s:
        s.query(SchemaMigration).filter_by(version="b").delete()
        s.execute(text("DROP TABLE t2"))
        s.commit()
    runner.run_pending()
    with Session(engine) as s:
        versions = {r.version for r in s.query(SchemaMigration).all()}
        assert versions == {"a", "b"}
