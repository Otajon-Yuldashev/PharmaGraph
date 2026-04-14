# PharmaGraph

A graph-augmented RAG system for drug interaction analysis, built on Google Cloud Platform. Users ask natural language questions about drug interactions and receive cited answers grounded in pharmacological data — powered by Spanner Graph, Gemini 2.5 Flash, and a 2.1 million edge knowledge graph.

Built for educational purposes as a data engineering portfolio project.

---

## What it does

A user types: *"what happens if I mix metformin and alcohol?"*

The system:
1. Scans the query word by word against the Drug table to identify drug names
2. Traverses the knowledge graph to find direct interactions between those drugs
3. Runs a vector similarity search across 4,822 PubMed research chunks
4. Packs the graph results and research context into a prompt
5. Sends it to Gemini 2.5 Flash which generates a cited answer referencing DrugBank, FAERS, SIDER, and PubMed paper IDs
6. Returns the answer alongside an animated knowledge graph visualization showing the drug relationships

---

## Architecture

```
User query
    ↓
React Frontend (Cloud Run)
    ↓ POST /query
Flask API (Cloud Run)
    ├── ner.py              — extract drug names via Spanner lookup
    ├── graph_retriever.py  — GQL graph traversal for interactions
    ├── vector_retriever.py — APPROX_DOT_PRODUCT vector search
    ├── context_packer.py   — format context for Gemini
    └── gemini_caller.py    — Gemini 2.5 Flash cited answer
    ↑
Spanner Graph (pharmagraph-db)
    ├── Drug, SideEffect, Enzyme       — node tables
    ├── InteractsWith, HasSideEffect   — edge tables (2.1M+ edges)
    ├── PubMedChunk + embedding[768]   — vector search
    └── PharmaGraph property graph     — GQL traversal
    ↑
Cloud Run ETL Job (one-shot)
    ↑
Cloud Storage (gs://pharmagraph/)
    ├── DrugBank XML (2.41 GB)
    ├── SIDER TSV
    ├── FAERS TXT
    └── PubMed XML
```

---

## Why Spanner Graph

The original architecture used Neo4j AuraDB for the graph and Vertex AI Vector Search for embeddings — two separate systems. Neo4j's free tier has a 400,000 relationship limit, which forced filtering 2.1 million DrugBank interactions down to 153,000. Vertex AI Vector Search required a separate metadata file, a separate index endpoint, and a separate API call.

Migrating to Spanner Graph replaced both with one database:

| | Neo4j + Vertex AI | Spanner Graph |
|---|---|---|
| Relationship limit | 400,000 (free tier) | None |
| Vector search | Separate Vertex AI index | Built-in APPROX_DOT_PRODUCT |
| Query languages | Cypher + REST | SQL + GQL (ISO standard) |
| Auth | Username + password + URI | GCP application default credentials |
| Systems to manage | 2 | 1 |

Spanner Graph is not a separate product — it's a capability built into Cloud Spanner that lets you define a property graph on top of regular relational tables. The same rows that answer SQL queries are also traversed as graph edges. No data duplication.

---

## Database Schema

### Node tables

```sql
Drug        (drug_id PK, name, description, indication, pubchem_id,
             sider_id, db_id, synonyms ARRAY<STRING>, source)

SideEffect  (side_effect_id PK, name)

Enzyme      (enzyme_id PK, name)

PubMedChunk (chunk_id PK, pmid, title, text,
             embedding ARRAY<FLOAT32>(vector_length=>768))
```

### Edge tables

```sql
HasSideEffect  (drug_id, side_effect_id, source)
               INTERLEAVE IN PARENT Drug ON DELETE CASCADE

SubstrateOf    (drug_id, enzyme_id, source)
               INTERLEAVE IN PARENT Drug ON DELETE CASCADE

InteractsWith  (from_drug_id, to_drug_id, description, source)
               -- not interleaved: self-referencing Drug→Drug
               -- uses NOT ENFORCED foreign keys instead
```

### Indexes

```sql
CREATE VECTOR INDEX PubMedEmbeddingIndex
ON PubMedChunk(embedding)
WHERE embedding IS NOT NULL
OPTIONS (distance_type = 'DOT_PRODUCT', tree_depth = 2, num_leaves = 100)
```

