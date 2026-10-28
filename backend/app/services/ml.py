"""Threshold tool over the IEEE-CIS held-out test predictions (real data, advisory only).

Merchants pick an operating point and see precision / recall / FPR and the SIMULATED cost
trade-off. Training lives in /ml and is offline; this module only reads its artifacts.
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import NotFound, ValidationFailed

ML_DIR = Path(__file__).resolve().parents[1] / "ml"
PREDICTIONS = ML_DIR / "ieee_test_predictions.csv"
REPORT = ML_DIR / "ieee_report.json"
OPS_COST_PER_BLOCK = 120.0
DISCLAIMER = "Costs use the SIMULATED cost model. Amounts are IEEE-CIS test amounts (USD)."


@lru_cache(maxsize=1)
def _predictions() -> tuple[tuple[float, int, float], ...]:
    if not PREDICTIONS.exists():
        raise NotFound("Model predictions are not available")
    with PREDICTIONS.open(newline="") as fh:
        return tuple((float(r["prob"]), int(r["isFraud"]), float(r["amount"])) for r in csv.DictReader(fh))


def report() -> dict[str, Any]:
    if not REPORT.exists():
        raise NotFound("Model report is not available")
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    model = data.get("logistic") or {}
    return {
        "model": "logistic_regression",
        "dataset": "IEEE-CIS Fraud Detection",
        "n_train": data.get("n_train"),
        "n_validation": data.get("n_val"),
        "n_test": data.get("n_test"),
        "validation": model.get("val"),
        "test": model.get("test"),
        "feature_importance": data.get("feature_importance", []),
        "disclaimer": "Evaluated on a temporal held-out split. With ~3.5% fraud, PR-AUC is the honest headline, "
                      "not accuracy. The model is advisory and does not change PayTrust decisions.",
    }


def metrics_at(threshold: float) -> dict[str, Any]:
    if not 0.0 <= threshold <= 1.0:
        raise ValidationFailed("threshold must be between 0 and 1")
    s = get_settings()
    fp_fixed = s.FP_CUSTOMER_FRICTION_COST + s.FP_SUPPORT_COST + s.FP_MERCHANT_IMPACT_COST
    tp = fp = tn = fn = 0
    fp_amount = fn_amount = 0.0
    for prob, is_fraud, amount in _predictions():
        flagged = prob >= threshold
        if flagged and is_fraud:
            tp += 1
        elif flagged:
            fp += 1
            fp_amount += amount
        elif is_fraud:
            fn += 1
            fn_amount += amount
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fraud_exposure = fn_amount * s.FN_FRAUD_EXPOSURE_MULTIPLIER
    fp_cost = fp * fp_fixed + fp_amount * s.FP_LOST_TRANSACTION_VALUE_MULTIPLIER * 0.1
    ops_cost = (tp + fp) * OPS_COST_PER_BLOCK
    return {
        "threshold": round(threshold, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
        "fraud_exposure": round(fraud_exposure, 2),
        "false_positive_cost": round(fp_cost, 2),
        "operational_cost": round(ops_cost, 2),
        "expected_total_cost": round(fraud_exposure + fp_cost + ops_cost, 2),
    }


@lru_cache(maxsize=4)
def curves(step: float = 0.01) -> dict[str, Any]:
    points = [metrics_at(min(1.0, round(i * step, 6))) for i in range(int(round(1 / step)) + 1)]
    best_f1 = max(points, key=lambda p: p["f1"])
    best_cost = min(points, key=lambda p: p["expected_total_cost"])
    return {
        "points": points,
        "recommended": {"max_f1": best_f1["threshold"], "min_cost": best_cost["threshold"]},
        "n": len(_predictions()),
        "disclaimer": DISCLAIMER,
    }
