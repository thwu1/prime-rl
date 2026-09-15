A directory-based MOESI cache coherence protocol simulator is at `/app/moesi_sim/`. It models a 4-core system with private L1 caches, 4 banked L2 directory controllers, and shared main memory. The project includes a `Makefile` at `/app/Makefile` for build orchestration, a Graphviz diagram generator at `/app/gen_diagram.py`, and a sample trace workload at `/app/trace_workload.json`.

Run `make validate` to execute the built-in protocol diagnostics. Multiple checks fail, indicating correctness bugs across different protocol subsystems. Analyze the coherence implementation, identify the root causes from observed symptoms, and fix all protocol violations.

The simulator also lacks Upgrade (Upg) transaction support. When a core already holds a Shared or Owned copy and wants to write, it performs a full GetM — fetching data it already has. Implement Upgrade support so that S/O-to-M transitions use invalidation-only requests without redundant data transfer. Per-bank statistics from `get_bank_stats()` must include upgrade counts under the key `"upgrade"`.

After fixing the protocol issues, operationalize the project tooling:

- `make diagram` should generate a valid SVG protocol state transition diagram at `/app/protocol.svg` using `/app/gen_diagram.py` and Graphviz `dot`. The pipeline has tool integration issues that must be resolved, and `gen_diagram.py` must reflect all implemented protocol transitions including Upgrade.

- `make trace-report` should produce `/app/trace_report.json` with protocol statistics extracted via `jq` from a trace simulation run. The `jq` analysis pipeline has field reference issues that prevent correct output.

All coherence bugs must be fixed, the Upgrade optimization must be functional in `/app/moesi_sim/`, `/app/protocol.svg` must be a valid SVG state diagram, and `/app/trace_report.json` must contain accurate protocol statistics.