A buggy implementation of the DARPA BESSPIN Scale security evaluation engine is at `/app/buggy_engine.py`. The scoring specification at `/app/spec.md` has three sections that reference missing appendices, leaving the correct behavior ambiguous. Partial known-correct output for one processor is at `/app/data/oracle_alpha.json`.

Test results for two RISC-V processors need evaluation: Processor Alpha results are in CSV files at `/app/data/test_results/`; Processor Beta results are in a SQLite database at `/app/data/beta_results.db` (examine its schema — it contains superseded runs that must be filtered). The BESSPIN coefficient weights are at `/app/data/coefficients.json`.

The buggy engine contains 5 implementation errors. You must audit the implementation against the oracle and specification, resolve the specification ambiguities using evidence from the oracle combined with the scoring philosophy described in the spec, fix all bugs, and produce corrected evaluations for both processors.

Write the following to `/app/output/`:

- `alpha_report.json` — Corrected BESSPIN Scale report for Processor Alpha (schema in spec Section 10)
- `beta_report.json` — Corrected BESSPIN Scale report for Processor Beta (same schema)
- `comparison.json` — Comparative analysis:
```json
{
  "alpha_besspin_scale": <float>,
  "beta_besspin_scale": <float>,
  "more_secure_processor": "alpha" or "beta",
  "alpha_category_advantages": ["<sorted category keys where Alpha scores strictly higher>"],
  "beta_category_advantages": ["<sorted category keys where Beta scores strictly higher>"],
  "highest_impact_category": "<category key with largest weight * |beta_score - alpha_score|>"
}
```