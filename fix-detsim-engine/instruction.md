`/app/` contains a deterministic simulation testing pipeline for a replicated state machine protocol:

- `/app/detsim/` — Discrete-event simulation engine, network simulator, buggify fault injection, deterministic RNG
- `/app/replication/` — Primary-backup log replication protocol with term-based leadership and log synchronization
- `/app/checker/` — Safety property checker for post-hoc validation of execution traces in SQLite
- `/app/campaign.py` — CLI for running parameterized fault injection campaigns from JSON configs
- `/app/harness.py` — Smoke-test harness for individual subsystems

The pipeline should verify that committed writes survive any sequence of network partitions, leader changes, and log synchronization. However, it reports zero safety violations across all seeds — despite the replication protocol containing a known committed-write durability defect.

Multiple bugs across subsystems interact to mask this defect. Fixing one bug may reveal others that were previously hidden, and the underlying protocol defect only becomes both reproducible and detectable when all masking bugs are resolved.

Diagnose and fix all bugs so that:

- The simulation engine produces identical event traces when run twice with the same seed
- Buggify fault injection produces identical decisions when run twice with the same seed
- Network partitions block traffic in both directions (symmetric)
- The safety checker correctly detects when a committed key is missing from a node's store
- Committed entries are present on all nodes after partition, heal, and sync (verified across 50 seeds)
- Writes committed by a new primary after a leader change are visible on all nodes after sync
- Uncommitted writes from a minority-partitioned former primary do not persist after sync

Then produce the following output files:

**`/app/campaign_config.json`** — A fault injection campaign configuration containing:
- A `"seeds"` object with `"start"` and `"end"` integer values covering at least 30 seeds
- A `"phases"` array where each element has an `"at"` (timestamp) and `"action"` field
- Must include at least one phase with each of these actions: `"partition"`, `"heal"`, `"write"`, `"sync"`, `"elect"`
- The campaign must produce zero violations when executed against the fixed code via: `python3 /app/campaign.py --config /app/campaign_config.json`

**`/app/results/analysis.md`** — A correctness analysis report (minimum 500 characters) covering:
- Determinism properties of the simulation
- Buggify / fault injection behavior
- Network partition semantics
- Safety and durability properties
- At least one diagnostic SQL query (`SELECT` statement) used against the trace database