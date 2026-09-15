Implement `/app/gc.c` conforming to the API in `/app/gc.h`, and create `/app/Makefile` to build and verify the implementation.

## `/app/gc.c`

A non-moving garbage collector managing all object types defined in `gc.h`. Object addresses must be stable across collections. The collector must reclaim all objects unreachable from the root set. Allocation functions must trigger collection when heap capacity is nearly exhausted.

Ephemeron semantics are specified in `gc.h`. The collector must correctly resolve ephemerons whose liveness depends on other ephemerons -- arbitrary interdependencies (including transitive and circular) must be handled.

`gc_get_stats()` must return accurate counts for all fields in `gc_stats_t`.

## `/app/Makefile`

GNU Makefile with these targets:

- `all` -- compiles `gc.c` into a static library `libgc.a`
- `clean` -- removes build artifacts
- `asan` -- compiles `/tests/test_basic.c` linked with your GC implementation using `-fsanitize=address`, then runs the resulting binary with `ASAN_OPTIONS=detect_leaks=0` (leak detection is handled separately by Valgrind); must exit 0. The ASan runtime must be linked so it is available at load time (e.g. static linking or `LD_PRELOAD`).
- `valgrind` -- compiles `/tests/test_basic.c` linked with your GC, runs it under Valgrind with full leak checking, and writes Valgrind XML output to `/app/valgrind-report.xml`; the run must produce zero errors and zero leaks

All test binaries must be memory-safe under both AddressSanitizer and Valgrind (zero errors, zero definitely/indirectly/possibly lost bytes after `gc_heap_destroy`).

Do not modify `/app/gc.h`.