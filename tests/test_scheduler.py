"""Tests for scheduler module (src/scheduler.py)."""
import pytest


class TestRecordJobStart:
    def test_creates_running_record(self):
        from database import configure, init_db, get_session
        from models import ScheduledJobRun
        from scheduler import _record_job_start

        configure("sqlite:///:memory:")
        init_db()

        run_id = _record_job_start("test_job")
        assert run_id > 0

        s = get_session()
        row = s.query(ScheduledJobRun).filter_by(id=run_id).first()
        s.close()
        assert row.job_name == "test_job"
        assert row.status == "running"
        assert row.started_at is not None


class TestRecordJobEnd:
    def test_success_updates_status(self):
        from database import configure, init_db, get_session
        from models import ScheduledJobRun
        from scheduler import _record_job_start, _record_job_end

        configure("sqlite:///:memory:")
        init_db()

        run_id = _record_job_start("success_job")
        _record_job_end(run_id, stocks_updated=10, error=None)

        s = get_session()
        row = s.query(ScheduledJobRun).filter_by(id=run_id).first()
        s.close()
        assert row.status == "completed"
        assert row.stocks_updated == 10
        assert row.finished_at is not None

    def test_failure_sets_error_message(self):
        from database import configure, init_db, get_session
        from models import ScheduledJobRun
        from scheduler import _record_job_start, _record_job_end

        configure("sqlite:///:memory:")
        init_db()

        run_id = _record_job_start("fail_job")
        _record_job_end(run_id, stocks_updated=0, error="Connection refused")

        s = get_session()
        row = s.query(ScheduledJobRun).filter_by(id=run_id).first()
        s.close()
        assert row.status == "failed"
        assert "Connection refused" in row.error_message

    def test_error_message_truncated_to_2000_chars(self):
        from database import configure, init_db, get_session
        from models import ScheduledJobRun
        from scheduler import _record_job_start, _record_job_end

        configure("sqlite:///:memory:")
        init_db()

        run_id = _record_job_start("truncate_job")
        long_error = "x" * 5000
        _record_job_end(run_id, error=long_error)

        s = get_session()
        row = s.query(ScheduledJobRun).filter_by(id=run_id).first()
        s.close()
        assert len(row.error_message) <= 2000


class TestJobDailyPipeline:
    def test_catches_exceptions_and_records_failure(self, monkeypatch):
        from database import configure, init_db, get_session
        from models import ScheduledJobRun
        from scheduler import job_daily_pipeline

        configure("sqlite:///:memory:")
        init_db()

        monkeypatch.setattr("scheduler.load_config", lambda: 1 / 0)

        job_daily_pipeline()

        s = get_session()
        row = s.query(ScheduledJobRun).filter_by(job_name="daily_pipeline").order_by(
            ScheduledJobRun.id.desc()).first()
        s.close()
        assert row is not None
        assert row.status == "failed"
        assert row.error_message is not None


class TestJobRefreshSymbols:
    def test_catches_exceptions_and_records_failure(self, monkeypatch):
        from database import configure, init_db, get_session
        from models import ScheduledJobRun
        from scheduler import job_refresh_symbols

        configure("sqlite:///:memory:")
        init_db()

        monkeypatch.setattr("scheduler.load_config", lambda: 1 / 0)

        job_refresh_symbols()

        s = get_session()
        row = s.query(ScheduledJobRun).filter_by(job_name="symbol_refresh").order_by(
            ScheduledJobRun.id.desc()).first()
        s.close()
        assert row is not None
        assert row.status == "failed"
        assert row.error_message is not None
