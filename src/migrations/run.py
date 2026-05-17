"""Idempotent SQL migration runner. Tracks applied versions in schema_migrations."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from models import SchemaMigration

logger = logging.getLogger(__name__)


class MigrationRunner:
    def __init__(self, engine: Engine, migrations_dir: str | Path):
        self.engine = engine
        self.dir = Path(migrations_dir)

    def applied_versions(self) -> set[str]:
        with Session(self.engine) as s:
            return {r.version for r in s.query(SchemaMigration).all()}

    def discover(self) -> list[Path]:
        return sorted(self.dir.glob("*.sql"))

    def run_pending(self) -> list[str]:
        applied = self.applied_versions()
        ran: list[str] = []
        for path in self.discover():
            version = path.stem
            if version in applied:
                logger.info("skip migration %s (already applied)", version)
                continue
            sql = path.read_text()
            logger.info("applying migration %s", version)
            with self.engine.begin() as conn:
                for statement in self._split_statements(sql):
                    if statement.strip():
                        conn.execute(text(statement))
            with Session(self.engine) as s:
                s.add(SchemaMigration(version=version))
                s.commit()
            ran.append(version)
        return ran

    @staticmethod
    def _split_statements(sql: str) -> list[str]:
        return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
