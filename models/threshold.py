"""models/threshold.py — Threshold decision tool over the real IEEE held-out test set.

Why this exists (Track 02 rubric): a merchant should choose *where* to draw the line,
seeing live precision / recall / FPR / confusion-matrix and the SIMULATED cost trade-off
(fraud exposure from missed fraud vs false-positive cost from blocked legit customers).
No fake numbers — this reads predictions saved from the actual held-out IEEE test set
by `models/train_ieee_chunked.py` → `evaluation/ieee_test_predictions.parquet`.

Costs are SIMULATED/ESTIMATED (cost model in core/config.py) and clearly labeled.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.config import get_settings

DEFAULT_PREDS = Path(__file__).resolve().parents[1] / "evaluation" / "ieee_test_predictions.parquet"


def load_test_predictions(path: Path | str | None = None) -> pd.DataFrame:
    """Load the honest held-out test predictions (prob, isFraud, amount[, TransactionID])."""
    p = Path(path) if path else DEFAULT_PREDS
    if not p.exists():
        raise FileNotFoundError(
            f"Test predictions not found at {p}. Generate with: python -m models.train_ieee_chunked --train-only"
        )
    return pd.read_parquet(p)


def _cost_model(amounts_fp: pd.Series, amounts_fn: pd.Series, settings=None) -> dict[str, float]:
    """SIMULATED cost estimates from the configured cost model (never real forecasts)."""
    s = settings or get_settings()
    per_fp_unit = (
        s.FP_CUSTOMER_FRICTION_COST + s.FP_SUPPORT_COST + s.FP_MERCHANT_IMPACT_COST
    )
    fp_amt = float(amounts_fp.sum()) if len(amounts_fp) else 0.0
    fn_amt = float(amounts_fn.sum()) if len(amounts_fn) else 0.0
    return {
        "per_fp_fixed_unit": per_fp_unit,
        "false_positive_cost": round(
            len(amounts_fp) * per_fp_unit + fp_amt * s.FP_LOST_TRANSACTION_VALUE_MULTIPLIER * 0.1, 2
        ),
        "fraud_exposure": round(fn_amt * s.FN_FRAUD_EXPOSURE_MULTIPLIER, 2),
    }


def metrics_at(threshold: float, df: pd.DataFrame | None = None, settings=None) -> dict[str, Any]:
    """Classification + SIMULATED cost metrics at one probability operating point."""
    data = df if df is not None else load_test_predictions()
    t = float(threshold)
    if not 0.0 <= t <= 1.0:
        raise ValueError("threshold must be in [0,1]")
    prob = data["prob"].astype(float).to_numpy()
    y = data["isFraud"].astype(int).to_numpy()
    pred = (prob >= t).astype(int)

    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    fnr = fn / (fn + tp) if (fn + tp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    amounts = data["amount"].astype(float) if "amount" in data.columns else pd.Series([0.0] * len(data))
    amounts.index = np.arange(len(amounts))
    fp_mask = (pred == 1) & (y == 0)
    fn_mask = (pred == 0) & (y == 1)
    cost = _cost_model(amounts[fp_mask], amounts[fn_mask], settings=settings)
    op_cost = float((tp + fp) * 120)  # per blocked transaction review/support overhead (SIMULATED)

    # Full float precision is the source of truth for the compute layer;
    # presentation layers (UI/API clients) round for display as needed.
    return {
        "threshold": t,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
        "blocked_count": tp + fp,
        "allowed_count": tn + fn,
        "fraud_exposure": cost["fraud_exposure"],
        "false_positive_cost": cost["false_positive_cost"],
        "operational_cost": round(op_cost, 2),
        "expected_total_cost": round(cost["fraud_exposure"] + cost["false_positive_cost"] + op_cost, 2),
        "currency": "USD (IEEE test amounts) — SIMULATED cost model",
        "disclaimer": "SIMULATED / ESTIMATED cost model (core/config.py). Not a financial forecast.",
    }


def sweep(step: float = 0.01, df: pd.DataFrame | None = None, settings=None) -> list[dict[str, Any]]:
    """All operating-point metrics across thresholds — feeds threshold-curve charts."""
    data = df if df is not None else load_test_predictions()
    thresholds = [round(x, 10) for x in np.arange(0.0, 1.0 + 1e-9, step)]
    return [metrics_at(t, data, settings=settings) for t in thresholds]


def to_curves(sweep_results: list[dict[str, Any]]) -> dict[str, list]:
    """Extract chartable arrays from sweep results."""
    keys = [
        "threshold", "precision", "recall", "f1", "false_positive_rate", "false_negative_rate",
        "fraud_exposure", "false_positive_cost", "expected_total_cost", "blocked_count",
    ]
    return {k: [r[k] for r in sweep_results] for k in keys}


def best_operating_point(df: pd.DataFrame | None = None, settings=None) -> dict[str, Any]:
    """Recommend operating points: max F1 and min SIMULATED expected total cost (labeled)."""
    data = df if df is not None else load_test_predictions()
    results = sweep(step=0.01, df=data, settings=settings)
    best_f1 = max(results, key=lambda r: r["f1"])
    best_cost = min(results, key=lambda r: r["expected_total_cost"])
    return {
        "max_f1": best_f1,
        "min_expected_total_cost": best_cost,
        "disclaimer": "OPTIMAL threshold is a business decision — these are optimization hints over a SIMULATED cost model.",
    }


if __name__ == "__main__":
    import json
    b = best_operating_point()
    print(json.dumps({"max_f1": b["max_f1"], "min_expected_total_cost": b["min_expected_total_cost"]}, indent=2))