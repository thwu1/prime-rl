Build a refactoring evaluation pipeline that processes SARIF 2.1.0 static analysis results and OpenGrep rule definitions to compute composite quality metrics for code refactoring agents.

The pipeline must produce:

1. A `jq` filter at `/app/pipeline/extract_rules.jq` that extracts distinct matched rule IDs from SARIF 2.1.0 JSON input. The filter must correctly handle: `ruleId` and `ruleIndex` resolution (including resolution against `tool.extensions[].rules` via the SARIF `toolComponent` property), suppression filtering, result qualification by `kind` and `level` fields, and cross-run deduplication.

2. A SQLite database at `/app/results/evaluation.db` with an `instance_metrics` table conforming to the schema in `/app/METHODOLOGY.md`, including phantom rule detection counts.

3. A JSON report at `/app/results/evaluation.json` with per-instance metrics (including phantom rule counts) and aggregate statistics including bootstrap 95% confidence intervals.

The pipeline must cross-validate SARIF-extracted rule IDs against YAML rule definitions to detect and exclude phantom rules — rule IDs referenced in SARIF output that do not correspond to any rule defined in the instance's YAML files.

Input data is at `/app/data/instances/`. The evaluation methodology, SARIF processing requirements, and output specifications are in `/app/METHODOLOGY.md`. The reference metric computation model is at `/app/reference/evaluation_models.py`.