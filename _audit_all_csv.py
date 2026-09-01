import pandas as pd
from pathlib import Path

base = Path(r"S:\Buildathon\paytrust-ai\data\required csv\ieee-fraud-detection")
files = {
    "train_transaction": base / "train_transaction.csv",
    "train_identity": base / "train_identity.csv",
    "test_transaction": base / "test_transaction.csv",
    "test_identity": base / "test_identity.csv",
    "sample_submission": base / "sample_submission.csv",
    "synthetic": Path(r"S:\Buildathon\paytrust-ai\data\synthetic_transactions.csv"),
}

for name, path in files.items():
    print(f"\n=== {name}: {path.name} ===")
    if not path.exists():
        print("NOT FOUND")
        continue
    # Get rows via wc-like (count lines -1)
    import csv
    with open(path, encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        header = next(reader)
        print(f"Cols {len(header)}: {header[:5]} ... {header[-3:]}")
        # Count rows quickly
        # Use pandas chunks for big files
        if "transaction" in name:
            # Sample fraud rate if train
            if "train_transaction" in str(path):
                chunks = pd.read_csv(path, usecols=['isFraud'], chunksize=100000)
                total = sum(len(c) for c in chunks)
                # Need to re-read for fraud
                chunks = pd.read_csv(path, usecols=['isFraud'], chunksize=100000)
                fraud = sum(int(c['isFraud'].sum()) for c in chunks)
                print(f"Rows {total} Fraud {fraud} Rate {fraud/total:.4f} Size {path.stat().st_size/1024/1024:.1f} MB")
            else:
                # test_transaction has no isFraud
                chunks = pd.read_csv(path, usecols=['TransactionID'], chunksize=100000)
                total = sum(len(c) for c in chunks)
                print(f"Rows {total} Size {path.stat().st_size/1024/1024:.1f} MB")
        elif "identity" in name:
            df = pd.read_csv(path, nrows=5)
            print(f"Rows ~ {sum(1 for _ in open(path, encoding='utf-8'))-1} Size {path.stat().st_size/1024/1024:.1f} MB")
            print(f"Sample DeviceType: {df['DeviceType'].value_counts().head(2).to_dict()}")
        elif "sample" in name:
            df = pd.read_csv(path, nrows=5)
            print(f"Rows {len(pd.read_csv(path))} Sample head:\n{df.head(2).to_dict(orient='records')}")
        elif "synthetic" in name:
            df = pd.read_csv(path)
            print(f"Rows {len(df)} Cols {len(df.columns)} Fraud { (df['label']=='anomaly').sum()} Size {path.stat().st_size/1024:.1f} KB")
            print(df['scenario'].value_counts().to_dict())

# Check join coverage
print("\n=== Join Coverage ===")
train_trans_ids = set(pd.read_csv(files["train_transaction"], usecols=['TransactionID'], nrows=100000)['TransactionID'])
train_id_ids = set(pd.read_csv(files["train_identity"], usecols=['TransactionID'])['TransactionID'])
print(f"Train trans 100k sample vs all identity: overlap {len(train_trans_ids & train_id_ids)} / 100k = {len(train_trans_ids & train_id_ids)/1000:.1f}% of sample have identity")
# Approx full coverage
print(f"Identity covers {len(train_id_ids)} / 590540 = {len(train_id_ids)/590540:.1%} of train transactions")

test_trans_ids = set(pd.read_csv(files["test_transaction"], usecols=['TransactionID'], nrows=100000)['TransactionID'])
test_id_ids = set(pd.read_csv(files["test_identity"], usecols=['TransactionID'])['TransactionID'])
print(f"Test trans 100k sample vs test identity: overlap {len(test_trans_ids & test_id_ids)} / 100k")
print(f"Test identity covers {len(test_id_ids)} / ~500k = {len(test_id_ids)/500000:.1%} (approx)")
