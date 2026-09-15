A distributed training simulation framework is provided at `/app/lib.py` with a custom CLI tool at `/app/dtrain` and a constraints database at `/app/constraints.db`.

Use the `dtrain` CLI to discover available strategies and their configurations:
- `./dtrain list` — lists strategy names and descriptions
- `./dtrain config <name>` — outputs JSON with ranks, layers, batches, and constraint limits
- `./dtrain schema` — shows the database schema for deeper exploration

Query `/app/constraints.db` directly with `sqlite3` to retrieve detailed strategy requirements, communication operation costs, and implementation constraints stored across the database tables. The `communication_costs` table documents the simulated time cost of each operation type in the framework.

Study the `Model` class API in `/app/lib.py` to understand the available computation primitives (`forward`, `backward`, `loss`, `update`) and communication primitives (`allgather`, `scatterreduce`, `allreduce`, `pass_to`/`receive`), as well as the storage dictionary system and memory tracking.

Implement all strategies listed by `dtrain list` as `async def` functions in `/app/strategies.py`. Each function takes a `Model` and returns it after performing one complete distributed training step. Each must:

1. Pass `Model.check()` — verifies all layer weights were updated exactly once and are complete across ranks
2. Meet the simulated time and peak memory constraints from the constraints database

Validate implementations using `./dtrain run <name>` which outputs JSON results (pipe through `jq` for readability). Profile event timelines with `./dtrain profile <name>` and use `jq` to extract per-rank summaries for optimization. A `Makefile` is provided: `make validate` runs all strategies, `make profile-<name>` shows per-rank summaries, `make constraints` shows the constraint table.