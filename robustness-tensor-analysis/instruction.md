A robustness analysis pipeline at `/app/pipeline/` evaluates ML model performance under controlled perturbation conditions. It reads data from `/app/data/benchmark.db`, runs analysis stages defined in `/app/config/workflow.yaml`, and should write a JSON report to `/app/output/report.json`.

Running `python3 /app/pipeline/run.py` currently fails. The codebase has bugs across multiple components, and two analysis stages are unimplemented stubs. The database schema, config files, taxonomy at `/app/config/taxonomy.json`, and existing code (docstrings, working stages) provide enough context to determine what each component should compute.

Fix all issues and ensure `python3 /app/pipeline/run.py` produces a complete, mathematically correct report.