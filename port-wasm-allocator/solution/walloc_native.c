/* walloc_native.c — Native Linux port of walloc (WebAssembly malloc)
 *
 * Original walloc.c: Copyright (c) 2020 Igalia, S.L. (MIT License)
 *
 * This file adapts the WebAssembly-specific memory management to use
 * Linux mmap/mprotect while preserving the page/chunk/granule architecture.
 *
 * Changes from the original:
 *  - Replaced __builtin_wasm_memory_{size,grow} with mmap+mprotect backend
 *  - Replaced &__heap_base with the mmap'd base pointer
 *  - Replaced wasm-specific typedefs with <stdint.h>
 *  - Renamed PAGE_SIZE -> WALLOC_PAGE_SIZE (avoids Linux kernel macro clash)
 *  - Added walloc_init / walloc_destroy lifecycle functions
 *  - Added walloc_realloc / walloc_calloc / walloc_get_stats
 *  - All public symbols prefixed with walloc_
 */


#define _GNU_SOURCE
#include "walloc.h"

#include <sys/mman.h>
#include <string.h>
#include <stdint.h>

/* ================================================================
 *  Constants — unchanged from original walloc design
 * ================================================================ */

#define WALLOC_PAGE_SIZE       65536
#define WALLOC_PAGE_SIZE_LOG_2 16
#define WALLOC_PAGE_MASK       (WALLOC_PAGE_SIZE - 1)

#define CHUNK_SIZE       256
#define CHUNK_SIZE_LOG_2 8
#define CHUNK_MASK       (CHUNK_SIZE - 1)

#define CHUNKS_PER_PAGE  256

#define GRANULE_SIZE                   8
#define GRANULE_SIZE_LOG_2             3
#define LARGE_OBJECT_THRESHOLD         256
#define LARGE_OBJECT_GRANULE_THRESHOLD 32

/* Maximum virtual address space to reserve (256 MiB). */
#define MAX_HEAP_VA (256UL * 1024 * 1024)

/* ================================================================
 *  Utility macros
 * ================================================================ */

#ifdef NDEBUG
#define ASSERT(x) ((void)0)
#else
#define ASSERT(x) do { if (!(x)) __builtin_trap(); } while (0)
#endif
#define ASSERT_EQ(a,b) ASSERT((a) == (b))
#define ASSERT_ALIGNED(x, y) ASSERT((x) == w_align((x), y))

static inline size_t w_max(size_t a, size_t b) { return a < b ? b : a; }
static inline uintptr_t w_align(uintptr_t val, uintptr_t alignment) {
    return (val + alignment - 1) & ~(alignment - 1);
}

/* ================================================================
 *  Native memory backend  (replaces wasm intrinsics)
 * ================================================================ */

static char   *memory_base;       /* 64 KB-aligned start of the VA region   */
static char   *raw_mmap_base;     /* the raw mmap return (for munmap)        */
static size_t  raw_mmap_size;     /* size passed to mmap / munmap            */
static size_t  committed_pages;   /* number of 64 KB pages currently usable  */

/* Equivalent of __builtin_wasm_memory_grow(0, delta).
 * Returns old committed page count on success, (size_t)-1 on failure. */
static size_t native_memory_grow(size_t delta_pages) {
    size_t new_committed = committed_pages + delta_pages;
    if (new_committed * WALLOC_PAGE_SIZE > MAX_HEAP_VA)
        return (size_t)-1;

    char *start = memory_base + committed_pages * WALLOC_PAGE_SIZE;
    if (mprotect(start, delta_pages * WALLOC_PAGE_SIZE,
                 PROT_READ | PROT_WRITE) != 0)
        return (size_t)-1;

    size_t old = committed_pages;
    committed_pages = new_committed;
    return old;
}

/* ================================================================
 *  Data structures — identical to original walloc
 * ================================================================ */

struct chunk { char data[CHUNK_SIZE]; };

#define FOR_EACH_SMALL_OBJECT_GRANULES(M) \
    M(1) M(2) M(3) M(4) M(5) M(6) M(8) M(10) M(16) M(32)

enum chunk_kind {
#define DEF_CK(i) GRANULES_##i,
    FOR_EACH_SMALL_OBJECT_GRANULES(DEF_CK)
#undef DEF_CK
    SMALL_OBJECT_CHUNK_KINDS,
    FREE_LARGE_OBJECT = 254,
    LARGE_OBJECT      = 255
};

