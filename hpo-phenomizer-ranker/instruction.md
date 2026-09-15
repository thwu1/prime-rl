The multi-component pipeline at `/app/pipeline/` processes HPO ontology data through Python, AWK, Bash, and SQLite stages to compute phenotype-disease similarity rankings. It contains bugs that span and interact across components. Fix all pipeline files so the system produces correct results.

**Pipeline:** `run_pipeline.sh` orchestrates: (1) `obo_graph.py` parses `/app/data/ontology.obo` into SQLite, (2) `load_annotations.sh` invokes `process_annotations.awk` to load `/app/data/annotations.hpoa`, (3) runs example queries via `similarity.py`. Supporting files: `schema.sql` (database tables: `terms`, `alt_ids`, `parents`, `ancestors`, `annotations`), `config.json` (file paths).

**Data:** `/app/data/ontology.obo` — OBO 1.2 with `is_a` DAG edges (some terms have multiple parents) and `alt_id` aliases. `/app/data/annotations.hpoa` — 12-column TSV: DatabaseID, DiseaseName, Qualifier, HPO_ID, Reference, Evidence, Onset, Frequency, Sex, Modifier, Aspect, Biocuration.

**After fixing, `bash /app/pipeline/run_pipeline.sh` must complete without error. The resulting database must satisfy:**
- `alt_ids` table contains ontology alt_id→primary_id mappings (alt_ids must not appear as standalone entries in `terms`)
- `ancestors` table reflects transitive closure following all parent edges in the DAG
- `annotations` table contains only Aspect=P rows with Qualifier≠NOT
- Alt_ids appearing in annotation HPO_IDs or CLI query arguments resolve to primary IDs

**`python3 /app/pipeline/similarity.py --db <db_path>` subcommands:**

**`ic TERM`** — IC = −ln(disease_count / total_diseases) after propagating annotations upward through transitive ancestors. Unannotated or universally-annotated terms: IC = 0. Output: 6-decimal float.

**`similarity T1 T2 --method M`** — `resnik`: IC of most informative common ancestor. `lin`: 2×Resnik/(IC(a)+IC(b)); 0 if denominator=0. `jc`: 1/(IC(a)+IC(b)−2×Resnik+1); self-similarity=1.0. `graphic`: ΣIC(shared ancestors)/ΣIC(union ancestors); self-similarity=1.0. All methods symmetric. Output: 6-decimal float.

**`rank QUERY --method M --combiner C`** — QUERY: comma-separated HPO IDs. Build |Q|×|D| pairwise similarity matrix; compute row-maxima and column-maxima. `funsimavg`: mean of avg-row-max and avg-col-max. `funsimmax`: max of avg-row-max and avg-col-max. `bma`: (Σrow_max+Σcol_max)/(|Q|+|D|). Output: `rank\tdisease_id\tname\tscore`, ranks 1..N, descending score, ties by disease_id ascending, 6-decimal scores. All annotated diseases must appear.

**Constraint:** Python standard library only.
