"""Production APScheduler daemon. Run via launchd on Mac Mini."""
import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from config import load_config
from database import get_session
from fetcher import create_fetcher
from models import ScheduledJobRun

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _record_job_start(job_name: str) -> int:
    session = get_session()
    try:
        run = ScheduledJobRun(job_name=job_name, started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()
        return run.id
    finally:
        session.close()


def _record_job_end(run_id: int, stocks_updated: int = 0, error: str | None = None):
    session = get_session()
    try:
        updates = {
            "finished_at": datetime.utcnow(),
            "stocks_updated": stocks_updated,
            "status": "failed" if error else "completed",
        }
        if error:
            updates["error_message"] = error[:2000]
        session.query(ScheduledJobRun).filter_by(id=run_id).update(updates)
        session.commit()
    finally:
        session.close()


def job_daily_pipeline():
    run_id = _record_job_start("daily_pipeline")
    stocks_updated = 0
    error = None
    try:
        logger.info("Daily pipeline triggered by scheduler.")
        config = load_config()
        fetcher = create_fetcher(config)
        from ingestion.pipeline import run_daily_pipeline
        summary = run_daily_pipeline(fetcher)
        stocks_updated = summary.get("processed", 0)
        logger.info("Daily pipeline done: %s", summary)
    except Exception as e:
        logger.error("Daily pipeline failed: %s", e)
        error = str(e)
    finally:
        _record_job_end(run_id, stocks_updated=stocks_updated, error=error)


def job_refresh_symbols():
    run_id = _record_job_start("symbol_refresh")
    count = 0
    error = None
    try:
        logger.info("Weekly symbol refresh triggered.")
        config = load_config()
        fetcher = create_fetcher(config)
        from ingestion.symbols import refresh_symbols
        count = refresh_symbols(fetcher)
        logger.info("Symbol refresh done: %d symbols", count)
    except Exception as e:
        logger.error("Symbol refresh failed: %s", e)
        error = str(e)
    finally:
        _record_job_end(run_id, stocks_updated=count, error=error)


def main():
    config = load_config()
    db_url = config["database"]["url"]
    scheduler_cfg = config.get("scheduler", {})
    run_time = scheduler_cfg.get("daily_run_time", "18:00")
    timezone = scheduler_cfg.get("timezone", "America/New_York")
    hour, minute = [int(x) for x in run_time.split(":")]

    jobstore = SQLAlchemyJobStore(url=db_url)
    scheduler = BlockingScheduler(
        jobstores={"default": jobstore},
        timezone=timezone,
    )

    # Daily pipeline — weekdays at configured time
    scheduler.add_job(
        job_daily_pipeline,
        CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=timezone),
        id="daily_pipeline",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly symbol refresh — Sundays at 02:00
    scheduler.add_job(
        job_refresh_symbols,
        CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=timezone),
        id="weekly_symbols",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info("Scheduler started. Daily pipeline at %s:%02d %s (Mon–Fri).", hour, minute, timezone)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
