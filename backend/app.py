from flask import Flask, request, jsonify
from flask_cors import CORS

import cache
import ner
import graph_retriever
import vector_retriever
import context_packer
import gemini_caller

app = Flask(__name__)
CORS(app)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/query", methods=["POST"])
def query():
    data       = request.get_json()
    query_text = data.get("query", "").strip()

    if not query_text:
        return jsonify({"error": "query is required"}), 400

    cached = cache.get(query_text)
    if cached:
        cached["from_cache"] = True
        return jsonify(cached)

    drug_names = ner.extract_drugs(query_text)

    if not drug_names:
        return jsonify({
            "error": "No drug names found. Please mention specific drug names.",
            "example": "Try: 'what happens if I mix metformin and alcohol?'"
        }), 400

    cross_interactions = graph_retriever.find_cross_interactions(drug_names)
    interactions       = cross_interactions + graph_retriever.find_interactions(drug_names)
    enzyme_chains      = graph_retriever.find_enzyme_chain(drug_names)
    side_effects       = graph_retriever.find_side_effects(drug_names)
    pubmed_chunks      = vector_retriever.search(query_text)

    context = context_packer.pack(
        drug_names, interactions, enzyme_chains,
        side_effects, pubmed_chunks
    )

    answer = gemini_caller.generate(query_text, context)

    result = {
        "query":       query_text,
        "drugs_found": drug_names,
        "answer":      answer,
        "graph_path":  interactions + enzyme_chains,
        "sources":     [c["pmid"] for c in pubmed_chunks],
        "from_cache":  False
    }

    cache.set(query_text, result)
    return jsonify(result)

@app.route("/cache", methods=["GET"])
def get_cache():
    return jsonify(cache.get_all())

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)