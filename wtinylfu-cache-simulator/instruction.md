The cache simulator at `/app/` is broken. Fix all defects so it builds and produces correct, deterministic results.

The project uses Apache Ant for compilation, invoked through a `Makefile` that delegates to Ant targets. The simulator models a three-segment cache (window, probation, protected) with frequency-based admission control. It processes a sequential trace of integer key accesses, tracking hits, misses, and evictions. New entries enter through a window segment, may be promoted from probation to protected on access, and are subject to eviction via frequency comparison when the cache is full. A frequency sketch estimates access popularity using packed 4-bit counters with periodic aging.

**Build:** `cd /app && make`

**Run:** `java -cp /app/bin wtinylfu.CacheSimulator <trace_file> <max_size> <percent_main> <percent_main_protected>`

Arguments:
- `trace_file`: path to a file with one integer key per line
- `max_size`: maximum total cache capacity
- `percent_main`: fraction of capacity for the main space (probation + protected), e.g. 0.99
- `percent_main_protected`: fraction of the main space for the protected segment, e.g. 0.8

The window capacity equals `max_size - floor(max_size * percent_main)`.

**Required JSON output (stdout):**
```json
{"hit_count": N, "miss_count": N, "eviction_count": N, "cache_size": N, "window_keys": [...], "probation_keys": [...], "protected_keys": [...]}
```

All `*_keys` arrays must be sorted ascending. These invariants hold for correct output:
- `hit_count + miss_count` equals the trace length
- `cache_size` equals `miss_count - eviction_count`
- `cache_size` equals the sum of entries across all three key lists
- No key appears in more than one segment
- `cache_size` never exceeds `max_size`

Source files are in `/app/src/wtinylfu/`. Build configuration is in `/app/build.xml` and `/app/Makefile`. Defects span build configuration and multiple source files, including unimplemented functionality, incorrect logic, and build tool misconfiguration.

**Success:** `make` compiles without errors. The simulator produces correct, deterministic JSON matching these invariants for any valid trace and parameter combination.
