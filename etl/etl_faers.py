import os
import io
import json
import hashlib
import pandas as pd
from google.cloud import storage, spanner

INSTANCE_ID = "pharmagraph-spanner"
DATABASE_ID = "pharmagraph-db"
GCS_BUCKET  = "pharmagraph"
BATCH_SIZE  = 500

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)
bucket         = storage.Client().bucket(GCS_BUCKET)

def make_id(value: str, prefix: str = "") -> str:
    h = hashlib.md5(value.encode()).hexdigest()[:16]
    return f"{prefix}{h}" if prefix else h

print("=== FAERS ETL STARTED ===")

print("[1/5] Reading DRUG24Q3.txt from GCS...")
content = bucket.blob("faers/DRUG24Q3.txt").download_as_text(encoding="latin-1")
drug_df = pd.read_csv(io.StringIO(content), sep="$", on_bad_lines="skip", low_memory=False)
print(f"      Raw rows: {len(drug_df)}")
drug_df = drug_df[drug_df["role_cod"].isin(["PS", "I"])]
drug_df = drug_df[["primaryid", "role_cod", "prod_ai"]].dropna()
drug_df["prod_ai"] = drug_df["prod_ai"].str.strip().str.upper()
drug_df = drug_df[drug_df["prod_ai"] != ""]
print(f"      After cleaning: {len(drug_df)} rows")
print("[1/5] Done!")

print("[2/5] Reading REAC24Q3.txt from GCS...")
content = bucket.blob("faers/REAC24Q3.txt").download_as_text(encoding="latin-1")
reac_df = pd.read_csv(io.StringIO(content), sep="$", on_bad_lines="skip", low_memory=False)
print(f"      Raw rows: {len(reac_df)}")
reac_df = reac_df[["primaryid", "pt"]].dropna()
reac_df["pt"] = reac_df["pt"].str.strip()
reac_df = reac_df[reac_df["pt"] != ""]
print(f"      After cleaning: {len(reac_df)} rows")
print("[2/5] Done!")

print("[3/5] Building drug interaction pairs...")
primary     = drug_df[drug_df["role_cod"] == "PS"][["primaryid", "prod_ai"]].rename(columns={"prod_ai": "drug_a"})
interacting = drug_df[drug_df["role_cod"] == "I"][["primaryid", "prod_ai"]].rename(columns={"prod_ai": "drug_b"})
pairs       = primary.merge(interacting, on="primaryid")

reactions_by_report = (
    reac_df.groupby("primaryid")["pt"]
    .apply(list).reset_index()
    .rename(columns={"pt": "reactions"})
)
pairs = pairs.merge(reactions_by_report, on="primaryid", how="left")
pairs["reactions"] = pairs["reactions"].apply(lambda x: x if isinstance(x, list) else [])

agg = (
    pairs.groupby(["drug_a", "drug_b"])
    .agg(
        report_count=("primaryid", "nunique"),
        reactions=("reactions", lambda lists: sorted({r for sublist in lists for r in sublist}))
    )
    .reset_index()
)
agg["description"] = agg.apply(
    lambda r: json.dumps({
        "report_count": int(r["report_count"]),
        "reactions":    r["reactions"][:50]
    }), axis=1
)
print(f"      Interaction pairs: {len(agg)}")
print("[3/5] Done!")

print("[4/5] Upserting Drug nodes...")
all_drug_names = sorted(set(agg["drug_a"].tolist() + agg["drug_b"].tolist()))
print(f"      Unique drugs: {len(all_drug_names)}")

def upsert_drugs(transaction, batch):
    transaction.insert_or_update("Drug",
        columns=["drug_id", "name", "source"],
        values=[(make_id(name, "faers_"), name, "FAERS") for name in batch])

total = 0
for i in range(0, len(all_drug_names), BATCH_SIZE):
    batch = all_drug_names[i:i + BATCH_SIZE]
    db.run_in_transaction(upsert_drugs, batch)
    total += len(batch)
    print(f"      Drugs: {total} upserted...")
print(f"      Drugs: {total} total")
print("[4/5] Done!")

print("[5/5] Loading InteractsWith edges...")
records = agg.to_dict("records")

def upsert_edges(transaction, batch):
    transaction.insert_or_update("InteractsWith",
        columns=["from_drug_id", "to_drug_id", "description", "source"],
        values=[(
            make_id(r["drug_a"], "faers_"),
            make_id(r["drug_b"], "faers_"),
            r["description"],
            "FAERS"
        ) for r in batch])

total = 0
for i in range(0, len(records), BATCH_SIZE):
    batch = records[i:i + BATCH_SIZE]
    db.run_in_transaction(upsert_edges, batch)
    total += len(batch)
    print(f"      InteractsWith: {total} loaded...")
print(f"      InteractsWith: {total} total")
print("[5/5] Done!")

print("[Verify]")
with db.snapshot() as snap:
    drug_count = list(snap.execute_sql("SELECT COUNT(*) FROM Drug"))[0][0]
with db.snapshot() as snap:
    edge_count = list(snap.execute_sql("SELECT COUNT(*) FROM InteractsWith"))[0][0]
print(f"      Drug nodes:          {drug_count}")
print(f"      InteractsWith edges: {edge_count}")
print("=== FAERS ETL COMPLETE ===")

