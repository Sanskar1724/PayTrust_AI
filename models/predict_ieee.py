"""
models/predict_ieee.py — Generate submission.csv for test (506k) using trained IEEE model, chunked.

Also maps IEEE transaction to PayTrust PaymentRequest for real-world demo.

Usage:
  python -m models.predict_ieee --model models/ieee_model.pkl --test data/required\ csv/ieee-fraud-detection/test_transaction.csv --out evaluation/submission.csv
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path
import pandas as pd
import numpy as np

# Reuse feature engineering from train_ieee_chunked
from models.train_ieee_chunked import _engineer_chunk, _load_identity_index, _select_features

TEST_TRANS = Path("data/required csv/ieee-fraud-detection/test_transaction.csv")
TEST_ID = Path("data/required csv/ieee-fraud-detection/test_identity.csv")

def predict_test(model_path: Path, test_trans: Path, test_id: Path, out_path: Path, chunksize: int = 50000):
    # Load model bundle
    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    scaler = bundle["scaler"]
    model = bundle["model"]
    features = bundle["features"]
    print(f"Loaded model {model_path} features {len(features)}")

    # Load identity index for test
    if test_id.exists():
        id_df = pd.read_csv(test_id)
        id_index = id_df.set_index("TransactionID")
        print(f"Test identity {id_index.shape}")
    else:
        id_index = pd.DataFrame()

    # Process test_transaction in chunks, predict, write submission incrementally
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Write header
    with open(out_path, "w", newline="") as out_f:
        out_f.write("TransactionID,isFraud\n")

    total = 0
    reader = pd.read_csv(test_trans, chunksize=chunksize)
    for idx, chunk in enumerate(reader, 1):
        print(f"Predicting chunk {idx} shape {chunk.shape} ...")
        # Engineer (without label)
        df = _engineer_chunk(chunk, id_index)
        # One-hot (must match training dummy cols)
        for col in ["ProductCD","P_emaildomain_freq","R_emaildomain_freq","DeviceType","card4","card6"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
        df = pd.get_dummies(df, columns=[c for c in ["ProductCD","P_emaildomain_freq","R_emaildomain_freq","DeviceType","card4","card6"] if c in df.columns], drop_first=False, dummy_na=False)
        for col in df.select_dtypes(include=['object']).columns:
            # Drop non-feature object cols (like id_*, DeviceInfo)
            if col not in features and not col.startswith("TransactionID"):
                df[col] = df[col].astype(str)
        # Align to training features: add missing cols as 0, drop extra
        for c in features:
            if c not in df.columns:
                df[c] = 0
        X = df[features].apply(pd.to_numeric, errors='coerce').fillna(0)
        # Ensure numeric
        X = X.select_dtypes(include=[np.number])
        # If still mismatch, re-align
        # Predict
        Xs = scaler.transform(X)
        prob = model.predict_proba(Xs)[:,1]
        # Write to submission
        out_chunk = pd.DataFrame({"TransactionID": chunk["TransactionID"], "isFraud": prob})
        out_chunk.to_csv(out_path, mode="a", header=False, index=False)
        total += len(chunk)
        print(f"Chunk {idx} predicted {len(chunk)} total {total} mean_prob {prob.mean():.4f}")

    print(f"Done. Submission {out_path} total {total}")

def ieee_to_paytrust(ieee_row: dict) -> dict:
    """
    Map IEEE transaction to PayTrust PaymentRequest.
    Real money mapping: TransactionAmt (USD) -> INR (x83), ProductCD -> category
    """
    prod_map = {"W":"electronics","C":"books","R":"fashion","H":"travel","S":"food"}
    amt_usd = float(ieee_row.get("TransactionAmt", 0))
    amt_inr = int(amt_usd * 83)  # USD to INR approx
    amt_inr = max(500, min(amt_inr, 200000))
    prod = str(ieee_row.get("ProductCD", "W"))
    cat = prod_map.get(prod, "electronics")
    # card1 as user (hash to 1-3)
    card1 = int(ieee_row.get("card1", 13926))
    user_id = (card1 % 3) + 1
    # addr1 as region
    addr = str(ieee_row.get("addr1", "315"))
    region_map = {"315":"Mumbai","325":"Delhi","330":"Bangalore","480":"Chennai"}
    region = region_map.get(addr, "Mumbai")
    return {
        "request_id": f"req_ieee_{ieee_row.get('TransactionID')}",
        "user_id": user_id,
        "agent_id": 1,
        "merchant_id": 1 if cat=="electronics" else 2 if cat=="books" else 3,
        "merchant_name": "TechMart Electronics" if cat=="electronics" else "BookHaven" if cat=="books" else "TravelEase",
        "amount": amt_inr,
        "currency": "INR",
        "category": cat,
        "description": f"IEEE {ieee_row.get('TransactionID')} Product {prod}",
        "agent_reason": f"IEEE fraud model: TransactionDT {ieee_row.get('TransactionDT')}, card {card1}",
        "region": region,
        "ieee_prob": None,  # to be filled after prediction
    }

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", type=str, default="models/ieee_model.pkl")
    p.add_argument("--test", type=str, default=str(TEST_TRANS))
    p.add_argument("--test-id", type=str, default=str(TEST_ID))
    p.add_argument("--out", type=str, default="evaluation/submission.csv")
    p.add_argument("--chunksize", type=int, default=50000)
    p.add_argument("--demo-map", type=int, default=0, help="if set, map first N rows to PayTrust and print")
    args = p.parse_args()
    if args.demo_map:
        # Demo mapping without model
        df = pd.read_csv(args.test, nrows=args.demo_map)
        for _, row in df.iterrows():
            print(ieee_to_paytrust(row.to_dict()))
    else:
        predict_test(Path(args.model), Path(args.test), Path(args.test_id), Path(args.out), chunksize=args.chunksize)
