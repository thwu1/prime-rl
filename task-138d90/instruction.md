A 3D object detection evaluation pipeline at `/app/` computes per-category detection metrics (AP, ATE, ASE, AOE, CDS) for autonomous driving perception data. The evaluation protocol is fully specified in `/app/spec.md`. Configuration is loaded from `/app/config/`, and data is stored in Apache Feather format under `/app/data/`. The pipeline modules live in `/app/pipeline/` with a main entry point at `/app/run_eval.py`, orchestrated via the `Makefile` at `/app/Makefile`. The codebase is a git repository with commit history showing when each module was added.

Running `make eval` produces output, but the metric values are incorrect — the pipeline contains multiple defects causing results to deviate from the specification. Audit the entire pipeline against the specification, diagnose all issues, and fix them.

Produce the following deliverables:

1. `/app/results.json` — correct evaluation metrics produced by running the fixed pipeline via `make eval`.

2. `/app/audit_report.json` — a JSON array documenting each defect found. Each entry must contain:
   - `"file"`: path to the affected source file
   - `"bug"`: description of the defect and its impact on metrics
   - `"commit_sha"`: abbreviated git commit hash that introduced the defect (use the git repository history)
   - `"severity"`: your assessment of the defect's impact on final metric quality — one of `"critical"`, `"major"`, or `"minor"`
   - `"severity_justification"`: brief explanation of why you assigned this severity level, referencing the quantitative impact on CDS or component metrics

3. `/app/pipeline_validator.py` — a standalone Python script you design that programmatically verifies the pipeline's compliance with the specification in `/app/spec.md`. Must contain at least 8 independent validation checks. When executed (`python3 /app/pipeline_validator.py`), must exit 0 if all checks pass, non-zero otherwise.