import os
import xml.etree.ElementTree as ET
from google.cloud import storage, spanner
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
import vertexai
import hashlib

INSTANCE_ID   = "pharmagraph-spanner"
DATABASE_ID   = "pharmagraph-db"
GCS_BUCKET    = "pharmagraph"
GCP_PROJECT   = "pharmagraph"
VERTEX_REGION = "us-central1"
BATCH_SIZE    = 25
SPANNER_BATCH = 50

vertexai.init(project=GCP_PROJECT, location=VERTEX_REGION)

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)
bucket         = storage.Client().bucket(GCS_BUCKET)

def make_chunk_id(pmid: str, index: int) -> str:
    return hashlib.md5(f"{pmid}_{index}".encode()).hexdigest()[:64]

print("=== PUBMED ETL STARTED ===")

print("[1/4] Reading PubMed XML from GCS...")
content = bucket.blob("pubmed/abstracts_raw.xml").download_as_text(encoding="utf-8")
print("[1/4] Done!")

print("[2/4] Parsing XML and chunking abstracts...")

def extract_abstracts(xml_content):
    abstracts = []
    for chunk in xml_content.split("<?xml"):
        if not chunk.strip():
            continue
        try:
            root = ET.fromstring("<?xml" + chunk)
            for article in root.iter("PubmedArticle"):
                pmid_el     = article.find(".//PMID")
                title_el    = article.find(".//ArticleTitle")
                abstract_el = article.find(".//AbstractText")
                if abstract_el is not None and abstract_el.text:
                    abstracts.append({
                        "pmid":  (pmid_el.text or "unknown") if pmid_el is not None else "unknown",
                        "title": (title_el.text or "") if title_el is not None else "",
                        "abstract": abstract_el.text.strip()
                    })
        except ET.ParseError:
            continue
    return abstracts

def chunk_text(text, chunk_size=300):
    words = text.split()
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

abstracts = extract_abstracts(content)
print(f"      Parsed abstracts: {len(abstracts)}")

chunks = []
for ab in abstracts:
    for i, text in enumerate(chunk_text(ab["abstract"])):
        chunks.append({
            "chunk_id": make_chunk_id(ab["pmid"], i),
            "pmid":     ab["pmid"],
            "title":    ab["title"] or "",
            "text":     text
        })
print(f"      Total chunks: {len(chunks)}")
print("[2/4] Done!")

print("[3/4] Generating embeddings via Vertex AI...")
model = TextEmbeddingModel.from_pretrained("text-embedding-004")

def embed_batch(texts):
    inputs = [TextEmbeddingInput(text=t, task_type="RETRIEVAL_DOCUMENT") for t in texts]
    return [e.values for e in model.get_embeddings(inputs)]

embedded_chunks = []
for i in range(0, len(chunks), BATCH_SIZE):
    batch   = chunks[i:i + BATCH_SIZE]
    vectors = embed_batch([c["text"] for c in batch])
    for chunk, vector in zip(batch, vectors):
        embedded_chunks.append({**chunk, "embedding": vector})
    print(f"      Embedded {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)} chunks...")
print("[3/4] Done!")

print("[4/4] Loading PubMedChunk rows into Spanner...")

def upsert_chunks(transaction, batch):
    transaction.insert_or_update("PubMedChunk",
        columns=["chunk_id", "pmid", "title", "text", "embedding"],
        values=[(
            row["chunk_id"],
            row["pmid"][:32],
            (row["title"] or "")[:512],
            row["text"],
            row["embedding"]
        ) for row in batch])

total = 0
for i in range(0, len(embedded_chunks), SPANNER_BATCH):
    batch = embedded_chunks[i:i + SPANNER_BATCH]
    db.run_in_transaction(upsert_chunks, batch)
    total += len(batch)
    print(f"      PubMedChunk: {total}/{len(embedded_chunks)} loaded...")
print(f"      PubMedChunk: {total} total")
print("[4/4] Done!")

print("[Verify]")
with db.snapshot() as snap:
    count = list(snap.execute_sql("SELECT COUNT(*) FROM PubMedChunk"))[0][0]
print(f"      PubMedChunk rows: {count}")
print("=== PUBMED ETL COMPLETE ===")

