"""
models/train_ieee_chunked.py — Chunked IEEE Fraud Detection training (no direct full load).

Handles 590k x 394 cols via chunks. Extracts max features but split:

- Reads train_transaction.csv in chunks (50k)
- Left-joins train_identity.csv (indexed) per chunk
- Feature engineering:
  * Transaction: amt_log, amt_zscore, ProductCD, card1-6, addr1/2, dist1/2, P/R email (freq), C1-14, D1-15, M1-9, V1-339 aggregated
  * Identity: id_01-38, DeviceType, DeviceInfo (freq), TransactionDT hour/day
  * Engineered: hour, is_night, is_weekend, amt_per_card, card1_count, dist flag, email_risk, V_missing, V_sum, identity_present

Saves processed parquet chunks to data/processed/, then trains LogisticRegression + LightGBM (if available) on sampled data,
evaluates on held-out 15% (temporal), saves metrics + feature importance.

Usage:
  python -m models.train_ieee_chunked --nrows 50000 --chunksize 50000 --seed 42
  python -m models.train_ieee_chunked --full  # use all 590k in chunks (slower)

UI will read evaluation/ieee_report.json and models/ieee_model.pkl
"""
from __future__ import annotations

import argparse
import json
import pickle
import gc
from pathlib import Path
from typing import List

import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, f1_score, average_precision_score, roc_auc_score, confusion_matrix
from sklearn.model_selection import train_test_split

try:
    import lightgbm as lgb  # type: ignore
    HAS_LGB = True
except Exception:
    HAS_LGB = False

TRAIN_TRANS = Path("data/required csv/ieee-fraud-detection/train_transaction.csv")
TRAIN_ID = Path("data/required csv/ieee-fraud-detection/train_identity.csv")
PROCESSED_DIR = Path("data/processed")
MODEL_PATH = Path("models/ieee_model.pkl")
REPORT_PATH = Path("evaluation/ieee_report.json")

# --- Feature lists (max but manageable) ---
C_COLS = [f"C{i}" for i in range(1,15)]
D_COLS = [f"D{i}" for i in range(1,16)]
M_COLS = [f"M{i}" for i in range(1,10)]
V_COLS = [f"V{i}" for i in range(1, 51)]  # first 50 V's are densest; rest are sparse but we aggregate
ID_COLS = [f"id_{i:02d}" for i in range(1,39)]
CARD_COLS = ["card1","card2","card3","card5","card6"]
ADDR_COLS = ["addr1","addr2","dist1","dist2"]

def _load_identity_index() -> pd.DataFrame:
    if not TRAIN_ID.exists():
        return pd.DataFrame()
    print(f"Loading identity {TRAIN_ID} ...")
    df = pd.read_csv(TRAIN_ID)
    df = df.set_index("TransactionID")
    print(f"Identity shape {df.shape}, cols {len(df.columns)}")
    return df

