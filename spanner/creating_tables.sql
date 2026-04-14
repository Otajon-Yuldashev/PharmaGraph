CREATE TABLE Drug (
    drug_id     STRING(64) NOT NULL,
    name        STRING(512),
    description STRING(MAX),
    indication  STRING(MAX),
    pubchem_id  STRING(64),
    sider_id    STRING(64),
    db_id       STRING(64),
    synonyms    ARRAY<STRING(512)>,
    source      STRING(64),
) PRIMARY KEY (drug_id);


CREATE TABLE SideEffect (
    side_effect_id STRING(64) NOT NULL,
    name           STRING(512),
) PRIMARY KEY (side_effect_id);


CREATE TABLE Enzyme (
    enzyme_id STRING(64) NOT NULL,
    name      STRING(512),
) PRIMARY KEY (enzyme_id);


CREATE TABLE PubMedChunk (
    chunk_id  STRING(64) NOT NULL,
    pmid      STRING(32),
    title     STRING(512),
    text      STRING(MAX),
    embedding ARRAY<FLOAT32>(vector_length=>768),
) PRIMARY KEY (chunk_id);


CREATE TABLE HasSideEffect (
    drug_id        STRING(64) NOT NULL,
    side_effect_id STRING(64) NOT NULL,
    source         STRING(64),
    CONSTRAINT FK_SideEffect FOREIGN KEY (side_effect_id)
        REFERENCES SideEffect (side_effect_id) NOT ENFORCED,
) PRIMARY KEY (drug_id, side_effect_id),
  INTERLEAVE IN PARENT Drug ON DELETE CASCADE;


CREATE TABLE SubstrateOf (
    drug_id   STRING(64) NOT NULL,
    enzyme_id STRING(64) NOT NULL,
    source    STRING(64),
    CONSTRAINT FK_Enzyme FOREIGN KEY (enzyme_id)
        REFERENCES Enzyme (enzyme_id) NOT ENFORCED,
) PRIMARY KEY (drug_id, enzyme_id),
  INTERLEAVE IN PARENT Drug ON DELETE CASCADE;


CREATE TABLE InteractsWith (
    from_drug_id STRING(64) NOT NULL,
    to_drug_id   STRING(64) NOT NULL,
    description  STRING(MAX),
    source       STRING(64),
    CONSTRAINT FK_FromDrug FOREIGN KEY (from_drug_id)
        REFERENCES Drug (drug_id) NOT ENFORCED,
    CONSTRAINT FK_ToDrug FOREIGN KEY (to_drug_id)
        REFERENCES Drug (drug_id) NOT ENFORCED,
) PRIMARY KEY (from_drug_id, to_drug_id);


CREATE VECTOR INDEX PubMedEmbeddingIndex
ON PubMedChunk(embedding)
WHERE embedding IS NOT NULL
OPTIONS (distance_type = 'DOT_PRODUCT', tree_depth = 2, num_leaves = 100);


CREATE PROPERTY GRAPH PharmaGraph
    NODE TABLES (
        Drug
            LABEL Drug
            PROPERTIES (drug_id, name, description, indication,
                        pubchem_id, sider_id, db_id, synonyms, source),
        SideEffect
            LABEL SideEffect
            PROPERTIES (side_effect_id, name),
        Enzyme
            LABEL Enzyme
            PROPERTIES (enzyme_id, name),
        PubMedChunk
            LABEL PubMedChunk
            PROPERTIES (chunk_id, pmid, title, text)
    )
    EDGE TABLES (
        HasSideEffect
            SOURCE KEY (drug_id) REFERENCES Drug (drug_id)
            DESTINATION KEY (side_effect_id) REFERENCES SideEffect (side_effect_id)
            LABEL HAS_SIDE_EFFECT
            PROPERTIES (source),
        SubstrateOf
            SOURCE KEY (drug_id) REFERENCES Drug (drug_id)
            DESTINATION KEY (enzyme_id) REFERENCES Enzyme (enzyme_id)
            LABEL SUBSTRATE_OF
            PROPERTIES (source),
        InteractsWith
            SOURCE KEY (from_drug_id) REFERENCES Drug (drug_id)
            DESTINATION KEY (to_drug_id) REFERENCES Drug (drug_id)
            LABEL INTERACTS_WITH
            PROPERTIES (description, source)
    );

    