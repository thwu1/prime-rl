A size-class segregated memory allocator at `/app/allocator.c` handles allocation (`halloc`), freeing (`hfree`), reallocation (`hrealloc`), and statistics reporting (`halloc_get_stats`) for 12 size classes and large mmap-backed allocations. The API is defined in `/app/allocator.h`; build with `make -C /app`. Do not modify `allocator.h` or the `Makefile`.

The allocator is functionally correct but completely unprotected against heap exploitation. Harden `/app/allocator.c` so that:

1. **Heap buffer overflows and metadata corruption are detected at free time.** If `hfree` discovers that data has been written beyond the bounds of a small allocation, or that the allocator's internal metadata has been tampered with, it must print a diagnostic to stderr and `abort()`.

2. **Double-free is detected.** Freeing the same pointer twice must print a diagnostic to stderr and `abort()`.

3. **Freed memory is scrubbed.** When a small allocation is freed, the full size-class extent of the user region must be overwritten with `0xAB` before the chunk is recycled to the free list.

4. **Large allocations are fault-isolated.** Each allocation above the maximum size class must be surrounded by inaccessible memory that triggers a hardware fault on any access. These inaccessible regions must appear as `---p` entries in `/proc/self/maps` adjacent to the `rw-p` mapping that contains the user pointer.

5. **Statistics are accurate.** `halloc_get_stats` must correctly report `total_allocs`, `total_frees`, `bytes_allocated` (net currently allocated bytes — size-class size for small, aligned request size for large), `slab_pages` (cumulative slab pages mapped), and `large_allocs` (outstanding large allocation count).

All existing functional guarantees must be preserved: `halloc(0)` returns NULL; `hfree(NULL, 0)` is a no-op; all size classes work; returned pointers are 16-byte aligned; `hrealloc` preserves data across size transitions; throughput of 2M alloc/free operations completes within 30 seconds.