static enum chunk_kind granules_to_chunk_kind(unsigned g) {
#define TEST(i) if (g <= i) return GRANULES_##i;
    FOR_EACH_SMALL_OBJECT_GRANULES(TEST)
#undef TEST
    return LARGE_OBJECT;
}

static unsigned chunk_kind_to_granules(enum chunk_kind k) {
    switch (k) {
#define CK2G(i) case GRANULES_##i: return i;
        FOR_EACH_SMALL_OBJECT_GRANULES(CK2G)
#undef CK2G
        default: return 0;
    }
}

struct page_header { uint8_t chunk_kinds[CHUNKS_PER_PAGE]; };

struct page {
    union {
        struct page_header header;
        struct chunk chunks[CHUNKS_PER_PAGE];
    };
};

#define PAGE_HEADER_SIZE        ((size_t)sizeof(struct page_header))
#define FIRST_ALLOCATABLE_CHUNK 1

static struct page *get_page(void *ptr) {
    return (struct page *)(char *)(((uintptr_t)ptr) & ~WALLOC_PAGE_MASK);
}
static unsigned get_chunk_index(void *ptr) {
    return (((uintptr_t)ptr) & WALLOC_PAGE_MASK) / CHUNK_SIZE;
}

struct freelist       { struct freelist *next; };
struct large_object   { struct large_object *next; size_t size; };

#define LARGE_OBJECT_HEADER_SIZE ((size_t)sizeof(struct large_object))

static inline void *get_large_object_payload(struct large_object *o) {
    return ((char *)o) + LARGE_OBJECT_HEADER_SIZE;
}
static inline struct large_object *get_large_object(void *ptr) {
    return (struct large_object *)(((char *)ptr) - LARGE_OBJECT_HEADER_SIZE);
}

/* ================================================================
 *  Global state
 * ================================================================ */

static struct freelist    *small_object_freelists[SMALL_OBJECT_CHUNK_KINDS];
static struct large_object *large_objects;
static size_t              walloc_heap_size;
static int                 pending_large_object_compact;

/* ================================================================
 *  Core allocator — adapted from walloc.c (only memory-backend calls changed)
 * ================================================================ */

static struct page *
allocate_pages(size_t payload_size, size_t *n_allocated) {
    size_t needed = payload_size + PAGE_HEADER_SIZE;
    /* In wasm: heap_size = wasm_memory_size * PAGE_SIZE  (an absolute addr,
     * because wasm memory starts at 0).  Native equivalent: */
    uintptr_t heap_end = (uintptr_t)memory_base +
                          committed_pages * WALLOC_PAGE_SIZE;
    uintptr_t base = heap_end;
    uintptr_t preallocated = 0;
    size_t grow = 0;

    if (!walloc_heap_size) {
        uintptr_t heap_base = w_align((uintptr_t)memory_base,
                                      WALLOC_PAGE_SIZE);
        preallocated = heap_end - heap_base;
        walloc_heap_size = preallocated;
        base -= preallocated;
    }

    if (preallocated < needed) {
        grow = w_align(w_max(walloc_heap_size / 2, needed - preallocated),
                       WALLOC_PAGE_SIZE);
        if (!grow) grow = WALLOC_PAGE_SIZE;
        if (native_memory_grow(grow >> WALLOC_PAGE_SIZE_LOG_2) == (size_t)-1)
            return NULL;
        walloc_heap_size += grow;
    }

    struct page *ret = (struct page *)base;
    size_t size = grow + preallocated;
    ASSERT(size);
    ASSERT_ALIGNED(size, WALLOC_PAGE_SIZE);
    *n_allocated = size / WALLOC_PAGE_SIZE;
    return ret;
}

static char *
allocate_chunk(struct page *page, unsigned idx, enum chunk_kind kind) {
    page->header.chunk_kinds[idx] = kind;
    return page->chunks[idx].data;
}

static void maybe_repurpose_single_chunk_large_objects_head(void) {
    if (large_objects->size < CHUNK_SIZE) {
        unsigned idx = get_chunk_index(large_objects);
        char *ptr = allocate_chunk(get_page(large_objects), idx, GRANULES_32);
        large_objects = large_objects->next;
        struct freelist *head = (struct freelist *)ptr;
        head->next = small_object_freelists[GRANULES_32];
        small_object_freelists[GRANULES_32] = head;
    }
}

