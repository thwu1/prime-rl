A retrieval evaluation system for a CRUMB-style passage retrieval benchmark is deployed at `/opt/crumb_eval/`. The system evaluates four retrieval runs against a passage corpus with document-level relevance judgments.

The previous evaluation output at `/opt/crumb_eval/output/initial_results.json` has been flagged as incorrect by the benchmark maintainers. The evaluation methodology is specified in `/opt/crumb_eval/protocol.md`. The evaluation code is at `/opt/crumb_eval/pipeline.py`. All dataset files are under `/opt/crumb_eval/data/`.

Produce correct evaluation results at `/app/results.json` conforming to the schema in `/opt/crumb_eval/output_schema.json`.