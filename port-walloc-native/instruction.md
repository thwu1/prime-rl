`/app/walloc.c` is a ~460-line segregated-freelist `malloc` implementation designed for WebAssembly. It manages memory in 64KB pages divided into 256-byte chunks, with 10 small-object size classes (8 to 256 bytes via 8-byte granule increments) and a best-fit large-object freelist with lazy compaction. Page headers (one byte per chunk) store allocation metadata used to identify object types and sizes.

The allocator relies on three WebAssembly-specific primitives: `__builtin_wasm_memory_grow` / `__builtin_wasm_memory_size` for extending linear memory, and the linker-provided `extern void __heap_base` symbol marking the start of usable heap space. The `get_page()` function uses `ptr & ~0xFFFF` to locate page headers, which requires all managed pages to be 64KB-aligned.

Port this allocator to native Linux x86_64 and extend it with `realloc` and `malloc_usable_size`.

## Deliverables

Create `/app/walloc_native.c` and `/app/walloc_native.h` implementing:

- `void* walloc_malloc(size_t size)`
- `void walloc_free(void *ptr)`
- `void* walloc_realloc(void *ptr, size_t new_size)`
- `size_t walloc_malloc_usable_size(void *ptr)`

The port must replace WebAssembly memory primitives with `mmap`-based memory management while maintaining 64KB page alignment and preserving the original allocation algorithm (segregated freelists, page/chunk metadata, large-object best-fit with lazy compaction).

The result must compile as a shared library: `gcc -shared -fPIC -O2 -DNDEBUG -o /app/libwalloc_native.so /app/walloc_native.c`

`walloc_realloc` must correctly handle: NULL ptr (acts as malloc), zero size (acts as free, returns NULL), same small-object size class (returns same pointer), cross-class transitions preserving data, and large-object grow/shrink.

`walloc_malloc_usable_size` must return the actual usable allocation size: for small objects, the size class in bytes (`granules * 8`); for large objects, the `size` field from the large-object header.