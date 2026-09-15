Build an analysis pipeline at `/app/` that processes Apache Flink streaming execution plan DAGs and produces an optimization report with state cost analysis, join consolidation opportunities, and async inference capacity planning.

## Environment

- Streaming execution plan DAGs: `/app/plans/*.json`
- Pipeline configuration: `/app/config.yaml`
- Report JSON Schema: `/app/output_schema.json`
- Domain reference: `/app/docs/flink_streaming_reference.md`
- Pipeline orchestration: `/app/Makefile`

## Required Outputs

Create `/app/run_optimizer.py` as the pipeline entry point (executed via `python3 /app/run_optimizer.py` from `/app/`). It must produce all of the following in `/app/output/`:

**`report.json`** -- optimization report conforming to `/app/output_schema.json`. Per plan: total join state cost across all joins, identified multi-join consolidation opportunities with state savings analysis, and async ML operator capacity requirements.

**`<plan_name>.dot`** -- Graphviz DOT source for each plan. Each graph must show all nodes (labeled with name, type, and key metrics such as rates for sources, join type and key columns for joins, QPS for async operators) and directed edges following data flow from inputs to outputs.

**`analysis.db`** -- SQLite database with three tables:
- `join_state` (`plan_name TEXT, node_id INTEGER, node_name TEXT, left_state_bytes INTEGER, right_state_bytes INTEGER, total_state_bytes INTEGER`)
- `multi_join_opportunities` (`plan_name TEXT, join_ids TEXT, common_key TEXT, source_ids TEXT, cascaded_state_bytes INTEGER, multi_join_state_bytes INTEGER, savings_bytes INTEGER, savings_percent REAL`)
- `async_ml_configs` (`plan_name TEXT, node_id INTEGER, node_name TEXT, required_queue_depth INTEGER, min_parallelism INTEGER, memory_per_subtask_bytes INTEGER, total_async_memory_bytes INTEGER`)

The Makefile at `/app/Makefile` orchestrates the pipeline: `make all` runs input validation (`jq`), analysis, DOT-to-SVG rendering (`dot`), and output validation (`check-jsonschema`).