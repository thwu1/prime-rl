A GPU compute team needs to audit their kernel fleet's performance across two NVIDIA GPU architectures before production deployment. Application data is at `/app/`:

- `/app/architectures/*.json` — GPU architecture specifications, including configurable shared memory carve-out options that partition on-chip memory between shared memory and L1 cache
- `/app/profiling.db` — SQLite database containing kernel resource requirements, memory access patterns, and execution pipeline topology
- `/app/profiling/ncu_*.csv` — Nsight Compute profiling exports from test runs, including the shared memory carve-out used during each measurement
- `/app/report_schema.json` — Required structure and field descriptions for the audit report

Build `/app/audit.py` to produce `/app/audit_report.json` conforming to the report schema. The report must contain:

**Kernel analyses** — For each kernel on each architecture: the optimal shared memory carve-out selection, theoretical maximum occupancy with full resource utilization breakdown, coalescing efficiency for every global memory access pattern, shared memory bank conflict severity for every shared memory access pattern, and a performance diagnosis comparing measured profiling results against theoretical predictions.

**Fusion analyses** — For each adjacent kernel pair in the execution pipeline (as defined by pipeline edges in the database): determine whether a fused kernel combining both kernels' resource footprints can launch on each architecture, and if so, report the achievable occupancy.

Run: `python3 /app/audit.py`