Ramulator 2.0, a cycle-accurate DRAM simulator, is cloned at `/app/ramulator2/`. Build it from source with CMake so that the `ramulator2` binary is produced at `/app/ramulator2/ramulator2` (or `/app/ramulator2/build/ramulator2`).

## FCFS Scheduler Plugin

Implement a new FCFS (First-Come-First-Served) scheduler as a C++ source file placed under `/app/ramulator2/src/dram_controller/impl/scheduler/`. The scheduler must:

- Inherit from the `IScheduler` interface.
- Register with Ramulator's self-registering factory via the `RAMULATOR_REGISTER_IMPLEMENTATION` macro under the name `"FCFS"`.
- Implement a `compare` method that orders requests purely by arrival time (the request's `arrive` field), without First-Ready reordering.
- Be added to `/app/ramulator2/src/dram_controller/CMakeLists.txt` so the build system compiles it.

Rebuild Ramulator 2.0 after adding the scheduler.

## Experimental Configuration

All simulations use: DDR4_8Gb_x8 / DDR4_2400R / 1 channel / 1 rank / ClosedRowPolicy(cap=4) / RoBaRaCoCh / RandomTranslation(max_addr=2147483648) / SimpleO3 frontend (100,000 expected instructions).

Two workload traces are required (SimpleO3 format: each line is space-separated `<distance> <address>`, at least 1000 lines each). Save them to `/app/traces/`:

- **`sequential.trace`**: distance=10, byte addresses starting at 0 and incrementing by 64.
- **`random.trace`**: distance=10, addresses from Python `random.getrandbits(30)` with `random.seed(42)`.

Run 4 simulations — {FRFCFS, FCFS} × {sequential, random} — and save each run's stdout to `/app/sim_output/{scheduler}_{workload}.txt` (e.g., `frfcfs_sequential.txt`). Each output must contain Ramulator's DRAM controller statistics including `row_hits_0` and `row_misses_0`.

## Output

Write `/app/results.json` with all integer fields as JSON integers and float fields as JSON numbers:

```json
{
  "timing_analysis": {
    "org": "DDR4_8Gb_x8",
    "timing": "DDR4_2400R",
    "nRRDS": "<int>", "nRRDL": "<int>", "nFAW": "<int>",
    "nRFC": "<int>", "nREFI": "<int>", "tCK_ps": "<int>",
    "read_latency_cycles": "<int>",
    "rank_rd_to_wr_cycles": "<int>",
    "rank_wr_to_rd_cycles": "<int>"
  },
  "simulations": {
    "frfcfs_sequential": {"row_hits": "<int>", "row_misses": "<int>", "row_conflicts": "<int>"},
    "fcfs_sequential": {"row_hits": "<int>", "row_misses": "<int>", "row_conflicts": "<int>"},
    "frfcfs_random": {"row_hits": "<int>", "row_misses": "<int>", "row_conflicts": "<int>"},
    "fcfs_random": {"row_hits": "<int>", "row_misses": "<int>", "row_conflicts": "<int>"}
  },
  "evaluation": {
    "sequential_optimal_scheduler": "<FRFCFS or FCFS>",
    "random_optimal_scheduler": "<FRFCFS or FCFS>",
    "frfcfs_row_hit_advantage_random_pct": "<float>",
    "design_rationale": "<string>"
  }
}
```

Timing analysis values must match Ramulator 2.0's internal computations for this DDR4 configuration — derive them from the simulator's source code, not from external references. Simulation statistics (`row_hits`, `row_misses`, `row_conflicts`) must be parsed from the simulator's raw output and must match the values in the corresponding `/app/sim_output/` files.

For the evaluation: FRFCFS should be identified as optimal for random workloads — its First-Ready policy avoids scheduling timing-blocked commands and opportunistically exploits row buffer hits, so FRFCFS must achieve >= row hits compared to FCFS for random workloads. `frfcfs_row_hit_advantage_random_pct` must be >= 0. The `design_rationale` must substantively explain scheduling trade-offs (at least 40 characters). The optimal scheduler selection must be consistent with the reported row hit metrics.