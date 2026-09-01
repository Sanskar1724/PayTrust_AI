"""
tests/test_synthetic.py — Phase 8 synthetic data verification.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import pandas as pd

from data.synthetic import generate_rows, generate_synthetic_csv, verify_distributions

def test_generate_rows_seed_reproducible():
    rows1 = generate_rows(n_normal=100, n_anomalies=10, seed=123)
    rows2 = generate_rows(n_normal=100, n_anomalies=10, seed=123)
    assert rows1 == rows2
    rows3 = generate_rows(n_normal=100, n_anomalies=10, seed=999)
    assert rows1 != rows3

def test_generate_rows_expected_scenarios():
    rows = generate_rows(n_normal=200, n_anomalies=50, seed=42)
    scenarios = {r["scenario"] for r in rows}
    assert "normal" in scenarios
    assert "high_value" in scenarios
    assert "blocked_category" in scenarios
    assert "new_merchant" in scenarios
    assert "unusual_timing_velocity" in scenarios
    assert "auth_violation_mixed" in scenarios

def test_csv_created_and_readable():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "syn.csv"
        path, n = generate_synthetic_csv(n_normal=100, n_anomalies=20, seed=42, path=out)
        assert path.exists()
        df = pd.read_csv(path)
        assert len(df) == n
        expected_cols = ["request_id","user_id","agent_id","merchant_id","merchant_name","amount","currency","category","description","agent_reason","timestamp","label","scenario"]
        assert list(df.columns) == expected_cols
        assert set(df["currency"].unique()) == {"INR"}

def test_distributions_reasonable():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "syn.csv"
        generate_synthetic_csv(n_normal=200, n_anomalies=40, seed=7, path=out)
        stats = verify_distributions(out)
        # Burst + daily are variable (3-6 per burst), so total is not fixed — check range
        assert 240 <= stats["total"] <= 300
        assert stats["total"] == stats["by_label"].get("normal",0) + stats["by_label"].get("anomaly",0)
        assert "normal" in stats["by_label"]
        assert "anomaly" in stats["by_label"]
        assert stats["avg_amount"] > 5000
        assert stats["max_amount"] > 60000  # high-value
        # Gambling should appear in blocked_category
        df = pd.read_csv(out)
        assert "gambling" in df["category"].values

def test_no_real_pii():
    rows = generate_rows(n_normal=10, n_anomalies=5, seed=42)
    for r in rows:
        assert "sk-" not in str(r.values())
        assert r["currency"] == "INR"
        assert r["amount"] >= 500

def test_csv_overwrites_deterministically():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "syn.csv"
        generate_synthetic_csv(n_normal=50, n_anomalies=10, seed=1, path=out)
        content1 = out.read_text()
        generate_synthetic_csv(n_normal=50, n_anomalies=10, seed=1, path=out)
        content2 = out.read_text()
        assert content1 == content2
