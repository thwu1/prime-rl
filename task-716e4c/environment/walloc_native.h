#ifndef WALLOC_NATIVE_H
#define WALLOC_NATIVE_H

#include <stddef.h>
#include <stdint.h>

/*
 * walloc_native: A native (Linux) port of the walloc WebAssembly memory allocator
 * with additional features: realloc, calloc, heap statistics, and heap validation.
 *
 * The original walloc is a bare-bones malloc/free implementation for WebAssembly
 * targets, using 64KB pages, 256-byte chunks, and segregated freelists for small
 * objects. This native port replaces WASM memory primitives (memory.size,
 * memory.grow) with mmap-based memory management while preserving the exact
 * allocation algorithm: page headers, chunk-based allocation, 10 small-object
 * size classes, and best-fit large object allocation with lazy coalescing.
 *
 * Size classes (granule = 8 bytes):
 *   1, 2, 3, 4, 5, 6, 8, 10, 16, 32 granules
 *   i.e. 8, 16, 24, 32, 40, 48, 64, 80, 128, 256 bytes
 *
 * Objects > 256 bytes are large objects with best-fit freelist allocation.
 *
 * Implement all functions declared below in walloc_native.c.
 * Compile as a shared library:
 *   gcc -shared -fPIC -O2 -I/app -o libwalloc.so walloc_native.c
 */

/* Initialize the allocator. Reserves up to max_heap_size bytes of virtual
 * address space using mmap. The region must be 64KB-aligned to match walloc's
 * page structure. Initially commits one 64KB page. */
void walloc_init(size_t max_heap_size);

/* Release all memory and reset allocator state. */
void walloc_destroy(void);

/* Allocate size bytes. Returns a pointer aligned to at least 8 bytes,
 * or NULL on failure. Uses walloc's segregated freelist for small objects
 * (<=256 bytes) and best-fit large object allocation for larger sizes. */
void *walloc_malloc(size_t size);

/* Free a previously allocated pointer. NULL is a no-op. */
void walloc_free(void *ptr);

/* Resize an allocation. Semantics:
 * - realloc(NULL, size) behaves like malloc(size)
 * - realloc(ptr, 0): frees ptr, returns NULL
 * - For small objects: returns same pointer if new size fits same size class
 * - For large objects: returns same pointer if shrinking
 * - Otherwise: allocates new block, copies data, frees old block
 * Data up to min(old_size, new_size) is preserved. */
void *walloc_realloc(void *ptr, size_t size);

/* Allocate nmemb * size bytes, zeroed. Returns NULL on overflow or failure. */
void *walloc_calloc(size_t nmemb, size_t size);

/* Heap diagnostic statistics. */
typedef struct {
    size_t heap_pages;        /* Total 64KB pages managed by the allocator */
    size_t large_obj_count;   /* Number of currently allocated large objects */
    size_t large_obj_bytes;   /* Total payload bytes in allocated large objects */
    size_t small_obj_count;   /* Number of currently allocated small objects */
    size_t free_large_bytes;  /* Total bytes on the large object free list */
    size_t free_small_count;  /* Number of entries on small object free lists */
} walloc_stats_t;

/* Populate stats with current heap state. */
void walloc_get_stats(walloc_stats_t *stats);

/* Validate internal heap consistency by walking free lists and checking
 * page header metadata. Returns 1 if valid, 0 if corruption detected.
 * Checks: free list entries are within heap bounds, page headers match
 * free list state, alignment invariants hold, no free list cycles. */
int walloc_validate_heap(void);

#endif /* WALLOC_NATIVE_H */
