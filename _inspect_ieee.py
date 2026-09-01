import pandas as pd
path = r"S:\Buildathon\paytrust-ai\data\required csv\ieee-fraud-detection\train_transaction.csv"
chunks = pd.read_csv(path, usecols=['isFraud','TransactionAmt','ProductCD','TransactionDT'], chunksize=100000)
total = 0
fraud = 0
for i, chunk in enumerate(chunks, 1):
    total += len(chunk)
    fraud += int(chunk['isFraud'].sum())
    print(f"chunk {i}: total {len(chunk)} fraud {int(chunk['isFraud'].sum())} amt_mean {chunk['TransactionAmt'].mean():.1f}")
print(f"TOTAL {total} fraud {fraud} rate {fraud/total:.4f}")
# Quick columns
import csv
with open(path, encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    print(f"cols {len(header)}")
    print(header[:15])
    print(header[15:30])
