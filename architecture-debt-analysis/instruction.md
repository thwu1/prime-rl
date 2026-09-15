The architecture governance system at `/app/` evaluates structural quality of a 35-component enterprise platform. Architecture data is ingested from three heterogeneous sources:

- `/app/data/dependencies.dot` — Graphviz DOT digraph of runtime dependencies
- `/app/data/components.db` — SQLite database with component metadata (layer assignments, abstract/concrete type counts)
- `/app/data/governance.yaml` — Layer dependency constraints and fitness thresholds

The analysis pipeline at `/app/pipeline/` (entry point: `run.sh`) produces JSON governance reports in `/app/results/`: Robert C. Martin package metrics (`metrics.json`), circular dependency detection with minimum feedback arc set sizes (`cycles.json`), and layer violation detection (`violations.json`).

The pipeline executes without errors but its output is unreliable. Engineering stakeholders report that known circular dependencies and layer violations fail to appear in the reports, and computed package metrics diverge from manual spot-checks. Multiple independent defects exist in the pipeline.

Diagnose all defects, fix them, and ensure `/app/results/` contains correct governance reports.