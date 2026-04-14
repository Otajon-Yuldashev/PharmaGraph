import os
from google.cloud import spanner, storage

INSTANCE_ID = "pharmagraph-spanner"
DATABASE_ID = "pharmagraph-db"
GCS_BUCKET  = "pharmagraph"
GCS_FILE    = "sider/meddra_all_se.tsv"

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)
bucket         = storage.Client().bucket(GCS_BUCKET)

print("=== SIDER ETL STARTED ===")

print("[1/4] Downloading SIDER TSV from GCS...")
blob    = bucket.blob(GCS_FILE)
content = blob.download_as_text(encoding="utf-8")
lines   = content.strip().split("\n")
print(f"      Total lines: {len(lines)}")
print("[1/4] Done!")

print("[2/4] Parsing SIDER data...")
drugs        = {}
side_effects = {}
edges        = set()

for line in lines:
    parts = line.split("\t")
    if len(parts) < 4:
        continue
    flat_id   = parts[0].strip()
    drug_name = parts[1].strip()
    se_id     = parts[2].strip()
    se_name   = parts[3].strip()
    if not flat_id or not se_id:
        continue
    drugs[flat_id]      = drug_name
    side_effects[se_id] = se_name
    edges.add((flat_id, se_id))

drug_list = [{"drug_id": k, "name": v, "sider_id": k, "source": "SIDER"} for k, v in drugs.items()]
se_list   = [{"side_effect_id": k, "name": v} for k, v in side_effects.items()]
edge_list = [{"drug_id": d, "side_effect_id": s, "source": "SIDER"} for d, s in edges]

print(f"      Drug nodes:          {len(drug_list)}")
print(f"      SideEffect nodes:    {len(se_list)}")
print(f"      HasSideEffect edges: {len(edge_list)}")
print("[2/4] Done!")

BATCH_SIZE = 500

def upsert(transaction, table, columns, batch):
    transaction.insert_or_update(table, columns=columns,
        values=[tuple(r[c] for c in columns) for r in batch])

def batch_load(table, columns, rows, label):
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        db.run_in_transaction(upsert, table, columns, batch)
        total += len(batch)
        print(f"      {label}: {total} loaded...")
    print(f"      {label}: {total} total")

print("[3/4] Loading into Spanner...")
batch_load("Drug",          ["drug_id", "name", "sider_id", "source"],          drug_list, "Drugs")
batch_load("SideEffect",    ["side_effect_id", "name"],                          se_list,   "SideEffects")
batch_load("HasSideEffect", ["drug_id", "side_effect_id", "source"],             edge_list, "HasSideEffect")
print("[3/4] Done!")

print("[4/4] Verifying...")
with db.snapshot() as snap:
    drug_count = list(snap.execute_sql("SELECT COUNT(*) FROM Drug"))[0][0]
with db.snapshot() as snap:
    se_count = list(snap.execute_sql("SELECT COUNT(*) FROM SideEffect"))[0][0]
with db.snapshot() as snap:
    edge_count = list(snap.execute_sql("SELECT COUNT(*) FROM HasSideEffect"))[0][0]
print(f"      Drugs:         {drug_count}")
print(f"      SideEffects:   {se_count}")
print(f"      HasSideEffect: {edge_count}")
print("[4/4] Done!")
print("=== SIDER ETL COMPLETE ===")


