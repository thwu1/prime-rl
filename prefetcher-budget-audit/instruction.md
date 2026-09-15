Audit the hardware storage budget of a DPC-3 (3rd Data Prefetching Championship) cache prefetcher submission. Three C++ source files at `/app/prefetchers/` implement multi-level prefetchers for L1D, L2C, and LLC data caches. The competition's storage budget rules are documented in `/app/budget_rules.txt`.

Compute the exact per-core storage budget in bits for each cache level and for the combined submission. Account for every persistent data structure (tables, arrays, circular buffer head pointers, counters) using the annotated hardware bit-widths from the source code comments — not C++ type sizes. Resolve all preprocessor macro expressions to determine actual table dimensions. The `[NUM_CPUS]` array dimension must be excluded (budget is per-core).

Write the audit results to `/app/storage_audit.json` with exactly this schema:

```json
{
    "l1d_total_bits": <int>,
    "l2c_total_bits": <int>,
    "llc_total_bits": <int>,
    "grand_total_bits": <int>,
    "budget_limit_bits": 524288,
    "compliant": <bool>,
    "over_budget_bits": <int>
}
```

Where `over_budget_bits` is 0 if compliant, or `grand_total_bits - budget_limit_bits` if not.