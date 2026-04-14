import os
import xml.etree.ElementTree as ET
from google.cloud import storage, spanner

INSTANCE_ID = "pharmagraph-spanner"
DATABASE_ID = "pharmagraph-db"
GCS_BUCKET  = "pharmagraph"
BATCH_SIZE  = 500

NS = "http://www.drugbank.ca"

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)
bucket         = storage.Client().bucket(GCS_BUCKET)

def tag(name):
    return f"{{{NS}}}{name}"

def find_text(el, t):
    found = el.find(t)
    return (found.text or "").strip() if found is not None else ""

def get_primary_id(drug_el):
    for db_id in drug_el.findall(tag("drugbank-id")):
        if db_id.get("primary") == "true":
            return (db_id.text or "").strip()
    first = drug_el.find(tag("drugbank-id"))
    return (first.text or "").strip() if first is not None else ""

def get_pubchem_id(drug_el):
    for ext in drug_el.findall(f".//{tag('external-identifier')}"):
        if find_text(ext, tag("resource")) == "PubChem Compound":
            return find_text(ext, tag("identifier"))
    return ""

def get_synonyms(drug_el):
    syns = []
    for s in drug_el.findall(f".//{tag('synonyms')}/{tag('synonym')}"):
        text = (s.text or "").strip()
        if text:
            syns.append(text[:512])
    return syns[:50]

print("=== DRUGBANK ETL STARTED ===")

# ── STEP 1: Download XML ──────────────────────────────────────────────────────
# 2.41GB file — download to /tmp instead of loading into memory
print("[1/5] Downloading DrugBank XML from GCS to /tmp...")
blob = bucket.blob("drugbank/drugbank_full.xml")
blob.download_to_filename("/tmp/drugbank_full.xml")
print("[1/5] Done!")

# ── STEP 2: Parse XML iteratively ────────────────────────────────────────────
# ET.iterparse streams the XML element by element — never loads full file
# into memory. Each drug element is parsed then cleared from memory (elem.clear())
print("[2/5] Parsing XML iteratively...")

drug_nodes        = []
enzyme_nodes      = {}   # deduped by enzyme_id
substrate_edges   = []
interaction_edges = []

count = 0
for event, elem in ET.iterparse("/tmp/drugbank_full.xml", events=["end"]):
    # only process <drug> elements, skip everything else
    if elem.tag != tag("drug"):
        continue

    # only small molecules and biotech drugs — skip salts, metabolites etc
    if elem.get("type") not in ("small molecule", "biotech"):
        elem.clear()
        continue

    db_id = get_primary_id(elem)
    if not db_id:
        elem.clear()
        continue

    # only approved drugs — skip experimental, withdrawn etc
    groups = [g.text for g in elem.findall(f".//{tag('group')}") if g.text]
    if "approved" not in groups:
        elem.clear()
        continue

    name        = find_text(elem, tag("name"))[:512]
    description = find_text(elem, tag("description"))
    indication  = find_text(elem, tag("indication"))
    pubchem_id  = get_pubchem_id(elem)[:64]
    synonyms    = get_synonyms(elem)

    drug_nodes.append({
        "drug_id":     db_id,
        "name":        name,
        "description": description,
        "indication":  indication,
        "pubchem_id":  pubchem_id,
        "db_id":       db_id,
        "synonyms":    synonyms,
        "source":      "DrugBank"
    })

    # ── Enzymes ───────────────────────────────────────────────────────────────
    enzymes_el = elem.find(tag("enzymes"))
    if enzymes_el is not None:
        for enz_el in enzymes_el.findall(tag("enzyme")):
            enz_id   = find_text(enz_el, tag("id"))
            enz_name = find_text(enz_el, tag("name"))[:512]
            if not enz_id:
                continue
            # dict keyed by enzyme_id deduplicates automatically
            if enz_id not in enzyme_nodes:
                enzyme_nodes[enz_id] = {"enzyme_id": enz_id, "name": enz_name}
            substrate_edges.append({
                "drug_id":   db_id,
                "enzyme_id": enz_id,
                "source":    "DrugBank"
            })

    # ── Drug-Drug Interactions ────────────────────────────────────────────────
    # NO filter, NO cap — load ALL interactions from DrugBank
    # insert_or_update handles duplicates safely if rerun
    interactions_el = elem.find(tag("drug-interactions"))
    if interactions_el is not None:
        for inter_el in interactions_el.findall(tag("drug-interaction")):
            to_id = find_text(inter_el, tag("drugbank-id"))
            desc  = find_text(inter_el, tag("description"))
            if not to_id:
                continue
            interaction_edges.append({
                "from_drug_id": db_id,
                "to_drug_id":   to_id,
                "description":  desc,
                "source":       "DrugBank"
            })

    count += 1
    if count % 500 == 0:
        print(f"      Parsed {count} approved drugs so far...")

    # free memory immediately after processing each drug element
    elem.clear()

