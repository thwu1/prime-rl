Annotation data from the SemTab 2025 Semantic Web Challenge (tabular data to knowledge graph matching) is at `/opt/semtab_data/`. Multiple systems submitted entity and type annotations for CSV tables against a knowledge graph.

Create `/app/evaluate.py` (accepting `--data-dir` and `--output` arguments) that evaluates all systems and writes results to `/app/results.json`.

The output must conform to `/opt/semtab_data/schema.json` and match the verified reference values at `/opt/semtab_data/reference.json` (tolerance: 1e-4). Explore `/opt/semtab_data/` to understand the dataset.