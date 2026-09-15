-- HPO Phenomizer pipeline database schema
-- Tables for ontology graph and disease annotations

CREATE TABLE IF NOT EXISTS terms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alt_ids (
    alt_id TEXT PRIMARY KEY,
    primary_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parents (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    PRIMARY KEY (child_id, parent_id)
);

CREATE TABLE IF NOT EXISTS ancestors (
    term_id TEXT NOT NULL,
    ancestor_id TEXT NOT NULL,
    PRIMARY KEY (term_id, ancestor_id)
);

CREATE TABLE IF NOT EXISTS annotations (
    disease_id TEXT NOT NULL,
    disease_name TEXT NOT NULL,
    hpo_id TEXT NOT NULL,
    qualifier TEXT DEFAULT '',
    aspect TEXT DEFAULT 'P'
);

CREATE INDEX IF NOT EXISTS idx_annotations_hpo ON annotations(hpo_id);
CREATE INDEX IF NOT EXISTS idx_annotations_disease ON annotations(disease_id);
CREATE INDEX IF NOT EXISTS idx_ancestors_term ON ancestors(term_id);
CREATE INDEX IF NOT EXISTS idx_parents_child ON parents(child_id);
