A clinical evidence evaluation framework at `/app/` scores system submissions against multi-annotator gold data stored in a SQLite database. The pipeline comprises Python scoring modules (`/app/scorer/`), an adjudication module, bootstrap CI computation, and an R cross-validation script (`/app/validate/check_alpha.R`). The entry point is `/app/run_eval.py` and the specification is at `/app/SPEC.md`.

Peer reviewers have flagged the pipeline's results as incorrect. Your task is to conduct a full methodological and implementation review:

1. **Evaluate statistical methodology**: Determine whether each scoring component uses methods appropriate for the data characteristics described in the spec (annotator count, measurement scale, target estimand). Replace any methodologically unsound approaches with correct alternatives — this requires understanding *why* a method is wrong for the data, not just that it produces a different number.

2. **Fix implementation defects**: The pipeline contains bugs across multiple modules — some with effects that silently propagate across component boundaries. Trace the full data flow from database loading through final output to find all defects.

3. **Design and implement missing components**: The weighted alignment scorer and a pipeline diagnostics module (threshold sensitivity analysis and scoring consistency validation) are unimplemented. Design and build both according to the spec.

Produce correct output via `python3 /app/run_eval.py --output /app/output/scores.json`.