import pandas as pd

train_path = r"S:\Buildathon\paytrust-ai\data\required csv\ieee-fraud-detection\train_transaction.csv"
id_path = r"S:\Buildathon\paytrust-ai\data\required csv\ieee-fraud-detection\train_identity.csv"

# Identity stats
id_df = pd.read_csv(id_path, nrows=5)
print("Identity cols:", len(id_df.columns))
print(list(id_df.columns)[:10])
print(id_df.head(1).to_dict(orient='records')[0])

# Check join coverage
import csv
trans_ids = set()
with open(train_path, encoding='utf-8') as f:
    r = csv.DictReader(f)
    for i, row in enumerate(r):
        if i < 100000:
            trans_ids.add(row['TransactionID'])
        elif i == 100000:
            break
print(f"Sample trans_ids {len(trans_ids)}")

id_ids = set(pd.read_csv(id_path, usecols=['TransactionID'])['TransactionID'].head(100000))
print(f"ID overlap sample: {len(trans_ids & id_ids)} / {len(trans_ids)}")

# Check V columns stats via chunk
chunks = pd.read_csv(train_path, usecols=['V1','V2','V3','isFraud'], chunksize=100000)
for i, chunk in enumerate(chunks):
    if i == 0:
        print("V1 mean", chunk['V1'].mean(), "missing", chunk['V1'].isna().mean())
        print("V1 fraud vs non", chunk.groupby('isFraud')['V1'].mean().to_dict())
    if i >= 0:
        break

# Check card and addr missing
chunks2 = pd.read_csv(train_path, usecols=['card1','card2','addr1','P_emaildomain'], chunksize=100000)
for chunk in chunks2:
    print("card1 missing", chunk['card1'].isna().mean())
    print("P_emaildomain top", chunk['P_emaildomain'].value_counts().head(3).to_dict())
    break
