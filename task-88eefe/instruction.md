Implement a kernel driver patch quality evaluation tool that faithfully reproduces the scoring methodology described in the DRIVEBENCH research paper. Excerpts from the paper's methodology, metrics, and results sections are provided at `/app/paper/`.

Study the paper excerpts to understand the full evaluation pipeline — your implementation must precisely match the paper's approach including all formulas, metric categories, and composite weighting.

**Inputs**: Test cases at `/app/cases/<name>/`, each containing `base.c` (original driver), `reference.c` (ground-truth patch), `candidate.c` (generated patch), and `metadata.json`.

**CLI**: `python3 /app/scorer.py /app/cases/<name>` (single case, JSON to stdout) or `python3 /app/scorer.py /app/cases /app/results.json` (batch, JSON to file).

**Single-case output**:

```json
{
  "ast_similarity": "<float 0-1>",
  "function_accuracy": "<float 0-1>",
  "call_accuracy": "<float 0-1>",
  "node_accuracy": "<float 0-1>",
  "variable_accuracy": "<float 0-1>",
  "composite_score": "<float 0-1>",
  "migration_type": "<string>",
  "changed_symbols": {"added": [], "removed": [], "modified": []},
  "node_type_details": {"<type>": {"delta_ref": "<int>", "delta_gen": "<int>", "similarity": "<float>"}}
}
```

**Batch output**: `{"cases": {"<name>": {...}, ...}}`

Valid `migration_type` values: `rename`, `api_migration`, `deprecation`, `structural`, `refactor`. `changed_symbols` tracks structural differences between `base.c` and `reference.c`. The implementation must handle C source containing preprocessor macros and generalize to arbitrary driver cases beyond the provided set.

After building the scorer, run it in batch mode to produce `/app/results.json`.