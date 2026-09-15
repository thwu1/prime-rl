Port the `walloc` WebAssembly memory allocator (`/app/walloc_original.c`) to run on native Linux x86-64. The original is a standalone malloc implementation for WebAssembly's linear memory model, using wasm-specific intrinsics (`__builtin_wasm_memory_size`, `__builtin_wasm_memory_grow`) and the linker-defined `__heap_base` symbol.

Create `/app/walloc_native.c` implementing the API declared in `/app/walloc.h`. Your implementation must:

- Replace WebAssembly memory intrinsics with a native memory backend (e.g., `mmap`/`mprotect`), ensuring 64KB page alignment and contiguous growth semantics that mirror WebAssembly's linear memory model
- Preserve walloc's page/chunk/granule architecture: 64KB pages, 256-byte chunks, 8-byte granules, 10 small-object size classes with segregated freelists, and best-fit large-object allocation with lazy coalescing
- Implement `walloc_realloc()` — returning the same pointer when the new size fits the current allocation's size class, otherwise allocating new space, copying data, and freeing the old allocation
- Implement `walloc_calloc()` with guaranteed zero-initialization even for reused memory
- Implement `walloc_get_stats()` that walks internal freelists and reports heap metrics matching the `struct walloc_stats` layout in `/app/walloc.h`
- Implement `walloc_init()` / `walloc_destroy()` lifecycle management

Build with `make -C /app` to produce `/app/libwalloc.so`.