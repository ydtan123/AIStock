import argparse
import logging
import sys
from datetime import date, datetime

from config import load_config
from fetcher import create_fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def cmd_init_db(args):
    from database import init_db
    init_db()


def cmd_bootstrap(args):
    config = load_config()
    fetcher = create_fetcher(config)

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


def _resolve_symbols(args) -> list[str]:
    """Parse --symbol args: supports space-separated and comma-separated values."""
    raw = args.symbol or []
    symbols = []
    for token in raw:
        symbols.extend(s.strip().upper() for s in token.split(",") if s.strip())
    return symbols


def _ensure_stock(symbol: str, force: bool) -> "Stock":
    """Return Stock record, creating a minimal one if missing and force=True."""
    from database import get_session
    from models import Stock

    session = get_session()
    try:
        stock = session.query(Stock).filter_by(symbol=symbol).first()
        if stock is None:
            if not force:
                logger.error("Symbol %s not found. Use --force to auto-create.", symbol)
                sys.exit(1)
            logger.info("--force: creating stock record for %s", symbol)
            stock = Stock(symbol=symbol, is_active=True, activated_at=datetime.utcnow())
            session.add(stock)
            session.commit()
            session.refresh(stock)
        elif not stock.is_active and force:
            logger.info("--force: activating %s for this run", symbol)
            stock.is_active = True
            stock.activated_at = datetime.utcnow()
            session.commit()
            session.refresh(stock)
        elif not stock.is_active:
            logger.error("Symbol %s is not active. Use --force to override.", symbol)
            sys.exit(1)
        return stock
    finally:
        session.close()


def cmd_run(args):
    config = load_config()
    if getattr(args, "source", None):
        config = dict(config)
        config["source"] = args.source
    fetcher = create_fetcher(config)

    from ingestion.pipeline import run_daily_pipeline

    symbols = _resolve_symbols(args)
    if symbols:
        from ingestion.pipeline import _process_symbol, _refresh_snapshots
        from model.train import load_model, load_feature_columns
        from model.labels import LABEL_METHODS

        models = []
        for method in LABEL_METHODS:
            b = load_model(method.name)
            fc = load_feature_columns(method.name) if b is not None else None
            if b is not None and fc:
                models.append((b, fc, method.name))

        for sym in symbols:
            stock = _ensure_stock(sym, args.force)
            result = _process_symbol(fetcher, stock, force=args.force,
                                     models=models if models else None)
            logger.info("Result [%s]: %s", sym, result)

        _refresh_snapshots()
    else:
        summary = run_daily_pipeline(fetcher, force=args.force)
        logger.info("Pipeline summary: processed=%d errors=%d", summary["processed"], summary["errors"])


def cmd_train(args):
    from model.labels import LABEL_METHODS

    label_filter = getattr(args, "label", None)
    methods = [m for m in LABEL_METHODS if label_filter is None or m.name == label_filter]
    if not methods:
        logger.error("Unknown label method: %s", label_filter)
        sys.exit(1)

    if getattr(args, "tune", False):
        from model.train import tune_hyperparams
        n_trials = getattr(args, "trials", 50)
        for method in methods:
            logger.info("Tuning hyperparams for label: %s  trials=%d", method.name, n_trials)
            metrics = tune_hyperparams(label_method=method.name, n_trials=n_trials)
            logger.info("Tune result [%s]: %s", method.name, metrics)
    else:
        from model.train import train
        for method in methods:
            logger.info("Training model for label: %s", method.name)
            metrics = train(label_method=method.name)
            logger.info("Metrics [%s]: %s", method.name, metrics)


def cmd_predict(args):
    if args.symbols:
        from model.inference import predict_stocks
        from display import print_predictions
        results = predict_stocks(args.symbols, top_n=args.top_n)
        print_predictions(results)
    else:
        from model.inference import run_batch_inference
        summary = run_batch_inference()
        logger.info("Inference: %s", summary)


def cmd_report(args):
    from model.train import data_quality_report
    data_quality_report()


def main():
    parser = argparse.ArgumentParser(description="StockDB — Stock Data Management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create all database tables")

    sub.add_parser("bootstrap", help="Initial setup: load symbols + fetch all fundamentals (~84 min)")

    run_p = sub.add_parser("run", help="Run daily pipeline (or single symbol with --symbol)")
    run_p.add_argument("--symbol", "-s", nargs="+",
                       help="One or more symbols (space or comma-separated, e.g. AAPL MSFT or 'AAPL,MSFT')")
    run_p.add_argument("--force", action="store_true", help="Bypass is_active check, force re-fetch fundamentals")
    run_p.add_argument("--source", choices=["alpha_vantage", "yahoo"],
                       help="Override data source for this run (default: from config.yaml)")
    run_p.add_argument("--start", type=lambda s: date.fromisoformat(s), default=None, help="Override start date (YYYY-MM-DD)")
    run_p.add_argument("--end", type=lambda s: date.fromisoformat(s), default=None, help="Override end date (YYYY-MM-DD)")

    train_p = sub.add_parser("train", help="Train XGBoost growth prediction model")
    train_p.add_argument("--label", "-l", default=None,
                         help="Label method to train (default: all). e.g. beats_spy")
    train_p.add_argument("--tune", action="store_true",
                         help="Run Optuna hyperparameter search instead of default train")
    train_p.add_argument("--trials", type=int, default=50,
                         help="Number of Optuna trials (default: 50, used with --tune)")

    predict_p = sub.add_parser(
        "predict",
        help="Score stocks. With symbols: show SHAP attribution. Without: batch score all active stocks.",
    )
    predict_p.add_argument(
        "symbols", nargs="*", metavar="SYMBOL",
        help="Symbols to score (e.g. AAPL MSFT). Omit to score all active stocks.",
    )
    predict_p.add_argument(
        "--top-n", type=int, default=5, dest="top_n",
        help="Number of top positive/negative SHAP features to show (default: 5)",
    )
    sub.add_parser("report", help="Data quality report: coverage, gaps, counts")

    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "bootstrap":
        cmd_bootstrap(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "train":
        cmd_train(args)
    elif args.command == "predict":
        cmd_predict(args)
    elif args.command == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
