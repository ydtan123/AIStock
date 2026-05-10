import pandas as pd


def print_predictions(results: list[dict]) -> None:
    """Print stock growth predictions with SHAP feature attribution."""
    ranked = sorted(
        [r for r in results if "error" not in r],
        key=lambda x: x["probability"],
        reverse=True,
    )
    errors = [r for r in results if "error" in r]

    for r in ranked:
        pct = r["probability"] * 100
        filled = int(pct / 5)
        bar = "█" * filled + "░" * (20 - filled)
        print(f"\n{'─' * 56}")
        print(f"  {r['symbol']:<6}  P(growth) = {pct:5.1f}%  [{bar}]")
        print(f"  As of: {r['input_end_date']}")

        if r.get("top_positive"):
            print("  ▲ Positive signals:")
            for item in r["top_positive"]:
                print(f"      {item['feature']:<32}  +{item['contribution']:.4f}")

        if r.get("top_negative"):
            print("  ▼ Negative signals:")
            for item in r["top_negative"]:
                print(f"      {item['feature']:<32}   {item['contribution']:.4f}")

    if errors:
        print(f"\n{'─' * 56}")
        for r in errors:
            print(f"  {r['symbol']}: {r['error']}")

    print(f"{'─' * 56}")


def fmt_market_cap(val) -> str:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        val = int(val)
    except (TypeError, ValueError):
        return "—"
    if val >= 1_000_000_000_000:
        return f"${val/1_000_000_000_000:.2f}T"
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    return f"${val:,}"


def nan_safe(fn):
    def _f(x):
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return "—"
            return fn(x)
        except (TypeError, ValueError):
            return "—"
    return _f
