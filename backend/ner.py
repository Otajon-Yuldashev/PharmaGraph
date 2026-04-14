from google.cloud import spanner

INSTANCE_ID = "pharmagraph-spanner"
DATABASE_ID  = "pharmagraph-db"

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)

# common words to skip when scanning query for drug names
STOPWORDS = {
    "with", "and", "the", "what", "happens", "side", "effects",
    "when", "take", "taking", "mix", "mixing", "combine", "combining",
    "together", "interaction", "interactions", "between", "does", "drug",
    "drugs", "about", "safe", "safety", "effect", "risk", "risks",
    "how", "can", "could", "would", "should", "tell", "give", "show",
    "please", "help", "need", "know", "want", "will", "from", "into",
    "for", "are", "is", "it", "if", "of", "to", "a", "an", "in", "on",
    "at", "by", "as", "or", "not", "be", "has", "have", "had", "do",
    "did", "use", "used", "using", "after", "before", "during", "combo",
}

DRUG_ALIASES = {
    "ALCOHOL":     "ETHANOL",
    "TYLENOL":     "ACETAMINOPHEN",
    "PARACETAMOL": "ACETAMINOPHEN",
    "ADVIL":       "IBUPROFEN",
    "MOTRIN":      "IBUPROFEN",
    "GLUCOPHAGE":  "METFORMIN",
    "ASPIRIN":     "ACETYLSALICYLIC ACID",
}

def extract_drugs(query):
    # split query into candidate words, skip stopwords and short words
    words = [
        w.strip("?.,!") for w in query.split()
        if len(w.strip("?.,!")) >= 4
        and w.strip("?.,!").lower() not in STOPWORDS
    ]

    if not words:
        return []

    # also try two-word combinations (e.g. "acetyl salicylic")
    bigrams = [
        f"{words[i]} {words[i+1]}"
        for i in range(len(words) - 1)
    ]

    candidates = words + bigrams
    found = set()

    for candidate in candidates:
        upper = candidate.upper()

        # check alias first
        if upper in DRUG_ALIASES:
            found.add(DRUG_ALIASES[upper])
            continue

        # query Spanner — match against name exactly or synonyms
        with db.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(
                """
                SELECT name FROM Drug
                WHERE UPPER(name) = @word
                LIMIT 1
                """,
                params={"word": upper},
                param_types={"word": spanner.param_types.STRING}
            ))
            if rows:
                found.add(rows[0][0].upper())

    return list(found)

    