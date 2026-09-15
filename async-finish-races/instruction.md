Build a multi-tool analysis pipeline for parallel programs expressed in the Habanero async-finish computation model. Six program traces are provided at `/app/traces/trace{1..6}.json`. The model specification is at `/app/spec.md`.

Create a `Makefile` at `/app/Makefile` with phony targets `all` (default), `analyze`, `visualize`, `schedule`, and `report`. Running `make all` in `/app/` must produce every output listed below.

## Expected outputs

**`/app/results.json`** — Per-trace analysis with fields `num_steps`, `num_edges` (spawn + continue + join), `work` (sum of step costs), `span` (critical-path length), `parallelism` (work / span), and `data_races` (sorted pairs of access IDs for unordered conflicting memory accesses). Nested JSON object keyed by trace name.

**`/app/graphs/trace{1..6}.dot`** — Graphviz DOT directed graphs of each trace's computation graph. Nodes labeled `"S{id} (cost={cost})"`. Edge styles: spawn edges colored red, continue edges colored blue, join edges colored green.

**`/app/graphs/trace{1..6}.png`** — PNG renderings produced by running `dot -Tpng` on the corresponding DOT files.

**`/app/schedules/trace{1..6}.csv`** — Greedy list schedules for P=2 processors. Each step is assigned to a processor when it becomes ready (all predecessors completed) and a processor is free. Priority: bottom-level (longest weighted path from the node to any sink, inclusive of the node's own cost). Ties broken by ascending step ID. Columns: `step_id,processor,start_time,end_time`.

**`/app/schedules/summary.json`** — Per-trace schedule summary: `{"trace1": {"makespan": <int>, "processors": 2}, ...}`.

**`/app/report.json`** — Merged report combining per-trace analysis metrics with schedule summary fields (`makespan`, `processors`), assembled using `jq` to merge `/app/results.json` and `/app/schedules/summary.json`.

Available tools: `python3`, `graphviz` (`dot`), `jq`, `make`, `gcc`.