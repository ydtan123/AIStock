"""CLI shim for the OOP pipeline.

Parses argv, builds a FullPipeline, runs it. Exits non-zero on failure.
All step logic lives in src/pipeline/.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Pre-import AIStock modules BEFORE any pipeline.backends import touches
# external/* paths — preserves the sys.path hazard discipline.
import config  # noqa: F401
import database  # noqa: F401
import models  # noqa: F401
import repository  # noqa: F401

from pipeline.base import PipelineError
from pipeline.config import ConfigLoader
from pipeline.data_update import DataUpdateStep
from pipeline.deep_evaluation import DeepEvaluationStep
from pipeline.fast_evaluation import FastEvaluationStep
from pipeline.orchestrator import FullPipeline
from pipeline.stock_selection import StockSelectionStep


STEPS_ORDER = [
    DataUpdateStep,
    StockSelectionStep,
    FastEvaluationStep,
    DeepEvaluationStep,
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AIStock OOP full pipeline")
    p.add_argument("--config", default="config.yaml")
    p.add_argument(
        "--set", dest="set_", action="append", default=[],
        help="Dotted-path override, KEY=VALUE; repeatable",
    )
    p.add_argument(
        "--resume-from", default=None,
        choices=[None, "data_update", "stock_selection",
                 "fast_evaluation", "deep_evaluation"],
    )
    p.add_argument("--run-id", type=int, default=None)
    p.add_argument(
        "--only", default=None,
        choices=[None, "data_update", "stock_selection",
                 "fast_evaluation", "deep_evaluation"],
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--log-level", default="INFO")
    p.add_argument(
        "--symbols", nargs="*", default=None,
        metavar="TICKER",
        help="Only process these symbols (comma/space separated). "
             "stock_selection skips; data/fast/deep evaluation filter to these tickers.",
    )
    return p.parse_args(argv)


def _setup_logging(level: str) -> logging.Logger:
    from datetime import datetime
    from pathlib import Path

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    )

    # Console handler (stderr)
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    # File handler — logs/fullpipeline_YYYYMMDDHHMM.log
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"fullpipeline_{datetime.now():%Y%m%d%H%M}.log"
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(fh)

    logger = logging.getLogger("full_pipeline")
    logger.info("Log file: %s", log_file)
    return logger


def _build_session_factory(cfg: dict):
    from database import get_session
    return get_session


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = _setup_logging(args.log_level)

    loader = ConfigLoader(args.config, overrides=args.set_)
    cfg = loader.load()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols if s.strip()]
        cfg.setdefault("pipeline", {})["symbols"] = symbols
        logger.info("Filtering to %d symbols: %s", len(symbols), symbols)

    report_root = Path("reports/full_pipeline")
    report_root.mkdir(parents=True, exist_ok=True)

    steps = [cls() for cls in STEPS_ORDER]
    pipeline = FullPipeline(
        steps=steps,
        cfg=cfg,
        session_factory=_build_session_factory(cfg),
        report_root=report_root,
        logger=logger,
        resume_from=args.resume_from,
        run_id=args.run_id,
        only=args.only,
    )

    if args.dry_run:
        logger.info("dry-run: would execute steps %s",
                    [s.name for s in pipeline._select_steps()])
        return 0

    try:
        run_id = pipeline.run()
        loader.write_effective(
            Path("reports/full_pipeline") / str(run_id) / "effective_config.yaml"
        )
        logger.info("pipeline run %d completed successfully", run_id)
        return 0
    except PipelineError as e:
        logger.error("pipeline failed: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