static struct large_object **
maybe_merge_free_large_object(struct large_object **prev) {
    struct large_object *obj = *prev;
    while (1) {
        char *end = (char *)get_large_object_payload(obj) + obj->size;
        ASSERT_ALIGNED((uintptr_t)end, CHUNK_SIZE);
        unsigned chunk = get_chunk_index(end);
        if (chunk < FIRST_ALLOCATABLE_CHUNK)
            return prev;
        struct page *page = get_page(end);
        if (page->header.chunk_kinds[chunk] != FREE_LARGE_OBJECT)
            return prev;
        struct large_object *next_obj = (struct large_object *)end;

        struct large_object **pp = &large_objects, *walk = large_objects;
        while (1) {
            ASSERT(walk);
            if (walk == next_obj) {
                obj->size += LARGE_OBJECT_HEADER_SIZE + walk->size;
                *pp = walk->next;
                if (prev == &walk->next)
                    prev = pp;
                break;
            }
            pp   = &walk->next;
            walk = walk->next;
        }
    }
}

static void maybe_compact_free_large_objects(void) {
    if (pending_large_object_compact) {
        pending_large_object_compact = 0;
        struct large_object **prev = &large_objects;
        while (*prev)
            prev = &(*maybe_merge_free_large_object(prev))->next;
    }
}

static struct large_object *
allocate_large_object(size_t size) {
    maybe_compact_free_large_objects();

    struct large_object *best = NULL, **best_prev = &large_objects;
    size_t best_size = (size_t)-1;

    for (struct large_object **prev = &large_objects, *walk = large_objects;
         walk;
         prev = &walk->next, walk = walk->next) {
        if (walk->size >= size && walk->size < best_size) {
            best_size = walk->size;
            best      = walk;
            best_prev = prev;
            if (best_size + LARGE_OBJECT_HEADER_SIZE ==
                w_align(size + LARGE_OBJECT_HEADER_SIZE, CHUNK_SIZE))
                break;                          /* exact fit */
        }
    }

    if (!best) {
        size_t size_with_header = size + sizeof(struct large_object);
        size_t n_allocated = 0;
        struct page *page = allocate_pages(size_with_header, &n_allocated);
        if (!page) return NULL;

        char *ptr = allocate_chunk(page, FIRST_ALLOCATABLE_CHUNK, LARGE_OBJECT);
        best = (struct large_object *)ptr;
        size_t page_hdr = (size_t)(ptr - (char *)page);
        best->next = large_objects;
        best->size = best_size =
            n_allocated * WALLOC_PAGE_SIZE - page_hdr - LARGE_OBJECT_HEADER_SIZE;
    }

    allocate_chunk(get_page(best), get_chunk_index(best), LARGE_OBJECT);

    struct large_object *next = best->next;
    *best_prev = next;

    size_t tail_size = (best_size - size) & ~CHUNK_MASK;
    if (tail_size) {
        struct page *start_page = get_page(best);
        char *start = (char *)get_large_object_payload(best);
        char *end   = start + best_size;

        if (start_page == get_page(end - tail_size - 1)) {
            ASSERT_ALIGNED((uintptr_t)end, CHUNK_SIZE);
        } else if (size < WALLOC_PAGE_SIZE - LARGE_OBJECT_HEADER_SIZE - CHUNK_SIZE) {
            ASSERT_ALIGNED((uintptr_t)end, WALLOC_PAGE_SIZE);
            size_t first_page_size =
                WALLOC_PAGE_SIZE - (((uintptr_t)start) & WALLOC_PAGE_MASK);
            struct large_object *head_obj = best;
            allocate_chunk(start_page, get_chunk_index(start),
                           FREE_LARGE_OBJECT);
            head_obj->size = first_page_size;
            head_obj->next = large_objects;
            large_objects = head_obj;

            maybe_repurpose_single_chunk_large_objects_head();

            struct page *next_page = start_page + 1;
            char *ptr2 = allocate_chunk(next_page, FIRST_ALLOCATABLE_CHUNK,
                                        LARGE_OBJECT);
            best = (struct large_object *)ptr2;
            best->size = best_size =
                best_size - first_page_size - CHUNK_SIZE
                - LARGE_OBJECT_HEADER_SIZE;
            ASSERT(best_size >= size);
            start     = (char *)get_large_object_payload(best);
            tail_size = (best_size - size) & ~CHUNK_MASK;
        } else {
            ASSERT_ALIGNED((uintptr_t)end, WALLOC_PAGE_SIZE);
            size_t first_page_size =
                WALLOC_PAGE_SIZE - (((uintptr_t)start) & WALLOC_PAGE_MASK);
            size_t tail_pages_size =
                w_align(size - first_page_size, WALLOC_PAGE_SIZE);
            size      = first_page_size + tail_pages_size;
            tail_size = best_size - size;
        }
        best->size -= tail_size;

        unsigned tail_idx = get_chunk_index(end - tail_size);
        while (tail_idx < FIRST_ALLOCATABLE_CHUNK && tail_size) {
            tail_size -= CHUNK_SIZE;
            tail_idx++;
        }

        if (tail_size) {
            struct page *pg = get_page(end - tail_size);
            char *tail_ptr  = allocate_chunk(pg, tail_idx, FREE_LARGE_OBJECT);
            struct large_object *tail = (struct large_object *)tail_ptr;
            tail->next = large_objects;
            tail->size = tail_size - LARGE_OBJECT_HEADER_SIZE;
            ASSERT_ALIGNED(
                (uintptr_t)((char *)get_large_object_payload(tail) + tail->size),
                CHUNK_SIZE);
            large_objects = tail;

            maybe_repurpose_single_chunk_large_objects_head();
        }
    }

    ASSERT_ALIGNED(
        (uintptr_t)((char *)get_large_object_payload(best) + best->size),
        CHUNK_SIZE);
    return best;
}

