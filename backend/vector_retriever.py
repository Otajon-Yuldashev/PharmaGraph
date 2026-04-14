import os
from google.cloud import spanner
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
import vertexai

GCP_PROJECT   = "pharmagraph"
VERTEX_REGION = "us-central1"
INSTANCE_ID   = "pharmagraph-spanner"
DATABASE_ID   = "pharmagraph-db"

vertexai.init(project=GCP_PROJECT, location=VERTEX_REGION)
embed_model = TextEmbeddingModel.from_pretrained("text-embedding-004")

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)

def search(query, top_k=10):
    embedding = embed_model.get_embeddings([
        TextEmbeddingInput(text=query, task_type="RETRIEVAL_QUERY")
    ])[0].values

    with db.snapshot() as snapshot:
        results = list(snapshot.execute_sql(
            """
            SELECT chunk_id, pmid, title, text,
                   APPROX_DOT_PRODUCT(embedding, @query_embedding,
                       options => JSON '{"num_leaves_to_search": 10}') AS score
            FROM PubMedChunk
            WHERE embedding IS NOT NULL
            ORDER BY score DESC
            LIMIT @top_k
            """,
            params={"query_embedding": embedding, "top_k": top_k},
            param_types={
                "query_embedding": spanner.param_types.Array(spanner.param_types.FLOAT32),
                "top_k": spanner.param_types.INT64
            }
        ))

    return [
        {
            "id":    row[0],
            "pmid":  row[1],
            "title": row[2],
            "text":  row[3],
            "score": row[4]
        }
        for row in results
    ]

    