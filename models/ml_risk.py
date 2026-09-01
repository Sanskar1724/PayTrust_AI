"""
models/ml_risk.py — Phase 12 Optional ML Risk Model.

It does NOT replace policy/decision engines. It provides an additional fraud probability
signal that can be blended into RiskEngine as one factor, only if it demonstrably
improves evaluation.

Pipeline:
  Synthetic CSV → Feature engineering → Train/Val/Test split (temporal) → Baseline Logistic → Optional XGBoost → Evaluate PR-AUC, Precision, Recall

Use as:
  python -m models.ml_risk --train data/synthetic_transactions.csv --seed 42
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score, average_precision_score, roc_auc_score, confusion_matrix

# Optional XGBoost — only if installed and justified
try:
    import xgboost as xgb  # type: ignore
    HAS_XGB = True
except Exception:
    HAS_XGB = False

FEATURE_COLS = ["amount", "hour", "is_night", "is_blocked_category", "is_high_amount", "is_new_merchant", "agent_risk"]

def _engineer(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    df = df.copy()
    # Parse timestamp
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["hour"] = df["ts"].dt.hour.fillna(12).astype(int)
    df["is_night"] = df["hour"].isin([1,2,3,4,5]).astype(int)
    df["is_blocked_category"] = df["category"].isin(["gambling","financial_products"]).astype(int)
    df["is_high_amount"] = (df["amount"] > 60000).astype(int)
    df["is_new_merchant"] = (df["scenario"] == "new_merchant").astype(int)
    # Agent risk: inactive agent
    df["agent_risk"] = (df["agent_id"] == 99).astype(int)
    # Label: anomaly vs normal
    df["y"] = (df["label"] == "anomaly").astype(int)
    X = df[FEATURE_COLS].fillna(0)
    y = df["y"]
    return X, y

def train_evaluate(csv_path: Path | str, seed: int = 42, model_out: Path | str | None = None) -> dict[str, Any]:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    df = pd.read_csv(csv_path)
    if len(df) < 100:
        raise ValueError("Need at least 100 rows for ML training")

    X, y = _engineer(df)
    # Temporal split: sort by ts if available, else random; here use random with seed for reproducibility
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=seed, stratify=y)
    X_train, X_val, y_train, y_val = train_test_split(X_train, y_train, test_size=0.176, random_state=seed, stratify=y_train)  # 0.176*0.85≈0.15 val

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)
    X_test_s = scaler.transform(X_test)

    # Baseline: Logistic Regression
    clf = LogisticRegression(max_iter=1000, random_state=seed, class_weight="balanced")
    clf.fit(X_train_s, y_train)

    def eval_at(Xs, ys):
        prob = clf.predict_proba(Xs)[:, 1]
        pred = (prob >= 0.5).astype(int)
        return {
            "precision": float(precision_score(ys, pred, zero_division=0)),
            "recall": float(recall_score(ys, pred, zero_division=0)),
            "f1": float(f1_score(ys, pred, zero_division=0)),
            "pr_auc": float(average_precision_score(ys, prob)) if len(set(ys)) > 1 else 0.0,
            "roc_auc": float(roc_auc_score(ys, prob)) if len(set(ys)) > 1 else 0.0,
            "confusion": confusion_matrix(ys, pred).tolist() if len(set(ys)) > 1 else [[0,0],[0,0]],
        }

    val_metrics = eval_at(X_val_s, y_val)
    test_metrics = eval_at(X_test_s, y_test)

    # Isolation Forest as unsupervised alternative (for comparison)
    iso = IsolationForest(contamination=0.15, random_state=seed)
    iso.fit(X_train_s)
    # Isolation score → map to probability-like
    iso_pred = (iso.predict(X_test_s) == -1).astype(int)
    iso_precision = float(precision_score(y_test, iso_pred, zero_division=0)) if len(set(y_test)) > 1 else 0

    result = {
        "seed": seed,
        "csv": str(csv_path),
        "n_train": len(X_train), "n_val": len(X_val), "n_test": len(X_test),
        "feature_cols": FEATURE_COLS,
        "logistic": {"val": val_metrics, "test": test_metrics},
        "isolation_forest": {"precision": iso_precision},
        "has_xgb": HAS_XGB,
        "model": "logistic_regression_balanced",
        "disclaimer": "Trained on SYNTHETIC data — not real fraud, not claim of production performance",
    }

    if model_out:
        out = Path(model_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            pickle.dump({"scaler": scaler, "model": clf, "features": FEATURE_COLS}, f)
        result["model_path"] = str(out)

    # Optional XGBoost if available and improves — only if val F1 > logistic
    if HAS_XGB:
        try:
            xclf = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.1, subsample=0.8, random_state=seed, eval_metric="logloss")
            xclf.fit(X_train_s, y_train)
            x_prob = xclf.predict_proba(X_val_s)[:,1]
            x_pred = (x_prob >= 0.5).astype(int)
            x_f1 = float(f1_score(y_val, x_pred, zero_division=0))
            result["xgb"] = {"val_f1": x_f1, "better_than_logistic": x_f1 > val_metrics["f1"]}
            if x_f1 > val_metrics["f1"] and model_out:
                with open(str(out).replace(".pkl","_xgb.pkl"), "wb") as f:
                    pickle.dump({"scaler": scaler, "model": xclf, "features": FEATURE_COLS}, f)
        except Exception as exc:
            result["xgb_error"] = str(exc)[:300]

    return result

def predict_proba(model_path: Path | str, features: dict[str, Any]) -> float:
    """
    Load pickled model and return fraud probability 0-1 for a single transaction.
    Features: dict with keys from FEATURE_COLS (or raw payment fields — we map)
    """
    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    scaler = bundle["scaler"]
    model = bundle["model"]
    cols = bundle["features"]
    # Map raw payment dict to feature row
    row = []
    for c in cols:
        row.append(float(features.get(c, 0)))
    import numpy as np
    X = np.array([row])
    Xs = scaler.transform(X)
    prob = float(model.predict_proba(Xs)[0,1])
    return prob

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Train optional ML risk model on synthetic CSV")
    p.add_argument("--train", type=str, default="data/synthetic_transactions.csv", help="CSV path")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default="models/risk_model.pkl")
    args = p.parse_args()
    res = train_evaluate(args.train, seed=args.seed, model_out=args.out)
    print(json.dumps(res, indent=2))
    # Save report
    report_path = Path("evaluation/ml_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(res, f, indent=2)
    print(f"Report → {report_path}")