static struct freelist *
obtain_small_objects(enum chunk_kind kind) {
    struct freelist **whole = &small_object_freelists[GRANULES_32];
    void *chunk;
    if (*whole) {
        chunk  = *whole;
        *whole = (*whole)->next;
    } else {
        chunk = allocate_large_object(0);
        if (!chunk) return NULL;
    }
    char *ptr = allocate_chunk(get_page(chunk), get_chunk_index(chunk), kind);
    char *end = ptr + CHUNK_SIZE;
    struct freelist *fl = NULL;
    size_t sz = chunk_kind_to_granules(kind) * GRANULE_SIZE;
    for (size_t i = sz; i <= CHUNK_SIZE; i += sz) {
        struct freelist *h = (struct freelist *)(end - i);
        h->next = fl;
        fl = h;
    }
    return fl;
}

static inline size_t size_to_granules(size_t sz) {
    return (sz + GRANULE_SIZE - 1) >> GRANULE_SIZE_LOG_2;
}

static struct freelist **get_small_object_freelist(enum chunk_kind kind) {
    ASSERT(kind < SMALL_OBJECT_CHUNK_KINDS);
    return &small_object_freelists[kind];
}

static void *allocate_small(enum chunk_kind kind) {
    struct freelist **loc = get_small_object_freelist(kind);
    if (!*loc) {
        struct freelist *fl = obtain_small_objects(kind);
        if (!fl) return NULL;
        *loc = fl;
    }
    struct freelist *ret = *loc;
    *loc = ret->next;
    return (void *)ret;
}

static void *allocate_large(size_t size) {
    struct large_object *obj = allocate_large_object(size);
    return obj ? get_large_object_payload(obj) : NULL;
}

/* ================================================================
 *  Public API
 * ================================================================ */

