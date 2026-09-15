A custom memory allocator library at `/app/libmyalloc.so` (source: `/app/myalloc.c`) was deployed as a drop-in replacement for the system allocator via `LD_PRELOAD`. It is failing in production — programs crash or exhibit incorrect behavior when running with `LD_PRELOAD=/app/libmyalloc.so`.

Diagnose all defects in the allocator source code, fix them, and recompile the library to `/app/libmyalloc.so`.

The fixed allocator must:

- Function correctly when injected via `LD_PRELOAD` into `/bin/ls`, `/bin/echo`, and `/bin/cat`
- Return pointers with at least 16-byte alignment for all requested sizes
- Efficiently reclaim and reuse freed memory — the heap must not grow without bound under sustained allocation/deallocation workloads
- Export `malloc`, `free`, `calloc`, and `realloc` as dynamic symbols with standard C semantics