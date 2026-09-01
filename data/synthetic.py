"""
data/synthetic.py — Phase 8 Synthetic Data Engine.

Reproducible generator (seeded) for:
  - normal transactions
  - high-value
  - unusual spending / amount 4x
  - new merchant
  - repeated payments (velocity)
  - blocked categories
  - policy violations (max exceeded, daily limit)
  - unusual timing (1-5 AM)
  - agent auth violations (inactive agent)
  - suspicious combos (mixed signals)

No real customer data. CSV at data/synthetic_transactions.csv
"""
from __future__ import annotations

import random
import csv
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

# Seeded merchants/users for reproducibility
MERCHANTS = [
    (1, "TechMart Electronics", "electronics"),
    (2, "BookHaven", "books"),
    (3, "TravelEase", "travel"),
    (4, "BetZone", "gambling"),
    (5, "FinServe", "financial_products"),
    (6, "FoodieDelight", "food"),
]
USERS = [(1, "Test User", "test@paytrust.ai"), (2, "Alice", "alice@paytrust.ai"), (3, "Bob", "bob@paytrust.ai")]
AGENTS = [(1, "Shopping Assistant"), (2, "Travel Bot"), (99, "Inactive Agent")]

CATEGORIES = ["electronics","books","travel","food","fashion","grocery","fuel","gambling","financial_products"]

def _amount_log_normal(rng: random.Random, mean=8.5, sigma=0.8) -> int:
    # Use Box-Muller via random.gauss to avoid numpy dependency for determinism
    v = rng.gauss(mean, sigma)
    import math
    amt = int(math.exp(v) * 100)  # paise-like then INR
    return max(500, min(amt, 200000))

