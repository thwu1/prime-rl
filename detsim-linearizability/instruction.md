A deterministic event simulator (`dessim`) has been used to generate traces from 16 simulation runs of a 5-node primary-backup replicated register cluster. The traces, stored in a SQLite database at `/app/traces.db`, record client operations (reads/writes), cluster events (crashes, partitions, elections), and node state snapshots. The simulator's CLI tool is available as `dessim` — run `dessim --help` and `dessim schema` to learn its interface and database structure. An example fault injection config is at `/app/example_config.toml`. Run metadata is at `/app/run_metadata.json`.

The replicated register starts at value 0 on all nodes. Writes go to the current primary, which replicates synchronously to reachable secondaries. Reads return the primary's current value. On primary crash, an election promotes the secondary with the longest log. Network partitions can isolate node groups; the majority partition may elect a new primary while the old primary in the minority partition continues serving requests — a classic split-brain bug in this protocol.

Analyze all 16 runs, determine which are linearizable, classify the violation type for non-linearizable runs, and create fault injection configurations that reliably trigger failures.

**Deliverables:**

1. `/app/pipeline.py` — Replace the stub. Must connect to `/app/traces.db`, extract operation histories, check linearizability (implementing a correct checker — the register spec is: initial value 0, `write(v)` sets value to `v`, `read()` returns current value), detect split-brain periods (multiple primaries), classify each run, and write results to `/app/results.json`.

2. `/app/results.json` — JSON object keyed by run_id (as string). Each entry:
   ```json
   {"linearizable": bool, "violation": "none"|"split_brain", "has_multi_primary": bool}
   ```
   `violation` is `"split_brain"` for non-linearizable runs (this protocol's only safety bug is dual-primary under partition). `has_multi_primary` indicates whether multiple nodes held primary role simultaneously at any point. Note: multi-primary does not always imply non-linearizability.

3. `/app/fault_configs/trigger_split_brain.toml` — A valid `dessim` config that, when run with seed 7777 (`dessim run --config /app/fault_configs/trigger_split_brain.toml --db /tmp/verify.db --seed 7777`), produces a non-linearizable trace due to split-brain.

4. `/app/fault_configs/trigger_extended_split.toml` — A config that with seed 8888 produces a non-linearizable trace where at least 5 client operations execute against each of the two primaries during the split.