def _engineer_chunk(df: pd.DataFrame, id_index: pd.DataFrame) -> pd.DataFrame:
    # Merge identity (left join)
    if not id_index.empty and "TransactionID" in df.columns:
        df = df.set_index("TransactionID")
        # Join only for IDs present to avoid exploding
        df = df.join(id_index, how="left", rsuffix="_id")
        df = df.reset_index()
    # Basic
    df["TransactionAmt_log"] = np.log1p(df["TransactionAmt"].clip(lower=0))
    df["TransactionAmt_zscore"] = (df["TransactionAmt"] - df["TransactionAmt"].mean()) / (df["TransactionAmt"].std() + 1e-6)
    # Time
    # TransactionDT is seconds from reference; convert to hour/day
    df["hour"] = (df["TransactionDT"] // 3600) % 24
    df["day"] = (df["TransactionDT"] // (3600*24)) % 7
    df["is_night"] = df["hour"].isin([1,2,3,4,5]).astype(int)
    df["is_weekend"] = df["day"].isin([5,6]).astype(int)
    # Product
    df["ProductCD"] = df["ProductCD"].fillna("Missing")
    # Card: card1,2,3,5 are numeric; card4,6 are categorical (visa/mastercard, credit/debit)
    for c in ["card1","card2","card3","card5"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(-1)
    for c in ["card4","card6"]:
        if c in df.columns:
            df[c] = df[c].astype(str).replace("nan", "Missing").fillna("Missing")
    # Addr/dist
    for c in ADDR_COLS:
        if c in df.columns:
            df[c] = df[c].fillna(-1)
    # Email
    for c in ["P_emaildomain","R_emaildomain"]:
        if c in df.columns:
            df[c] = df[c].fillna("Missing")
            # Frequency encode top domains, else Other
            top = df[c].value_counts().head(5).index
            df[c + "_freq"] = df[c].where(df[c].isin(top), "Other")
    # C cols - fill with median per chunk, clip
    for c in C_COLS:
        if c in df.columns:
            df[c] = df[c].fillna(df[c].median())
            df[c] = df[c].clip(-10, 50)
    # D cols - time delta, fill -1
    for c in D_COLS:
        if c in df.columns:
            df[c] = df[c].fillna(-1)
    # M cols - binary T/F/NaN
    for c in M_COLS:
        if c in df.columns:
            df[c] = df[c].map({"T":1,"F":0}).fillna(-1).astype(int)
    # V cols - aggregate: sum, mean, missing count, plus first 10 individually
    v_present = [c for c in V_COLS if c in df.columns]
    if v_present:
        df["V_sum"] = df[v_present].sum(axis=1, skipna=True)
        df["V_mean"] = df[v_present].mean(axis=1, skipna=True)
        df["V_missing"] = df[v_present].isna().sum(axis=1)
        # Fill first 10 V for model
        for c in V_COLS[:10]:
            if c in df.columns:
                df[c] = df[c].fillna(0)
    # Identity
    if "DeviceType" in df.columns:
        df["DeviceType"] = df["DeviceType"].fillna("Missing")
    if "DeviceInfo" in df.columns:
        df["DeviceInfo"] = df["DeviceInfo"].fillna("Missing")
        # Simplify: browser vs device
        df["DeviceInfo_simple"] = df["DeviceInfo"].str.split().str[0].fillna("Missing")
    # Engineered: amt per card, card count
    df["card1_count"] = df.groupby("card1")["card1"].transform("count") if "card1" in df.columns else 0
    df["amt_per_card_mean"] = df["TransactionAmt"] / (df["card1_count"].clip(lower=1))
    # Identity present flag
    df["has_identity"] = (~df["id_01"].isna()).astype(int) if "id_01" in df.columns else 0
    return df

def _select_features(df: pd.DataFrame) -> List[str]:
    # Choose max features that exist after engineering, excluding raw high-cardinality
    base = ["TransactionAmt","TransactionAmt_log","TransactionAmt_zscore","hour","day","is_night","is_weekend",
            "card1","card2","card3","card5","card6","addr1","addr2","dist1","dist2",
            "V_sum","V_mean","V_missing","card1_count","amt_per_card_mean","has_identity"]
    base += [c for c in C_COLS if c in df.columns]
    base += [c for c in D_COLS if c in df.columns]
    base += [c for c in M_COLS if c in df.columns]
    base += [c for c in V_COLS[:10] if c in df.columns]
    # One-hot will be done via get_dummies for ProductCD, P/R freq, DeviceType
    return [c for c in base if c in df.columns]

def process_and_save(nrows: int | None = None, chunksize: int = 50000, seed: int = 42):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    # Clear old parquet and pkl
    for p in list(PROCESSED_DIR.glob("chunk_*.parquet")) + list(PROCESSED_DIR.glob("chunk_*.pkl")):
        p.unlink(missing_ok=True)
    id_index = _load_identity_index()
    total = 0
    chunk_idx = 0
    reader = pd.read_csv(TRAIN_TRANS, chunksize=chunksize, nrows=nrows)
    for chunk in reader:
        chunk_idx += 1
        print(f"Processing chunk {chunk_idx} shape {chunk.shape} ...")
        df = _engineer_chunk(chunk, id_index)
        # One-hot for ProductCD, P/R freq, DeviceType (top 5) — ensure string dtype
        for col in ["ProductCD","P_emaildomain_freq","R_emaildomain_freq","DeviceType","card4","card6"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
        df = pd.get_dummies(df, columns=[c for c in ["ProductCD","P_emaildomain_freq","R_emaildomain_freq","DeviceType","card4","card6"] if c in df.columns], drop_first=False, dummy_na=False)
        # Convert any remaining object cols to string to avoid pyarrow mixed-type error
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str)
        out = PROCESSED_DIR / f"chunk_{chunk_idx:03d}.parquet"
        try:
            df.to_parquet(out, index=False)
        except Exception as e:
            # Fallback to pickle if parquet fails (mixed types)
            print(f"Parquet failed {e}, falling back to pickle")
            out = PROCESSED_DIR / f"chunk_{chunk_idx:03d}.pkl"
            df.to_pickle(out)
        total += len(df)
        print(f"Saved {out} rows {len(df)} total {total}")
        del df
        gc.collect()
        if nrows and total >= nrows:
            break
    print(f"Done. Total rows processed {total}, chunks {chunk_idx}")
    return total, chunk_idx

def train_from_processed(seed: int = 42):
    files = sorted(list(PROCESSED_DIR.glob("chunk_*.parquet")) + list(PROCESSED_DIR.glob("chunk_*.pkl")))
    if not files:
        raise FileNotFoundError("No processed chunks found — run process_and_save first")
    print(f"Loading {len(files)} chunks for training ...")
    dfs = []
    for f in files:
        if f.suffix == ".parquet":
            dfs.append(pd.read_parquet(f))
        else:
            dfs.append(pd.read_pickle(f))
    df = pd.concat(dfs, ignore_index=True)
    print(f"Concat shape {df.shape}")
    # Select features
    feature_cols = _select_features(df)
    # Add dummy cols that may be present after get_dummies
    dummy_cols = [c for c in df.columns if c.startswith("ProductCD_") or c.startswith("P_emaildomain") or c.startswith("DeviceType_") or c.startswith("card4_") or c.startswith("card6_")]
    feature_cols += dummy_cols
    feature_cols = list(dict.fromkeys(feature_cols))  # dedup
    # Filter to only columns that are numeric or dummy (exclude any remaining object with strings like 'Missing')
    numeric_cols = []
    for c in feature_cols:
        if c in df.columns:
            # Check if dtype is numeric or if all values can be coerced
            if pd.api.types.is_numeric_dtype(df[c]):
                numeric_cols.append(c)
            else:
                # Try to coerce, if fails, skip this column (likely still object with 'Missing')
                try:
                    pd.to_numeric(df[c].head(100), errors='raise')
                    numeric_cols.append(c)
                except Exception:
                    print(f"Skipping non-numeric feature {c} dtype {df[c].dtype}")
                    continue
    feature_cols = numeric_cols
    # Ensure label exists
    if "isFraud" not in df.columns:
        raise ValueError("isFraud missing")
    # Drop rows where label missing (should not)
    df = df.dropna(subset=["isFraud"]).reset_index(drop=True)
    X = df[feature_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
    y = df["isFraud"].astype(int)
    print(f"Features {len(feature_cols)}: {feature_cols[:10]}...")
    print(f"Fraud rate {y.mean():.4f}")
    # Temporal split: TransactionDT already in df, sort by it if present
    if "TransactionDT" in df.columns:
        df_sorted_idx = df["TransactionDT"].argsort()
        # Use last 15% as test (temporal)
        n = len(df)
        n_test = int(n * 0.15)
        test_idx = df_sorted_idx[int(n*0.85):]
        train_idx = df_sorted_idx[:int(n*0.85*0.85)]
        val_idx = df_sorted_idx[int(n*0.85*0.85):int(n*0.85)]
        X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
        X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]
        X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]
    else:
        # Random split fallback — keep positional indices so we can save test preds later
        all_idx = np.arange(len(df))
        train_idx, test_idx = train_test_split(all_idx, test_size=0.15, random_state=seed, stratify=y)
        X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
        X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]
        sub_train, sub_val = train_test_split(np.arange(len(train_idx)), test_size=0.176, random_state=seed, stratify=y_train)
        X_train, y_train = X.iloc[train_idx[sub_train]], y.iloc[train_idx[sub_train]]
        X_val, y_val = X.iloc[train_idx[sub_val]], y.iloc[train_idx[sub_val]]
    print(f"Train {len(X_train)} Val {len(X_val)} Test {len(X_test)}")
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)
    X_test_s = scaler.transform(X_test)

    # Logistic Regression
    print("Training LogisticRegression...")
    clf = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed, n_jobs=-1)
    clf.fit(X_train_s, y_train)

    def eval_metrics(y_true, prob, pred):
        return {
            "precision": float(precision_score(y_true, pred, zero_division=0)),
            "recall": float(recall_score(y_true, pred, zero_division=0)),
            "f1": float(f1_score(y_true, pred, zero_division=0)),
            "pr_auc": float(average_precision_score(y_true, prob)) if len(set(y_true))>1 else 0,
            "roc_auc": float(roc_auc_score(y_true, prob)) if len(set(y_true))>1 else 0,
            "confusion": confusion_matrix(y_true, pred).tolist(),
        }

    val_prob = clf.predict_proba(X_val_s)[:,1]
    val_pred = (val_prob >= 0.5).astype(int)
    test_prob = clf.predict_proba(X_test_s)[:,1]
    test_pred = (test_prob >= 0.5).astype(int)
    val_m = eval_metrics(y_val, val_prob, val_pred)
    test_m = eval_metrics(y_test, test_prob, test_pred)
    print("Val", val_m)
    print("Test", test_m)

    # Feature importance (coef)
    importances = list(zip(feature_cols, clf.coef_[0]))
    importances = sorted(importances, key=lambda x: abs(x[1]), reverse=True)[:20]

    # Optional LightGBM
    lgb_metrics = None
    if HAS_LGB:
        print("Training LightGBM...")
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        params = {"objective":"binary","metric":"auc","boosting_type":"gbdt","verbosity":-1,"seed":seed,"is_unbalance":True}
        try:
            gbm = lgb.train(params, train_data, num_boost_round=500, valid_sets=[val_data], callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)])
            lgb_val_prob = gbm.predict(X_val, num_iteration=gbm.best_iteration)
            lgb_test_prob = gbm.predict(X_test, num_iteration=gbm.best_iteration)
            lgb_val_pred = (lgb_val_prob >= 0.5).astype(int)
            lgb_test_pred = (lgb_test_prob >= 0.5).astype(int)
            lgb_metrics = {"val": eval_metrics(y_val, lgb_val_prob, lgb_val_pred), "test": eval_metrics(y_test, lgb_test_prob, lgb_test_pred)}
            print("LGB Val", lgb_metrics["val"])
            print("LGB Test", lgb_metrics["test"])
        except Exception as e:
            print(f"LGB failed: {e}")
            lgb_metrics = {"error": str(e)[:500]}

    report = {
        "seed": seed,
        "n_train": len(X_train), "n_val": len(X_val), "n_test": len(X_test),
        "feature_cols": feature_cols,
        "feature_importance": [{"feature": k, "coef": float(v)} for k,v in importances],
        "logistic": {"val": val_m, "test": test_m},
        "lightgbm": lgb_metrics,
        "disclaimer": "Trained on IEEE Fraud Detection (real) but synthetic labels not — use PR-AUC, not accuracy, due to 3.5% fraud rate",
    }

    # Save test predictions for the Threshold Decision Tool (honest held-out data)
    try:
        preds_records: dict[str, Any] = {
            "isFraud": y_test.astype(int).tolist(),
            "prob": [float(v) for v in test_prob],
        }
        if "TransactionID" in df.columns:
            preds_records["TransactionID"] = df["TransactionID"].iloc[test_idx].astype(str).tolist()
        if "TransactionAmt" in df.columns:
            preds_records["amount"] = df["TransactionAmt"].iloc[test_idx].astype(float).tolist()
        preds_df = pd.DataFrame(preds_records)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        preds_path = REPORT_PATH.parent / "ieee_test_predictions.parquet"
        preds_df.to_parquet(preds_path, index=False)
        report["test_predictions_path"] = str(preds_path)
        report["test_predictions_rows"] = len(preds_df)
        print(f"Saved test predictions {preds_df.shape} -> {preds_path}")
    except Exception as e:
        print(f"WARN: could not save test preds: {e}")

    # Save
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"scaler": scaler, "model": clf, "features": feature_cols}, f)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved model -> {MODEL_PATH}, report -> {REPORT_PATH}")
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nrows", type=int, default=None, help="limit rows for quick demo (else full)")
    parser.add_argument("--chunksize", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--full", action="store_true", help="process all 590k")
    parser.add_argument("--train-only", action="store_true")
    args = parser.parse_args()
    if args.full:
        args.nrows = None
    if not args.train_only:
        process_and_save(nrows=args.nrows, chunksize=args.chunksize, seed=args.seed)
    train_from_processed(seed=args.seed)
