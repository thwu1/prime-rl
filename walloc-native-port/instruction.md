`/app/walloc_original.c` contains `walloc`, a compact memory allocator (~470 LOC) built exclusively for WebAssembly. It uses WASM-specific primitives (`__builtin_wasm_memory_grow`, `__builtin_wasm_memory_size`) and bare-metal type definitions with no native Linux equivalents.

Port this allocator to x86-64 Linux, preserving its internal architecture: 64KB page management, 256-byte chunk metadata, segregated freelists for 10 small-object size classes, and large-object allocation with chunk coalescing. The WASM linear memory model must be replaced with an `mmap`-backed arena. Write `/app/walloc_native.c` and `/app/walloc_native.h`.

The library must compile with:
```
gcc -shared -fPIC -O2 -DNDEBUG -o libwalloc.so walloc_native.c
```

Required public API (`/app/walloc_native.h`):

- `walloc_init()` / `walloc_destroy()` — lifecycle; destroy must release all resources and reset global state so a fresh `walloc_init()` works correctly
- `walloc_malloc(size)` / `walloc_free(ptr)` — allocation and deallocation preserving the original's size-class behavior
- `walloc_realloc(ptr, size)` — resize with data preservation and in-place large-object growth when adjacent free chunks exist; `realloc(NULL, n)` acts as malloc, `realloc(p, 0)` acts as free returning NULL
- `walloc_calloc(nmemb, size)` — zeroed allocation with overflow check
- `walloc_get_stats(struct walloc_stats *)` — fields: `total_allocated_bytes`, `total_freed_bytes`, `current_live_bytes`, `peak_live_bytes`, `num_pages`, `fragmentation_ratio` (`1.0 - current_live / total_managed`). Track allocator-internal sizes, not raw user-requested sizes.