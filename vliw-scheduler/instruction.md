Implement a VLIW instruction scheduler with register allocation and a build pipeline at `/app/`.

A simplified VLIW processor has 4 functional units (**alu**, **load**, **store**, **flow**), each executing at most one instruction per cycle. Within a bundle (cycle), reads see pre-bundle state; writes take effect at end.

Three benchmark programs at `/app/programs/prog{1,2,3}.json` each contain a sequential instruction list, initial memory, and expected final memory. Program 3 uses virtual registers > 255, requiring register allocation. ISA spec: `/app/isa.py`. Simulator: `/app/simulator.py`.

## Required Files

**`/app/scheduler.py`** — Export `def schedule(instructions: list, max_registers: int = 256) -> list` returning a VLIW program (list of bundles, each a list of instructions) satisfying ALL of:

1. Produces identical memory output when simulated via `run_vliw` from `/app/simulator.py`
2. Uses only registers `0` to `max_registers - 1`
3. Achieves fewer VLIW cycles than the sequential instruction count
4. Each bundle contains at most one instruction per functional unit
5. No two instructions in the same bundle write to the same register
6. Total instruction count across all bundles equals the original sequential count (no instructions lost or duplicated)

**`/app/pipeline.py`** — Script with three subcommands invoked as `python3 /app/pipeline.py <cmd>`:

- `schedule` — runs the scheduler on all 3 programs, writes VLIW bundle JSON arrays to `/app/output/prog1_bundles.json`, `/app/output/prog2_bundles.json`, `/app/output/prog3_bundles.json`
- `dot` — generates Graphviz DOT digraph files representing instruction dependency graphs (with edges for RAW, WAR, WAW hazards and memory ordering) to `/app/output/prog1_deps.dot`, `/app/output/prog2_deps.dot`, `/app/output/prog3_deps.dot`
- `report` — produces `/app/output/report.json` with per-program entries keyed by `prog1`, `prog2`, `prog3`, each containing: `sequential_cycles` (int), `vliw_cycles` (int), `speedup` (float, must be > 1.0), `num_bundles` (int), `total_instructions` (int), `max_register` (int)

**`/app/Makefile`** — GNU Makefile with targets:

- `all` — runs `schedule`, `graphs`, `report` in order
- `schedule` — invokes `pipeline.py schedule`
- `graphs` — invokes `pipeline.py dot`, then renders each DOT file to SVG using `dot -Tsvg`, producing `/app/output/prog{1,2,3}_deps.svg`
- `report` — invokes `pipeline.py report`
- `clean` — removes `/app/output/`

The generated `report.json` must be valid JSON queryable with `jq` (e.g., `jq '.prog3.speedup' /app/output/report.json` returns a number > 1.0).

Environment tools: `python3`, `make`, `dot` (graphviz), `jq`.