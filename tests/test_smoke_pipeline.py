"""Smoke tests: training and prediction pipelines for each label method.

Trains once per label (module scope), then reuses for predict test.
Uses 300 rows/split and 20 boost rounds — pipeline correctness, not model quality.

Usage:
    pytest tests/test_smoke_pipeline.py -m smoke -s
    pytest tests/test_smoke_pipeline.py -m smoke -k max_high_5pct -s
"""

import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest

import model.train as train_mod
from database import get_session
from model.inference import predict_stocks
from model.labels import LABEL_METHODS
from model.train import train
from models import Stock

_LABEL_NAMES = [m.name for m in LABEL_METHODS]

# Trained once per label per session: {label: (model_dir, metrics)}
_SMOKE_CACHE: dict[str, tuple[Path, dict]] = {}


def _train_for_smoke(label: str) -> tuple[Path, dict]:
    """Train with smoke settings; cache result to avoid re-training."""
    if label in _SMOKE_CACHE:
        model_dir, metrics = _SMOKE_CACHE[label]
        train_mod.MODEL_DIR = model_dir
        return model_dir, metrics

    model_dir = Path(tempfile.mkdtemp(prefix=f"smoke_{label}_"))
    train_mod.MODEL_DIR = model_dir
    print(f"\n[{label}] training smoke (300 rows/split, 20 rounds)...")
    try:
        metrics = train(
            label_method=label,
            save=True,
            skip_generate=True,
            smoke_test=True,
            num_boost_round=20,
        )
    except RuntimeError as exc:
        shutil.rmtree(model_dir, ignore_errors=True)
        raise

    print(
        f"[{label}] train done — val_auc={metrics['val_auc']:.4f}  "
        f"test_auc={metrics['test_auc']:.4f}  "
        f"samples={metrics['train_samples']}  features={metrics['features']}"
    )
    _SMOKE_CACHE[label] = (model_dir, metrics)
    return model_dir, metrics


@pytest.fixture(scope="module", autouse=True)
def _cleanup_smoke_cache() -> Generator[None, None, None]:
    """Delete tmp model dirs after all smoke tests in this module finish."""
    yield
    for model_dir, _ in _SMOKE_CACHE.values():
        shutil.rmtree(model_dir, ignore_errors=True)
    _SMOKE_CACHE.clear()


@pytest.mark.smoke
@pytest.mark.parametrize("label", _LABEL_NAMES)
def test_train_smoke(label: str) -> None:
    """Training pipeline completes and returns valid metrics."""
    try:
        _, metrics = _train_for_smoke(label)
    except RuntimeError as exc:
        if "SPY prices required" in str(exc):
            pytest.skip(str(exc))
        raise

    assert isinstance(metrics, dict)
    for key in ("val_auc", "test_auc", "train_samples", "features"):
        assert key in metrics, f"missing metric key: {key}"
    assert 0.0 <= metrics["val_auc"] <= 1.0, f"val_auc out of range: {metrics['val_auc']}"
    assert 0.0 <= metrics["test_auc"] <= 1.0, f"test_auc out of range: {metrics['test_auc']}"
    assert metrics["train_samples"] > 0, "no training samples — run generate_and_persist_samples first"
    assert metrics["features"] > 0, "zero features learned"


@pytest.mark.smoke
@pytest.mark.parametrize("label", _LABEL_NAMES)
def test_predict_smoke(label: str) -> None:
    """Prediction pipeline returns valid probability using the cached trained model."""
    try:
        _train_for_smoke(label)
    except RuntimeError as exc:
        if "SPY prices required" in str(exc):
            pytest.skip(str(exc))
        raise

    session = get_session()
    stock = session.query(Stock).filter(Stock.is_active == True).first()
    session.close()
    if stock is None:
        pytest.skip("no active stocks in DB")

    print(f"[{label}] predicting {stock.symbol}...")
    try:
        results = predict_stocks([stock.symbol], label_method=label)
    except RuntimeError as exc:
        if "SPY prices required" in str(exc):
            pytest.skip(str(exc))
        raise

    assert results, "predict_stocks returned empty list"
    r = results[0]
    assert "error" not in r, f"prediction failed for {stock.symbol}: {r.get('error')}"
    assert 0.0 <= r["probability"] <= 1.0, f"probability out of range: {r['probability']}"
    assert isinstance(r.get("top_positive"), list), "missing top_positive"
    assert isinstance(r.get("top_negative"), list), "missing top_negative"
    print(f"[{label}] predict done — {stock.symbol} prob={r['probability']:.4f}")