### Property graph

```sql
CREATE PROPERTY GRAPH PharmaGraph
    NODE TABLES (Drug, SideEffect, Enzyme, PubMedChunk)
    EDGE TABLES (HasSideEffect, SubstrateOf, InteractsWith)
```

### Key design decisions

**Interleaving** — `HasSideEffect` and `SubstrateOf` are interleaved into the `Drug` parent table. This physically colocates child rows with their parent row on disk, so queries like "find all side effects of Metformin" are a single disk read rather than a join across two locations.

**InteractsWith cannot be interleaved** — it is a self-referencing Drug→Drug edge. Spanner requires the first primary key column of a child table to match the parent table's primary key exactly. Since `InteractsWith` has `from_drug_id` and `to_drug_id` rather than `drug_id`, interleaving is not possible. NOT ENFORCED foreign keys provide query optimizer hints without the write penalty of enforced checks.

**DOT_PRODUCT vector index** — matches the distance metric used by `text-embedding-004` internally. `tree_depth=2` and `num_leaves=100` are appropriate for a dataset of ~5,000 vectors.

---

## Data

| Dataset | Source | Loaded |
|---|---|---|
| DrugBank | `drugbank_full.xml` (2.41 GB) | 7,310 Drug nodes, 2,171,535 InteractsWith edges, 458 Enzyme nodes, 5,447 SubstrateOf edges |
| SIDER | `meddra_all_se.tsv` | 1,430 Drug nodes, 5,868 SideEffect nodes, 139,756 HasSideEffect edges |
| FAERS | `DRUG24Q3.txt` + `REAC24Q3.txt` | Drug nodes + InteractsWith edges with reaction aggregates |
| PubMed | `abstracts_raw.xml` | 4,707 abstracts → 4,822 chunks with 768-dim embeddings |

**Total: ~2.3 million rows across 7 tables**

DrugBank XML is 2.41 GB — too large for `ET.fromstring()` which loads the entire file into memory. The ETL uses `ET.iterparse()` which streams the file element by element, parsing one `<drug>` block at a time and calling `elem.clear()` immediately after to free memory. This keeps RAM usage flat regardless of file size.

---

## ETL Pipeline

All four ETL scripts run as a single Cloud Run job via `orchestrate.py`, which calls each script sequentially using `subprocess.run(..., check=True)`. If any script fails the job exits with a non-zero code and Cloud Run marks the execution as failed.

```
orchestrate.py
    ├── etl_sider.py     — parse TSV → Drug + SideEffect + HasSideEffect
    ├── etl_faers.py     — parse CSV → Drug + InteractsWith (with reaction aggregates)
    ├── etl_drugbank.py  — stream XML → Drug + Enzyme + SubstrateOf + InteractsWith
    └── etl_pubmed.py    — parse XML → chunk → embed → PubMedChunk
```

All writes use `insert_or_update` keyed on the primary key — safe to rerun without creating duplicates. Spanner transactions are batched at 500 rows per commit to stay within mutation limits.

PubMed embeddings are generated via Vertex AI `text-embedding-004` with `task_type=RETRIEVAL_DOCUMENT`. At query time the user query is embedded with `task_type=RETRIEVAL_QUERY`. This distinction helps the model optimize embeddings for their role — documents for storage, queries for retrieval.

---

## Backend

The Flask API runs on Cloud Run with 2 vCPUs and 2Gi RAM. All seven modules:

| File | Role |
|---|---|
| `app.py` | Flask routes — `/query` and `/health` |
| `ner.py` | Splits query into words, queries Spanner Drug table to identify drug names |
| `graph_retriever.py` | GQL queries for interactions, enzyme chains, side effects, cross-drug interactions |
| `vector_retriever.py` | Embeds query, runs `APPROX_DOT_PRODUCT` against `PubMedEmbeddingIndex` |
| `context_packer.py` | Formats graph results and PubMed chunks into a structured prompt |
| `gemini_caller.py` | Sends prompt to Gemini 2.5 Flash via Vertex AI SDK |
| `cache.py` | In-memory dict cache per Cloud Run instance |

### RAG pipeline per query

