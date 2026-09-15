#pragma once


#include <stddef.h>

/**
 * Hardened memory allocator public API.
 *
 * - halloc_init() must be called before any allocation.
 * - halloc(size) returns a 16-byte-aligned pointer or NULL.
 * - hfree(ptr, size) frees; size must match the original halloc() argument.
 * - hrealloc(ptr, old_size, new_size) reallocates, preserving min(old, new) bytes.
 * - halloc_get_stats(stats) populates the stats struct with current counters.
 */

void halloc_init(void);
void *halloc(size_t size);
void hfree(void *ptr, size_t size);
void *hrealloc(void *ptr, size_t old_size, size_t new_size);

typedef struct {
    size_t total_allocs;      /* cumulative halloc() calls that returned non-NULL */
    size_t total_frees;       /* cumulative successful hfree() calls (non-NULL ptr) */
    size_t bytes_allocated;   /* currently allocated bytes (by size-class for small, aligned size for large) */
    size_t slab_pages;        /* total slab pages currently mapped */
    size_t large_allocs;      /* current number of outstanding large allocations */
} halloc_stats_t;

void halloc_get_stats(halloc_stats_t *stats);
