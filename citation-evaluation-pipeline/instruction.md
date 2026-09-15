A LegalCiteBench evaluation environment has been set up across multiple data sources at `/app/`. The benchmark evaluates legal citation reliability in LLM outputs across three task categories (citation retrieval, citation completion, citation error detection) spanning diverse US jurisdictions and reporter systems.

The evaluation data is distributed across:
- **SQLite database** (`/app/citation_eval.db`): Instance metadata and model responses
- **JSONL manifest** (`/app/ground_truth_manifest.jsonl`): Ground truth citations in a nested annotation format
- **XML authority index** (`/app/citation_authority.xml`): Parallel citation equivalence mappings across reporter systems
- **Configuration** (`/app/scoring_config.yaml` + `/app/scoring_overrides.json`): Scoring parameters split across two files requiring reconciliation

A prior evaluation script at `/app/evaluate.py` was written for an earlier schema and fails against the current data architecture. Audit notes at `/app/audit_notes.md` and a methodology reference at `/app/evaluation_methodology.md` provide context.

Build a complete evaluation pipeline that reconciles data across all sources, resolves parallel citation equivalences using the authority index, and produces correct aggregate metrics at `/app/results.json`.