```
1. Check in-memory cache
2. NER — scan query words against Drug table to extract drug names
3. find_cross_interactions — direct Drug A ↔ Drug B edges (highest priority)
4. find_interactions — individual drug neighborhood edges
5. find_enzyme_chain — SubstrateOf traversal
6. find_side_effects — HasSideEffect traversal
7. vector_retriever — APPROX_DOT_PRODUCT on PubMedChunk embeddings
8. context_packer — format all results into prompt
9. Gemini 2.5 Flash — generate cited answer
10. Cache result → return JSON
```

### NER approach

The original NER used spaCy with a hardcoded list of ~15 drug hints. This meant any drug not on the list — Lepirudin, Alteplase, Vancomycin — returned no results. The updated approach queries the Spanner Drug table directly for each word in the query, checking for exact name matches. Since the Drug table contains 7,310+ entries covering approved drugs across all datasets, this catches any drug the system knows about. spaCy was removed entirely.

---

## Frontend

Single-file React app (`App.jsx`) built with Vite, served by Nginx on Cloud Run.

**Chat interface** — centered layout, suggestion pills on first load, markdown rendering for Gemini responses (converts `**bold**` to green headings, `* bullets` to numbered lists), typing animation while waiting for response.

**Knowledge graph** — Canvas API visualization that appears on the right panel after the first query. Shows the queried drugs as primary nodes (larger, dark green) with up to 3 neighbors each and enzyme nodes. Nodes float with a sine wave animation. Clicking any node shows the interaction description in an overlay. The graph panel is `position: sticky` with `height: 100vh` so it never stretches or scrolls with the chat.

---

## Repository Structure

```
PharmaGraph/
├── spanner/
│   └── creating_tables.sql     — full DDL: tables, vector index, property graph
├── etl/
│   ├── orchestrate.py          — runs all 4 ETL scripts in order
│   ├── etl_sider.py
│   ├── etl_faers.py
│   ├── etl_drugbank.py
│   ├── etl_pubmed.py
│   ├── requirements.txt
│   └── Dockerfile
├── backend/
│   ├── app.py
│   ├── ner.py
│   ├── graph_retriever.py
│   ├── vector_retriever.py
│   ├── context_packer.py
│   ├── gemini_caller.py
│   ├── cache.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   └── Dockerfile
└── README.md
```

---

## GCP Infrastructure

| Resource | Details |
|---|---|
| Region | us-central1 |
| Cloud Storage | gs://pharmagraph/ — raw datasets |
| Spanner instance | pharmagraph-spanner — Enterprise, 100 PUs |
| Spanner database | pharmagraph-db |
| Cloud Run (ETL) | 16Gi RAM, 4 CPU, 5hr timeout — one-shot job |
| Cloud Run (API) | 2Gi RAM, 2 CPU, 120s timeout |
| Cloud Run (UI) | 256Mi RAM, Nginx static serving |
| Artifact Registry | pharmagraph-repo — etl-spanner, backend, frontend images |
| Vertex AI | text-embedding-004, Gemini 2.5 Flash |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, Canvas API |
| Backend | Flask, Gunicorn, Python 3.12 |
| Database | Cloud Spanner Graph |
| Vector search | Spanner APPROX_DOT_PRODUCT |
| Graph query | GQL (ISO standard) |
| LLM | Gemini 2.5 Flash (Vertex AI) |
| Embeddings | text-embedding-004 (Vertex AI) |
| Containerization | Docker |
| Hosting | Cloud Run |
| Storage | Cloud Storage |
| Registry | Artifact Registry |

---

## Data Credits

- **DrugBank** — drug-drug interactions, enzyme substrates, drug metadata
- **SIDER** — drug side effects (MedDRA coded)
- **FAERS** — FDA adverse event reporting system
- **PubMed** — pharmacological research abstracts

This project was built for educational purposes under academic data access. The system is not publicly deployed.

---

## Local Development

Requires a GCP project with Spanner, Vertex AI, and Cloud Storage enabled, and application default credentials configured via `gcloud auth application-default login`.

```bash
# Backend
cd backend
pip install -r requirements.txt
python app.py

# Frontend
cd frontend
npm install
npm run dev
```