def generate_rows(n_normal: int = 500, n_anomalies: int = 50, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    base = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    rows: list[dict[str, Any]] = []
    counter = 0
    def new_id(prefix="req"):
        nonlocal counter
        counter += 1
        return f"{prefix}_{seed}_{counter:05d}_{rng.randint(100,999)}"

    # Normal
    for _ in range(n_normal):
        uid, _, _ = rng.choice(USERS[:2])  # not inactive
        aid = 1
        mid, mname, mcat = rng.choice(MERCHANTS[:3])  # allowlisted
        amt = _amount_log_normal(rng)
        # Clamp to policy max for normal
        amt = min(amt, 55000)
        cat = mcat
        ts = base + timedelta(days=rng.randint(0,20), hours=rng.randint(9,20), minutes=rng.randint(0,59))
        rows.append({
            "request_id": new_id("req"),
            "user_id": uid, "agent_id": aid, "merchant_id": mid, "merchant_name": mname,
            "amount": amt, "currency": "INR", "category": cat,
            "description": "Normal purchase", "agent_reason": "User requested", "timestamp": ts.isoformat().replace("+00:00","Z"),
            "label": "normal", "scenario": "normal"
        })

    # High-value (>60k max)
    for _ in range(n_anomalies // 5):
        uid = 1; aid = 1; mid,mname,mcat = rng.choice(MERCHANTS[:3])
        amt = rng.randint(65000, 120000)
        ts = base + timedelta(days=rng.randint(0,20), hours=rng.randint(10,18))
        rows.append({"request_id": new_id("req"), "user_id": uid, "agent_id": aid, "merchant_id": mid, "merchant_name": mname, "amount": amt, "currency": "INR", "category": mcat, "description": "High-value", "agent_reason": "High-value flagged", "timestamp": ts.isoformat().replace("+00:00","Z"), "label": "anomaly", "scenario": "high_value"})

    # Blocked category
    for _ in range(n_anomalies // 5):
        uid = 1; aid = 1; mid,mname,mcat = rng.choice([(4,"BetZone","gambling"),(5,"FinServe","financial_products")])
        amt = rng.randint(5000, 30000)
        ts = base + timedelta(days=rng.randint(0,20), hours=rng.randint(10,18))
        rows.append({"request_id": new_id("req"), "user_id": uid, "agent_id": aid, "merchant_id": mid, "merchant_name": mname, "amount": amt, "currency": "INR", "category": mcat, "description": "Blocked category", "agent_reason": "Blocked", "timestamp": ts.isoformat().replace("+00:00","Z"), "label": "anomaly", "scenario": "blocked_category"})

    # New merchant (unseen)
    for _ in range(n_anomalies // 5):
        uid = 1; aid = 1; mid=99; mname="NewMerchant_Unseen"
        amt = rng.randint(20000, 50000)
        cat = rng.choice(["electronics","books"])
        ts = base + timedelta(days=rng.randint(0,20))
        rows.append({"request_id": new_id("req"), "user_id": uid, "agent_id": aid, "merchant_id": mid, "merchant_name": mname, "amount": amt, "currency": "INR", "category": cat, "description": "New merchant", "agent_reason": "New merchant", "timestamp": ts.isoformat().replace("+00:00","Z"), "label": "anomaly", "scenario": "new_merchant"})

    # Unusual timing 1-5 AM + velocity burst
    for _ in range(n_anomalies // 5):
        uid = 1; aid = 1; mid,mname,mcat = rng.choice(MERCHANTS[:3])
        base_burst = base.replace(hour=2, minute=0) + timedelta(days=rng.randint(0,20))
        for j in range(rng.randint(3,6)):
            amt = _amount_log_normal(rng)
            ts = base_burst + timedelta(minutes=j*7)
            rows.append({"request_id": new_id("req"), "user_id": uid, "agent_id": aid, "merchant_id": mid, "merchant_name": mname, "amount": amt, "currency": "INR", "category": mcat, "description": "Unusual timing / velocity", "agent_reason": "Burst", "timestamp": ts.isoformat().replace("+00:00","Z"), "label": "anomaly", "scenario": "unusual_timing_velocity"})

    # Auth violation + mixed
    for _ in range(n_anomalies // 5):
        uid = 1; aid = 99  # inactive agent
        mid,mname,mcat = rng.choice(MERCHANTS[:3])
        amt = rng.randint(40000, 70000)
        cat = "electronics"
        ts = base + timedelta(days=rng.randint(0,20), hours=2)
        rows.append({"request_id": new_id("req"), "user_id": uid, "agent_id": aid, "merchant_id": mid, "merchant_name": mname, "amount": amt, "currency": "INR", "category": cat, "description": "Auth violation mixed", "agent_reason": "Inactive agent high amount at night", "timestamp": ts.isoformat().replace("+00:00","Z"), "label": "anomaly", "scenario": "auth_violation_mixed"})

    # Daily limit: many tx same day for same user to exceed 100k
    daily_user = 2
    daily_base = base + timedelta(days=5)
    for k in range(6):
        amt = 25000
        mid,mname,mcat = MERCHANTS[0]
        ts = daily_base + timedelta(hours=k)
        rows.append({"request_id": new_id("req"), "user_id": daily_user, "agent_id": 1, "merchant_id": mid, "merchant_name": mname, "amount": amt, "currency": "INR", "category": mcat, "description": "Daily limit burst", "agent_reason": "Daily limit test", "timestamp": ts.isoformat().replace("+00:00","Z"), "label": "anomaly" if k>=4 else "normal", "scenario": "daily_limit"})

    rng.shuffle(rows)
    return rows

def generate_synthetic_csv(n_normal: int = 500, n_anomalies: int = 50, seed: int = 42, path: str | Path | None = None) -> tuple[Path, int]:
    rows = generate_rows(n_normal=n_normal, n_anomalies=n_anomalies, seed=seed)
    out = Path(path) if path else Path(__file__).resolve().parent / "synthetic_transactions.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Use pandas for reliable CSV
    df = pd.DataFrame(rows)
    # Ensure deterministic column order
    cols = ["request_id","user_id","agent_id","merchant_id","merchant_name","amount","currency","category","description","agent_reason","timestamp","label","scenario"]
    df = df[cols]
    df.to_csv(out, index=False)
    return out, len(df)

def verify_distributions(path: Path | str) -> dict:
    df = pd.read_csv(path)
    return {
        "total": len(df),
        "by_label": df["label"].value_counts().to_dict(),
        "by_scenario": df["scenario"].value_counts().to_dict(),
        "avg_amount": float(df["amount"].mean()),
        "max_amount": int(df["amount"].max()),
        "currencies": df["currency"].unique().tolist(),
    }

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--normal", type=int, default=500)
    p.add_argument("--anomalies", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()
    out, n = generate_synthetic_csv(n_normal=args.normal, n_anomalies=args.anomalies, seed=args.seed, path=args.out)
    print(f"Generated {n} rows -> {out}")
    print(verify_distributions(out))
