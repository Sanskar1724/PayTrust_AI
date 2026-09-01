"""tests/test_threshold.py — Threshold Decision Tool over real IEEE held-out test predictions.

Covers: loading predictions, metrics correctness at known thresholds,
sweep coverage, cost-model sanity, operating-point helper.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import models.threshold as thr


@pytest.fixture(scope="module")
def preds() -> pd.DataFrame:
    p = Path(__file__).resolve().parents[1] / "evaluation" / "ieee_test_predictions.parquet"
    if not p.exists():
        pytest.skip("ieee_test_predictions.parquet not present — run: python -m models.train_ieee_chunked --train-only")
    return thr.load_test_predictions(p)


def _tiny_df() -> pd.DataFrame:
    # 10 rows: 3 fraud (prob .99/.96/.9), 7 legit (prob .1,.2,.3,.4,.5,.6,.7)
    return pd.DataFrame({
        "prob": [0.99, 0.96, 0.90, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70],
        "isFraud": [1, 1, 1, 0, 0, 0, 0, 0, 0, 0],
        "amount": [1000.0, 900.0, 800.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0],
    })


def test_load_predictions_has_expected_cols(preds):
    assert {"prob", "isFraud"}.issubset(preds.columns)
    assert len(preds) > 1000


def test_metrics_at_threshold_zero_everything_is_fraud():
    df = _tiny_df()
    m = thr.metrics_at(0.0, df)
    assert m["tp"] == 3 and m["fp"] == 7
    assert m["precision"] == pytest.approx(3 / 10)
    assert m["recall"] == 1.0
    assert m["false_positive_rate"] == 1.0


def test_metrics_at_high_threshold_only_high_prob():
    df = _tiny_df()
    m = thr.metrics_at(0.95, df)
    assert m["tp"] == 2 and m["fp"] == 0
    assert m["tn"] == 7 and m["fn"] == 1
    assert m["precision"] == 1.0
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["false_positive_rate"] == 0.0


def test_metrics_at_invalid_threshold_raises():
    with pytest.raises(ValueError):
        thr.metrics_at(1.5)


def test_sweep_covers_thresholds():
    df = _tiny_df()
    res = thr.sweep(step=0.1, df=df)
    # 0.0 ... 1.0 step 0.1 → 11 points
    assert len(res) == 11
    assert res[0]["threshold"] == 0.0
    assert res[-1]["threshold"] == 1.0


def test_cost_model_never_negative():
    df = _tiny_df()
    for t in [0.0, 0.5, 0.95, 1.0]:
        m = thr.metrics_at(t, df)
        assert m["fraud_exposure"] >= 0
        assert m["false_positive_cost"] >= 0
        assert m["expected_total_cost"] >= 0
        assert "SIMULATED" in m["disclaimer"]


def test_to_curves_returns_chartable_arrays():
    df = _tiny_df()
    curves = thr.to_curves(thr.sweep(step=0.1, df=df))
    assert len(curves["threshold"]) == 11
    assert len(curves["precision"]) == 11
    assert len(curves["recall"]) == 11
    assert len(curves["expected_total_cost"]) == 11


def test_best_operating_point_returns_both_hints():
    df = _tiny_df()
    b = thr.best_operating_point(df=df)
    assert b["max_f1"]["f1"] >= 0
    assert b["min_expected_total_cost"]["expected_total_cost"] >= 0
    assert "disclaimer" in b