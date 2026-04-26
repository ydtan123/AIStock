import argparse
import logging
import sys
from datetime import date, datetime

import yaml
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        logger.error("config.yaml not found. Copy config.yaml.example to config.yaml and fill in values.")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_fetcher(config: dict):
    source = config.get("source", "alpha_vantage")
    if source == "alpha_vantage":
        from fetcher.alpha_vantage import AlphaVantageFetcher
        return AlphaVantageFetcher(api_key=config["alpha_vantage"]["api_key"])
    elif source == "yahoo":
        from fetcher.yahoo import YahooFetcher
        return YahooFetcher()
    else:
        raise ValueError(f"Unknown source: {source}")


def cmd_init_db(args):
    from database import init_db
    init_db()


def cmd_bootstrap(args):
    config = _load_config()
    fetcher = _get_fetcher(config)

    from database import get_session
    from ingestion.symbols import refresh_symbols
    from ingestion.pipeline import run_bootstrap
    from models import Stock

    logger.info("Step 1: Refreshing symbol listing...")
    refresh_symbols(fetcher)

    criteria = config.get("default_activation_criteria")
    logger.info("Step 2: Fetching OVERVIEW for all symbols (this takes ~84 min)...")
    run_bootstrap(fetcher, auto_activate_criteria=criteria)
    logger.info("Bootstrap complete. Open the Manager tab to activate stocks, then run the scheduler.")


def cmd_run(args):
    config = _load_config()
    fetcher = _get_fetcher(config)

    from database import get_session
    from ingestion.pipeline import run_daily_pipeline
    from models import Stock

    if args.symbol:
        # Single-symbol mode
        session = get_session()
        stock = session.query(Stock).filter_by(symbol=args.symbol.upper()).first()
        session.close()

        if not stock:
            logger.error("Symbol %s not found. Run --bootstrap first.", args.symbol)
            sys.exit(1)

        if not args.force and not stock.is_active:
            logger.error("Symbol %s is not active. Use --force to override.", args.symbol)
            sys.exit(1)

        if not stock.is_active and args.force:
            logger.info("--force: activating %s temporarily for this run.", args.symbol)
            session = get_session()
            stock = session.query(Stock).filter_by(symbol=args.symbol.upper()).first()
            stock.is_active = True
            stock.activated_at = datetime.utcnow()
            session.commit()
            session.close()

        from ingestion.pipeline import _process_symbol, _refresh_snapshots
        result = _process_symbol(fetcher, stock, force=args.force)
        _refresh_snapshots()
        logger.info("Result: %s", result)
    else:
        summary = run_daily_pipeline(fetcher, force=args.force)
        logger.info("Pipeline summary: processed=%d errors=%d", summary["processed"], summary["errors"])


def main():
    parser = argparse.ArgumentParser(description="StockDB — Stock Data Management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create all database tables")

    sub.add_parser("bootstrap", help="Initial setup: load symbols + fetch all fundamentals (~84 min)")

    run_p = sub.add_parser("run", help="Run daily pipeline (or single symbol with --symbol)")
    run_p.add_argument("--symbol", "-s", help="Single symbol to process")
    run_p.add_argument("--force", action="store_true", help="Bypass is_active check, force re-fetch fundamentals")
    run_p.add_argument("--start", type=lambda s: date.fromisoformat(s), default=None, help="Override start date (YYYY-MM-DD)")
    run_p.add_argument("--end", type=lambda s: date.fromisoformat(s), default=None, help="Override end date (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "bootstrap":
        cmd_bootstrap(args)
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