print(f"      Drug nodes:          {len(drug_nodes)}")
print(f"      Enzyme nodes:        {len(enzyme_nodes)}")
print(f"      SubstrateOf edges:   {len(substrate_edges)}")
print(f"      InteractsWith edges: {len(interaction_edges)}")
print("[2/5] Done!")

# ── STEP 3: Upsert Drug nodes ─────────────────────────────────────────────────
# insert_or_update: if drug_id already exists → update, else → insert
# safe to rerun — no duplicates ever created
print("[3/5] Upserting Drug nodes...")

def upsert_drugs(transaction, batch):
    transaction.insert_or_update("Drug",
        columns=["drug_id", "name", "description", "indication",
                 "pubchem_id", "db_id", "synonyms", "source"],
        values=[(r["drug_id"], r["name"], r["description"], r["indication"],
                 r["pubchem_id"], r["db_id"], r["synonyms"], r["source"])
                for r in batch])

total = 0
for i in range(0, len(drug_nodes), BATCH_SIZE):
    batch = drug_nodes[i:i + BATCH_SIZE]
    db.run_in_transaction(upsert_drugs, batch)
    total += len(batch)
    print(f"      Drugs: {total} upserted...")
print(f"      Drugs: {total} total")
print("[3/5] Done!")

# ── STEP 4: Upsert Enzyme nodes + SubstrateOf edges ───────────────────────────
print("[4/5] Upserting Enzyme nodes + SubstrateOf edges...")
enzyme_list = list(enzyme_nodes.values())

def upsert_enzymes(transaction, batch):
    transaction.insert_or_update("Enzyme",
        columns=["enzyme_id", "name"],
        values=[(r["enzyme_id"], r["name"]) for r in batch])

def upsert_substrates(transaction, batch):
    transaction.insert_or_update("SubstrateOf",
        columns=["drug_id", "enzyme_id", "source"],
        values=[(r["drug_id"], r["enzyme_id"], r["source"]) for r in batch])

total_enz = 0
for i in range(0, len(enzyme_list), BATCH_SIZE):
    batch = enzyme_list[i:i + BATCH_SIZE]
    db.run_in_transaction(upsert_enzymes, batch)
    total_enz += len(batch)
    print(f"      Enzymes: {total_enz} upserted...")

total_sub = 0
for i in range(0, len(substrate_edges), BATCH_SIZE):
    batch = substrate_edges[i:i + BATCH_SIZE]
    db.run_in_transaction(upsert_substrates, batch)
    total_sub += len(batch)
    print(f"      SubstrateOf: {total_sub} upserted...")

print(f"      Enzymes: {total_enz} total")
print(f"      SubstrateOf: {total_sub} total")
print("[4/5] Done!")

# ── STEP 5: Upsert InteractsWith edges ───────────────────────────────────────
# Full 2.1M interactions — no keyword filter, no per-drug cap
# insert_or_update keyed on (from_drug_id, to_drug_id) — safe to rerun
print("[5/5] Upserting InteractsWith edges...")

def upsert_interactions(transaction, batch):
    transaction.insert_or_update("InteractsWith",
        columns=["from_drug_id", "to_drug_id", "description", "source"],
        values=[(r["from_drug_id"], r["to_drug_id"], r["description"], r["source"])
                for r in batch])

total_int = 0
for i in range(0, len(interaction_edges), BATCH_SIZE):
    batch = interaction_edges[i:i + BATCH_SIZE]
    db.run_in_transaction(upsert_interactions, batch)
    total_int += len(batch)
    print(f"      InteractsWith: {total_int} upserted...")
print(f"      InteractsWith: {total_int} total")
print("[5/5] Done!")

# ── VERIFY ────────────────────────────────────────────────────────────────────
print("[Verify]")
with db.snapshot() as snap:
    drug_count = list(snap.execute_sql("SELECT COUNT(*) FROM Drug"))[0][0]
with db.snapshot() as snap:
    enz_count = list(snap.execute_sql("SELECT COUNT(*) FROM Enzyme"))[0][0]
with db.snapshot() as snap:
    sub_count = list(snap.execute_sql("SELECT COUNT(*) FROM SubstrateOf"))[0][0]
with db.snapshot() as snap:
    int_count = list(snap.execute_sql("SELECT COUNT(*) FROM InteractsWith"))[0][0]

print(f"      Drug nodes:          {drug_count}")
print(f"      Enzyme nodes:        {enz_count}")
print(f"      SubstrateOf edges:   {sub_count}")
print(f"      InteractsWith edges: {int_count}")
print("[Verify] Done!")

# cleanup downloaded XML from container disk
os.remove("/tmp/drugbank_full.xml")
print("=== DRUGBANK ETL COMPLETE ===")

