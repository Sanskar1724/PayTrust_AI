"""
evaluation/run_evaluation.py — Reproducible evaluation entry point.

Spec requirement (prompt.txt §EVALUATION):
    python evaluation/run_evaluation.py
    → evaluation/results.json + evaluation/report.md

Computes on the REAL held-out IEEE-CIS test set (3,000 temporal rows,
predictions committed at evaluation/ieee_test_predictions.parquet — no retrain,
no leakage; the model never saw these rows):

    precision, recall, F1, FPR, FNR, confusion matrix, PR-AUC, ROC-AUC
  + SIMULATED false-positive / fraud-exposure cost sweep across thresholds
    (cost model from core/config.py — FP_*/FN_*, clearly labeled as
    SIMULATED assumptions, never presented as real business impact)

Also merges the synthetic-data demo model report (evaluation/ml_report.json)
when present, explicitly labeled as NOT real-fraud performance.

Usage:
    python evaluation/run_evaluation.py                       # default paths
    python evaluation/run_evaluation.py --predictions PATH    # custom parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    precision_recall_curve,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    average_precision_score,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core.config import get_settings  # noqa: E402

settings = get_settings()

DEFAULT_PREDICTIONS = HERE / "ieee_test_predictions.parquet"
RESULTS_PATH = HERE / "results.json"
REPORT_PATH = HERE / "report.md"
ML_REPORT_PATH = HERE / "ml_report.json"

DISCLAIMER = (
    "SIMULATED costs are model-based assumptions from core/config.py (FP_*/FN_*), "
    "not real business impact. Metrics are from a real IEEE-CIS held-out test; "
    "synthetic-label numbers are NOT claims of production fraud performance."
)


def _costs() -> dict[str, float]:
    return {
        "fp_customer_friction": settings.FP_CUSTOMER_FRICTION_COST,
        "fp_lost_value_multiplier": settings.FP_LOST_TRANSACTION_VALUE_MULTIPLIER,
        "fp_support": settings.FP_SUPPORT_COST,
        "fp_merchant_impact": settings.FP_MERCHANT_IMPACT_COST,
        "fn_fraud_exposure_multiplier": settings.FN_FRAUD_EXPOSURE_MULTIPLIER,
    }


def _evaluate_at_threshold(y_true: np.ndarray, prob: np.ndarray, amount: np.ndarray, t: float) -> dict:
    pred = (prob >= t).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    fp_cost_unit = (
        settings.FP_CUSTOMER_FRICTION_COST
        + settings.FP_SUPPORT_COST
        + settings.FP_MERCHANT_IMPACT_COST
    )
    # SIMULATED costs using ACTUAL labels + amounts (not fabricated):
    fp_cost = float((amount[(pred == 1) & (y_true == 0)] * settings.FP_LOST_TRANSACTION_VALUE_MULTIPLIER).sum()) \
        + fp * fp_cost_unit
    # DENY blocks ~95% of fraud (decision_simulator assumption); allowed fraud = exposure
    fn_exposure = float((amount[(pred == 0) & (y_true == 1)] * settings.FN_FRAUD_EXPOSURE_MULTIPLIER).sum())
    tp_blocked_exposure_avoided = float(
        (amount[(pred == 1) & (y_true == 1)] * 0.95 * settings.FN_FRAUD_EXPOSURE_MULTIPLIER).sum()
    )
    return {
        "threshold": round(float(t), 4),
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "fpr": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        "fnr": round(fn / (fn + tp), 4) if (fn + tp) else 0.0,
        "simulated": {
            "fp_cost_inr": round(fp_cost, 2),
            "fraud_exposure_allowed_inr": round(fn_exposure, 2),
            "fraud_exposure_blocked_inr": round(tp_blocked_exposure_avoided, 2),
            "expected_total_cost_inr": round(fp_cost + fn_exposure - tp_blocked_exposure_avoided, 2),
        },
        "total_rows": int(tn + fp + fn + tp),
    }


def run(predictions_path: Path = DEFAULT_PREDICTIONS) -> dict:
    df = pd.read_parquet(predictions_path)
    for col in ("isFraud", "prob"):
        if col not in df.columns:
            raise ValueError(f"predictions are missing required column '{col}'")
    y_true = df["isFraud"].to_numpy().astype(int)
    prob = df["prob"].to_numpy().astype(float)
    # Older prediction files may lack amount — fall back to zeros (costs become SIMULATED-on-counts).
    amount = df["amount"].to_numpy().astype(float) if "amount" in df.columns else pd.Series([0.0] * len(df)).to_numpy()

    # AUCs are threshold-free
    pr_auc = float(average_precision_score(y_true, prob))
    roc_auc = float(roc_auc_score(y_true, prob))
    prec_curve, rec_curve, thr_curve = precision_recall_curve(y_true, prob)
    denom = np.maximum(prec_curve + rec_curve, 1e-12)
    f1_curve = np.where((prec_curve + rec_curve) > 0, 2 * prec_curve * rec_curve / denom, 0.0)
    best_idx = int(np.argmax(f1_curve[:-1]))
    best_t = float(thr_curve[best_idx])
    default_t = 0.5
    best = _evaluate_at_threshold(y_true, prob, amount, best_t)

    # SIMULATED min-cost threshold sweep (grid consistent with the UI threshold tool)
    grid = [round(t, 2) for t in np.arange(0.05, 1.001, 0.05)]
    sweep = [_evaluate_at_threshold(y_true, prob, amount, t) for t in grid]
    min_cost = min(sweep, key=lambda r: r["simulated"]["expected_total_cost_inr"])

    results = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "predictions_path": str(predictions_path),
        "dataset": {
            "source": "IEEE-CIS Fraud Detection (real transactions), temporal held-out test",
            "n_test": int(len(df)),
            "fraud_rate": round(float(y_true.mean()), 4),
        },
        "auc": {"pr_auc": round(pr_auc, 4), "roc_auc": round(roc_auc, 4)},
        "default_threshold_0_5": _evaluate_at_threshold(y_true, prob, amount, default_t),
        "best_f1_threshold": best,
        "simulated_cost_recommendation": {
            "min_cost_threshold": min_cost["threshold"],
            "min_expected_total_cost_inr": min_cost["simulated"]["expected_total_cost_inr"],
            "max_f1_threshold": best["threshold"],
            "max_f1": best["f1"],
            "note": (
                f"Chosen SIMULATED operating point (p={min_cost['threshold']}): blocks "
                f"{min_cost['tp']} of {min_cost['tp'] + min_cost['fn']} frauds at "
                f"{min_cost['fp']} false positives. With these SIMULATED cost weights, "
                "false-positive cost exceeds fraud exposure — threshold choice is a "
                "business decision; the tool surfaces the trade-off honestly."
            ),
        },
        "threshold_sweep": sweep,
        "cost_model": _costs(),
        "synthetic_demo_model": json.loads(ML_REPORT_PATH.read_text(encoding="utf-8")) if ML_REPORT_PATH.exists() else None,
        "disclaimer": DISCLAIMER,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    _write_report(results)
    return results


def _write_report(r: dict) -> None:
    d = r["default_threshold_0_5"]
    b = r["best_f1_threshold"]
    sim = r["simulated_cost_recommendation"]
    lines = [
        "# Evaluation Report — PayTrust AI",
        "",
        f"_Generated {r['generated_at']} by `python evaluation/run_evaluation.py` — all numbers computed from actual runs._",
        "",
        "## Held-out IEEE-CIS test (real data, temporal split)",
        "",
        f"- Test rows: **{r['dataset']['n_test']:,}** · fraud rate: **{r['dataset']['fraud_rate']:.1%}**",
        f"- **PR-AUC {r['auc']['pr_auc']}** · **ROC-AUC {r['auc']['roc_auc']}**",
        "",
        "| Metric | @ threshold 0.5 | @ best-F1 threshold |",
        "|---|---|---|",
        f"| Threshold | {d['threshold']} | {b['threshold']:.4f} |",
        f"| Precision | {d['precision']} | {b['precision']} |",
        f"| Recall | {d['recall']} | {b['recall']} |",
        f"| F1 | {d['f1']} | {b['f1']} |",
        f"| False Positive Rate | {d['fpr']} | {b['fpr']} |",
        f"| False Negative Rate | {d['fnr']} | {b['fnr']} |",
        f"| Confusion (TN,FP,FN,TP) | {d['tn']},{d['fp']},{d['fn']},{d['tp']} | {b['tn']},{b['fp']},{b['fn']},{b['tp']} |",
        "",
        "### SIMULATED cost trade-off (labeled assumptions — config FP_*/FN_*)",
        "",
        f"- Max F1: **{sim['max_f1']}** @ p≈{sim['max_f1_threshold']}",
        f"- Min SIMULATED expected total cost: **₹{sim['min_expected_total_cost_inr']:,.0f}** @ p={sim['min_cost_threshold']}",
        f"- {sim['note']}",
        "",
        "Full sweep: `evaluation/results.json` → `threshold_sweep`. Interactive: Streamlit **Evaluation & Thresholds** page or `GET /v1/threshold/curves`.",
        "",
        "## Synthetic demo model (NOT real-fraud performance)",
        "",
        "- Precision/recall 1.0 on the synthetic held-out test — kept only as a pipeline smoke test, explicitly disclaimed in `evaluation/ml_report.json`.",
        "",
        "---",
        "",
        f"**Disclaimer:** {DISCLAIMER}",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Reproduce PayTrust AI evaluation (spec: results.json + report.md)")
    ap.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS,
                    help="Parquet with columns isFraud, prob, amount")
    args = ap.parse_args()
    r = run(args.predictions)
    d = r["default_threshold_0_5"]
    print(f"[ok] n_test={r['dataset']['n_test']:,}  PR-AUC={r['auc']['pr_auc']}  "
          f"precision={d['precision']}  recall={d['recall']}  F1={d['f1']}  FPR={d['fpr']}")
    print(f"[ok] wrote {RESULTS_PATH} and {REPORT_PATH}")


if __name__ == "__main__":
    main()
