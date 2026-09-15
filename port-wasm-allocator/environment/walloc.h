#ifndef WALLOC_H
#define WALLOC_H

/*
 * walloc native API — port of the walloc WebAssembly allocator to Linux.
 *
 * The original walloc (see walloc_original.c) is a standalone malloc for
 * WebAssembly linear memory.  This header declares the native API that a
 * correct port must implement.
 *
 * Key design invariants from the original:
 *   - 64 KB pages (WALLOC_PAGE_SIZE), each divided into 256-byte chunks
 *   - 8-byte granules; small objects <= 256 bytes use segregated freelists
 *   - 10 size classes: 1,2,3,4,5,6,8,10,16,32 granules
 *   - Large objects (> 256 bytes) use a best-fit freelist with lazy coalescing
 *   - The page header (chunk 0) stores a per-chunk kind byte
 */

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Initialize the allocator with initial_pages 64 KB pages of committed memory.
 * Must be called before any allocation function.
 * Returns 0 on success, -1 on failure. */
int walloc_init(size_t initial_pages);

/* Standard allocation functions */
void *walloc_malloc(size_t size);
void  walloc_free(void *ptr);
void *walloc_realloc(void *ptr, size_t size);
void *walloc_calloc(size_t nmemb, size_t size);

/* Heap statistics — all counts derived from walking internal freelists. */
struct walloc_stats {
    size_t heap_pages;              /* Total 64 KB pages managed by walloc   */
    size_t heap_size_bytes;         /* = heap_pages * 65536                  */
    size_t free_large_count;        /* Entries on large-object freelist      */
    size_t free_large_total_bytes;  /* Sum of payload sizes on that list     */
    size_t small_free_counts[10];   /* Free objects per size-class index 0-9 */
    size_t small_free_total;        /* Sum of small_free_counts[]            */
};

/* Fill *stats with current heap metrics.  Returns 0 on success, -1 if
 * the allocator has not been initialized. */
int walloc_get_stats(struct walloc_stats *stats);

/* Release all memory.  After this, walloc_init() must be called again
 * before any allocation.  Safe to call multiple times. */
void walloc_destroy(void);

#ifdef __cplusplus
}
#endif

#endif /* WALLOC_H */
