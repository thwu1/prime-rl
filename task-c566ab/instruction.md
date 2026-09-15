The file `/app/walloc.c` contains **walloc**, a standalone `malloc`/`free` implementation designed for WebAssembly. It uses WebAssembly-specific intrinsics (`__builtin_wasm_memory_size`, `__builtin_wasm_memory_grow`, `extern void __heap_base`) and compiler-defined types (`__SIZE_TYPE__`, `__UINTPTR_TYPE__`, `__UINT8_TYPE__`).

Port this allocator to native Linux x86_64 and extend it with two additional functions:

1. **`walloc_malloc_usable_size(void *ptr)`**: Return the actual usable size (in bytes) of the allocation at `ptr`. For small objects, this is determined by the size class (granule count multiplied by the 8-byte granule size). For large objects, this is the payload size stored in the large object header. Return 0 for NULL.

2. **`walloc_realloc(void *ptr, size_t new_size)`**: Standard C `realloc` semantics. If `ptr` is NULL, behave like `malloc`. If `new_size` is 0 and `ptr` is non-NULL, free the allocation and return NULL. Otherwise, resize the allocation, preserving existing data up to `min(old_usable_size, new_size)` bytes. Return the same pointer if the current allocation already has sufficient capacity for `new_size` (same size class for small objects, or payload size >= new_size for large objects). Otherwise allocate new, copy, free old.

Your implementation must:
- Replace WebAssembly memory management with `mmap`-based native memory management, preserving walloc's contiguous-heap model with 64KB-aligned pages
- Preserve walloc's page (64KB) / chunk (256B) / granule (8B) layout and all invariants exactly
- Handle the 10 small-object size classes: 1, 2, 3, 4, 5, 6, 8, 10, 16, 32 granules
- Handle large objects (>256 bytes payload) with best-fit freelist, splitting, and coalescing
- Use the `walloc_` prefix for all public functions to avoid libc symbol conflicts

Place your implementation in `/app/walloc_native.c` with declarations in `/app/walloc_native.h`.

Required API in `/app/walloc_native.h`:
```c
void   walloc_init(void);
void  *walloc_malloc(size_t size);
void   walloc_free(void *ptr);
void  *walloc_realloc(void *ptr, size_t new_size);
size_t walloc_malloc_usable_size(void *ptr);
```

`walloc_init()` must be called once before any allocation.