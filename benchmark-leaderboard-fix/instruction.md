A benchmark evaluation pipeline at `/app/` is designed to analyze model performance data and produce a ranked leaderboard. The pipeline is orchestrated by `/app/Makefile`, but its core processing stages are unimplemented stubs.

Running `make -C /app all` must produce a valid leaderboard at `/app/output/leaderboard.json` with correct statistical metrics, contamination analysis, cost computation, and ranking for all models in the dataset.

Explore the `/app/` directory tree thoroughly to understand the pipeline architecture, data schema, available reference materials, and processing requirements before implementing the stubs.

Constraints:
- Do not modify `/app/Makefile`, `/app/config.yaml`, `/app/eval.db`, or any file under `/app/candidates/` or `/app/docs/`.
- Each pipeline stage must produce output compatible with subsequent stages as defined by the Makefile's dependency graph.