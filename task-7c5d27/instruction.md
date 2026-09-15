Implement a MESI cache coherence protocol simulator per the specification at `/app/spec.md`.

The simulator must process multi-core memory access traces and produce exact cache
statistics including per-core hit/miss counts, coherence invalidations, writebacks,
bus transactions, and memory access counts.

**Required outputs:**

1. `/app/output/stats.json` — Run the simulator on `/app/traces/workload.trace` using
   the baseline configuration (4 cores, 2KB L1 per core, 4-way set-associative, 64-byte
   lines). Output complete statistics in the format specified in `/app/spec.md`.

2. `/app/output/min_size.json` — Perform a design-space sweep over L1 cache sizes
   {512, 1024, 2048, 4096, 8192, 16384, 32768} bytes with 4-way associativity and
   64-byte lines on the same workload trace. Find the minimum cache size where overall
   miss rate drops below 10%. Report the size, its miss rate, and the miss rate at half
   that size.

A small test vector trace at `/app/traces/test_vector.trace` with expected results in
the spec can be used for self-validation.