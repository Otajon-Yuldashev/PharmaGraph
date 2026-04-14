from google.cloud import spanner

INSTANCE_ID = "pharmagraph-spanner"
DATABASE_ID = "pharmagraph-db"

spanner_client = spanner.Client()
db             = spanner_client.instance(INSTANCE_ID).database(DATABASE_ID)

def find_interactions(drug_names):
    results = []
    for drug in drug_names:
        with db.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(
                """
                GRAPH PharmaGraph
                MATCH (a:Drug)-[r:INTERACTS_WITH]->(b:Drug)
                WHERE UPPER(a.name) LIKE @pattern
                   OR a.db_id = @drug
                RETURN a.name AS drug_a,
                       b.name AS drug_b,
                       r.description AS description,
                       r.source AS source
                LIMIT 10
                """,
                params={"pattern": f"%{drug.upper()}%", "drug": drug.upper()},
                param_types={
                    "pattern": spanner.param_types.STRING,
                    "drug":    spanner.param_types.STRING
                }
            ))
            results.extend([
                {"drug_a": r[0], "drug_b": r[1], "description": r[2], "source": r[3]}
                for r in rows
            ])
    return results

def find_cross_interactions(drug_names):
    results = []
    for i in range(len(drug_names)):
        for j in range(len(drug_names)):
            if i == j:
                continue
            with db.snapshot() as snapshot:
                rows = list(snapshot.execute_sql(
                    """
                    GRAPH PharmaGraph
                    MATCH (a:Drug)-[r:INTERACTS_WITH]->(b:Drug)
                    WHERE UPPER(a.name) LIKE @drug_a
                      AND UPPER(b.name) LIKE @drug_b
                    RETURN a.name AS drug_a,
                           b.name AS drug_b,
                           r.description AS description,
                           r.source AS source
                    LIMIT 5
                    """,
                    params={
                        "drug_a": f"%{drug_names[i].upper()}%",
                        "drug_b": f"%{drug_names[j].upper()}%"
                    },
                    param_types={
                        "drug_a": spanner.param_types.STRING,
                        "drug_b": spanner.param_types.STRING
                    }
                ))
                results.extend([
                    {"drug_a": r[0], "drug_b": r[1], "description": r[2], "source": r[3]}
                    for r in rows
                ])
    return results

def find_enzyme_chain(drug_names):
    results = []
    for drug in drug_names:
        with db.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(
                """
                GRAPH PharmaGraph
                MATCH (a:Drug)-[:SUBSTRATE_OF]->(e:Enzyme)
                WHERE UPPER(a.name) LIKE @pattern
                RETURN a.name AS drug,
                       e.name AS enzyme
                LIMIT 5
                """,
                params={"pattern": f"%{drug.upper()}%"},
                param_types={"pattern": spanner.param_types.STRING}
            ))
            results.extend([
                {"drug": r[0], "enzyme": r[1], "other_drugs": []}
                for r in rows
            ])
    return results

def find_side_effects(drug_names):
    results = []
    for drug in drug_names:
        with db.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(
                """
                GRAPH PharmaGraph
                MATCH (a:Drug)-[:HAS_SIDE_EFFECT]->(s:SideEffect)
                WHERE UPPER(a.name) LIKE @pattern
                RETURN a.name AS drug,
                       ARRAY_AGG(s.name) AS side_effects
                GROUP BY a.name
                LIMIT 5
                """,
                params={"pattern": f"%{drug.upper()}%"},
                param_types={"pattern": spanner.param_types.STRING}
            ))
            results.extend([
                {"drug": r[0], "side_effects": list(r[1])[:5] if r[1] else []}
                for r in rows
            ])
    return results

    