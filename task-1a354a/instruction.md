`/app/` contains a C project skeleton for a bus-snooping cache coherence simulator. Cache data structures, LRU lookup/replacement operations (`src/cache.c`), the trace-driven main loop (`src/main.c`), and statistics output (`src/simulator.c`) are complete and functional.

Implement the `process_access` function in `/app/src/protocol.c` to correctly simulate the MESI snooping protocol for a multi-processor system with private write-back, write-allocate, set-associative LRU caches on a shared bus. This function is called once per memory access and must:

- Perform cache lookups and manage LRU evictions using the API in `/app/include/cache.h`
- Implement all MESI state transitions across all processors' caches, including bus-snooped state changes
- Issue correct bus transactions (BusRd, BusRdX, BusUpgr, Flush) and maintain accurate per-processor and bus-level statistics
- Handle dirty write-back on eviction of Modified lines

Build: `make` in `/app/`. Run: `./mesi_sim <trace> [num_procs] [num_sets] [assoc] [block_size]` (defaults: 4, 4, 2, 64). Test traces are in `/app/traces/`.