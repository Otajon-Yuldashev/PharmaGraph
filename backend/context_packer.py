def pack(drug_names, interactions, enzyme_chains, side_effects, pubmed_chunks):
    parts = []
    parts.append("=== DRUG INTERACTION CONTEXT ===")

    if interactions:
        parts.append("\nKnown interactions:")
        for i in interactions:
            parts.append(
                f"- {i.get('drug_a','?')} + {i.get('drug_b','?')}: "
                f"{i.get('description','no description')} "
                f"[source: {i.get('source','unknown')}]"
            )

    if enzyme_chains:
        parts.append("\nEnzyme relationships:")
        for e in enzyme_chains:
            others = ", ".join(e.get("other_drugs", [])[:3])
            parts.append(
                f"- {e.get('drug','?')} is processed by {e.get('enzyme','?')}"
                + (f" (also processes: {others})" if others else "")
            )

    if side_effects:
        parts.append("\nKnown side effects:")
        for s in side_effects:
            effects = ", ".join(s.get("side_effects", [])[:5])
            parts.append(f"- {s.get('drug','?')}: {effects}")

    if pubmed_chunks:
        parts.append("\n=== RESEARCH CONTEXT (PubMed) ===")
        for chunk in pubmed_chunks[:5]:
            parts.append(
                f"\n[PMID: {chunk['pmid']}] {chunk['title']}\n{chunk['text']}"
            )

    return "\n".join(parts)