int walloc_init(size_t initial_pages) {
    /* Reset global state */
    walloc_heap_size             = 0;
    large_objects                = NULL;
    pending_large_object_compact = 0;
    memset(small_object_freelists, 0, sizeof(small_object_freelists));

    if (initial_pages == 0)
        initial_pages = 1;

    /* Reserve a large VA range, then commit only the requested pages.
     * Extra room is reserved for 64 KB alignment. */
    raw_mmap_size = MAX_HEAP_VA + WALLOC_PAGE_SIZE;
    raw_mmap_base = (char *)mmap(NULL, raw_mmap_size, PROT_NONE,
                                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (raw_mmap_base == MAP_FAILED) {
        raw_mmap_base = NULL;
        return -1;
    }

    /* Align the usable base to a 64 KB boundary. */
    memory_base = (char *)w_align((uintptr_t)raw_mmap_base, WALLOC_PAGE_SIZE);

    /* Commit the initial pages. */
    if (mprotect(memory_base, initial_pages * WALLOC_PAGE_SIZE,
                 PROT_READ | PROT_WRITE) != 0) {
        munmap(raw_mmap_base, raw_mmap_size);
        raw_mmap_base = NULL;
        memory_base   = NULL;
        return -1;
    }

    committed_pages = initial_pages;
    return 0;
}

void *walloc_malloc(size_t size) {
    if (size == 0) size = 1;
    size_t granules     = size_to_granules(size);
    enum chunk_kind kind = granules_to_chunk_kind(granules);
    return (kind == LARGE_OBJECT) ? allocate_large(size) : allocate_small(kind);
}

void walloc_free(void *ptr) {
    if (!ptr) return;
    struct page *page = get_page(ptr);
    unsigned chunk    = get_chunk_index(ptr);
    uint8_t kind      = page->header.chunk_kinds[chunk];

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = get_large_object(ptr);
        obj->next    = large_objects;
        large_objects = obj;
        allocate_chunk(page, chunk, FREE_LARGE_OBJECT);
        pending_large_object_compact = 1;
    } else {
        struct freelist **loc = get_small_object_freelist(kind);
        struct freelist *obj  = (struct freelist *)ptr;
        obj->next = *loc;
        *loc      = obj;
    }
}

void *walloc_realloc(void *ptr, size_t new_size) {
    if (!ptr) return walloc_malloc(new_size);
    if (new_size == 0) { walloc_free(ptr); return NULL; }

    struct page *page = get_page(ptr);
    unsigned chunk    = get_chunk_index(ptr);
    uint8_t kind      = page->header.chunk_kinds[chunk];

    size_t old_size;
    if (kind == LARGE_OBJECT) {
        struct large_object *obj = get_large_object(ptr);
        old_size = obj->size;
        /* If shrinking within the same large allocation, keep it. */
        if (new_size <= old_size)
            return ptr;
    } else {
        unsigned g = chunk_kind_to_granules(kind);
        old_size   = g * GRANULE_SIZE;
        /* If new size fits in the same size class, no-op. */
        size_t ng          = size_to_granules(new_size);
        enum chunk_kind nk = granules_to_chunk_kind(ng);
        if (nk == kind)
            return ptr;
    }

    /* General path: malloc + copy + free */
    void *new_ptr = walloc_malloc(new_size);
    if (!new_ptr) return NULL;

    size_t copy = old_size < new_size ? old_size : new_size;
    memcpy(new_ptr, ptr, copy);
    walloc_free(ptr);
    return new_ptr;
}

void *walloc_calloc(size_t nmemb, size_t size) {
    /* Overflow check */
    size_t total = nmemb * size;
    if (nmemb != 0 && total / nmemb != size)
        return NULL;

    void *ptr = walloc_malloc(total);
    if (ptr) memset(ptr, 0, total);
    return ptr;
}

int walloc_get_stats(struct walloc_stats *stats) {
    if (!stats) return -1;
    memset(stats, 0, sizeof(*stats));

    if (!memory_base || !walloc_heap_size)
        return -1;

    stats->heap_pages      = walloc_heap_size / WALLOC_PAGE_SIZE;
    stats->heap_size_bytes = walloc_heap_size;

    /* Walk large-object freelist */
    for (struct large_object *obj = large_objects; obj; obj = obj->next) {
        stats->free_large_count++;
        stats->free_large_total_bytes += obj->size;
    }

    /* Walk small-object freelists (one per size class) */
    for (int i = 0; i < SMALL_OBJECT_CHUNK_KINDS; i++) {
        size_t count = 0;
        for (struct freelist *fl = small_object_freelists[i]; fl; fl = fl->next)
            count++;
        stats->small_free_counts[i] = count;
        stats->small_free_total    += count;
    }

    return 0;
}

void walloc_destroy(void) {
    if (raw_mmap_base) {
        munmap(raw_mmap_base, raw_mmap_size);
        raw_mmap_base = NULL;
        memory_base   = NULL;
        raw_mmap_size = 0;
    }
    committed_pages              = 0;
    walloc_heap_size             = 0;
    large_objects                = NULL;
    pending_large_object_compact = 0;
    memset(small_object_freelists, 0, sizeof(small_object_freelists));
}
