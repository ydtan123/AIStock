"""Production APScheduler daemon. Run via launchd on Mac Mini."""
import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from config import load_config
from fetcher import create_fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def job_daily_pipeline():
    logger.info("Daily pipeline triggered by scheduler.")
    config = load_config()
    fetcher = create_fetcher(config)
    from ingestion.pipeline import run_daily_pipeline
    summary = run_daily_pipeline(fetcher)
    logger.info("Daily pipeline done: %s", summary)


def job_refresh_symbols():
    logger.info("Weekly symbol refresh triggered.")
    config = load_config()
    fetcher = create_fetcher(config)
    from ingestion.symbols import refresh_symbols
    count = refresh_symbols(fetcher)
    logger.info("Symbol refresh done: %d symbols", count)


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
