A biochemical knowledge graph built from the NuBBE natural products database is provided at `/app/data/`. Validate the ontology, audit compound properties against Lipinski's Rule of Five, and evaluate two link-prediction models. Write all results to `/app/results/analysis.json`.

## Data

`/app/data/ontology.ttl` — OWL ontology (Turtle) defining a class hierarchy under prefix `<http://nubbe.db/>` via `rdfs:subClassOf`.

`/app/data/compounds.nt` — 30 compounds in N-Triples. Numeric literals use European decimal notation (comma separator, e.g. `"290,354187"`). Properties under `<http://nubbe.db/property/>`: `molecularMass`, `cLogP`, `numberOfLipinskiViolations`, `numberOfH-bondAcceptors`, `numberOfH-bondDonors`.

`/app/data/predictions/deepwalk.csv` and `node2vec.csv` — link-prediction outputs. Header: `query_id,true_target,predicted_1,...,predicted_10`.

## Required output

`/app/results/analysis.json` must contain:

**`orphan_subclass_declarations`** — array of `{"class": "<URI>", "missing_parent": "<URI>"}` for every `owl:Class` whose `rdfs:subClassOf` target is not itself declared as an `owl:Class`. Do not flag `owl:Thing`. Sort by class URI.

**`max_hierarchy_depth`** — integer depth of the deepest valid class. `owl:Thing` = 0. Only follow edges where both endpoints are declared classes (or `owl:Thing`).

**`lipinski_mismatches`** — array of `{"compound_id": <int>, "stated": <int>, "computed": <int>}` for compounds whose stated violation count disagrees with the count derived from Lipinski thresholds (MW > 500, cLogP > 5, HBD > 5, HBA > 10). Sort by compound_id.

**`deepwalk_metrics`** and **`node2vec_metrics`** — objects with `hits_at_1`, `hits_at_5`, `hits_at_10` (fraction of queries where true target is within top-k) and `mrr` (mean reciprocal rank; 0 contribution if true target absent from top-10).