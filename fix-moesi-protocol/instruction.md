A MOESI_CMP_Directory cache coherence protocol simulator lives at `/app/coherence_sim/`. It models a multi-core system with private L1 caches, a banked shared L2 cache, and directory-based memory controllers. The driver is `/app/run_workload.py`. The implementation spans Python modules and a native C shared library (`libaddrcalc.so`, source in `addr_calc.c`, built via `make -C /app/coherence_sim`).

The simulator has multiple correctness defects spanning both the C and Python layers, plus a critical missing architectural feature. All source files are under `/app/coherence_sim/`.

## Observed failures

- `python3 /app/run_workload.py --cores 4 --pattern writeback-storm` crashes with an assertion failure during directory entry deallocation.

- `python3 /app/run_workload.py --cores 2 --pattern sequential --analyze-banks` reports severely imbalanced L2 bank utilization — addresses are not distributed evenly across banks, and per-bank set utilization is poor. The root causes involve multiple interacting defects that span both the C extension and the Python cache controller.

- `python3 /app/run_workload.py --cores 2 --dual-memory` shows addresses near the DRAM/HBM boundary being served by multiple memory controllers simultaneously.

- Under sustained multi-core workloads with heavy L2 eviction pressure, dirty data written by cores is silently lost. The cache hierarchy does not enforce the L2 inclusion property — when L2 evicts a line, corresponding dirty L1 copies are not handled, leading to silent data corruption.

## Required outcome

All defects must be resolved and the missing feature implemented so that:

- The 4-core writeback-storm workload completes without assertion errors.
- Sequential addresses distribute evenly across all L2 banks (coefficient of variation < 0.1), and each bank's cache sets are well-utilized (>50% of sets used per bank, no aliasing).
- In dual-memory mode, every address is served by exactly one memory controller with no range overlaps at the DRAM/HBM boundary.
- The L2 inclusion property holds under eviction pressure: every valid L1 cache line has a corresponding L2 entry, and dirty data in Modified-state L1 lines is never silently dropped during L2 evictions — it must be preserved and written back through the memory hierarchy.
- MOESI protocol invariants are maintained (e.g., no two L1 caches simultaneously hold the same line in Modified state).
- The simulator exposes a `get_protocol_traffic_report()` method on `CoherenceSimulator` returning a dict with keys: `total_messages` (int — total protocol messages processed), `messages_by_type` (dict mapping message type name string to count), `recall_events` (int — inclusion-related recall invocations), and `dirty_collections` (int — times dirty data was collected from Modified-state L1 holders). These counters must be tracked during simulation operation. Write the report from a mixed workload exercising all fixes to `/app/traffic_report.json`.

The C extension must be rebuilt after any modifications to it (`make -C /app/coherence_sim`).