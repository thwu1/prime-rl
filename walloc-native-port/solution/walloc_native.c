/*
 * walloc_native.c: Native Linux port of walloc (WebAssembly memory allocator)
 *
 * Original by Andy Wingo, (c) 2020 Igalia, S.L. (MIT License)
 * Ported to native Linux with mmap arena backend.
 * Added: walloc_init/destroy, realloc (with in-place large-object growth),
 *        calloc, memory statistics.
 *
 */

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <sys/mman.h>
#include "walloc_native.h"

/* ------------------------------------------------------------------ */
/*  Utilities                                                          */
/* ------------------------------------------------------------------ */

#ifndef NDEBUG
#define ASSERT(x) do { if (!(x)) __builtin_trap(); } while (0)
#else
#define ASSERT(x) do { (void)0; } while (0)
#endif
#define ASSERT_EQ(a, b) ASSERT((a) == (b))

static inline size_t max_sz(size_t a, size_t b) { return a < b ? b : a; }

static inline uintptr_t align_up(uintptr_t val, uintptr_t alignment) {
    return (val + alignment - 1) & ~(alignment - 1);
}

#define ASSERT_ALIGNED(x, y) ASSERT((x) == align_up((x), (y)))

/* ------------------------------------------------------------------ */
/*  Constants — same as original walloc                                */
/* ------------------------------------------------------------------ */

#define CHUNK_SIZE           256
#define CHUNK_SIZE_LOG_2     8
#define CHUNK_MASK           (CHUNK_SIZE - 1)

/* Renamed to avoid conflict with Linux PAGE_SIZE (4096). */
#define WPAGE_SIZE           65536
#define WPAGE_SIZE_LOG_2     16
#define WPAGE_MASK           (WPAGE_SIZE - 1)

#define CHUNKS_PER_PAGE      256     /* WPAGE_SIZE / CHUNK_SIZE */

#define GRANULE_SIZE         8
#define GRANULE_SIZE_LOG_2   3
#define LARGE_OBJECT_THRESHOLD       256
#define LARGE_OBJECT_GRANULE_THRESHOLD 32

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

struct chunk { char data[CHUNK_SIZE]; };

#define FOR_EACH_SMALL_OBJECT_GRANULES(M) \
    M(1) M(2) M(3) M(4) M(5) M(6) M(8) M(10) M(16) M(32)

enum chunk_kind {
#define DEFINE_SMALL_OBJECT_CHUNK_KIND(i) GRANULES_##i,
    FOR_EACH_SMALL_OBJECT_GRANULES(DEFINE_SMALL_OBJECT_CHUNK_KIND)
#undef DEFINE_SMALL_OBJECT_CHUNK_KIND
    SMALL_OBJECT_CHUNK_KINDS,
    FREE_LARGE_OBJECT = 254,
    LARGE_OBJECT      = 255
};

static enum chunk_kind granules_to_chunk_kind(unsigned granules) {
#define TEST_GRANULE_SIZE(i) if (granules <= i) return GRANULES_##i;
    FOR_EACH_SMALL_OBJECT_GRANULES(TEST_GRANULE_SIZE);
#undef TEST_GRANULE_SIZE
    return LARGE_OBJECT;
}

static unsigned chunk_kind_to_granules(enum chunk_kind kind) {
    switch (kind) {
#define CHUNK_KIND_GRANULE_SIZE(i) case GRANULES_##i: return i;
    FOR_EACH_SMALL_OBJECT_GRANULES(CHUNK_KIND_GRANULE_SIZE);
#undef CHUNK_KIND_GRANULE_SIZE
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
    return (struct page *)(void *)(((uintptr_t)ptr) & ~((uintptr_t)WPAGE_MASK));
}
static unsigned get_chunk_index(void *ptr) {
    return (unsigned)((((uintptr_t)ptr) & WPAGE_MASK) / CHUNK_SIZE);
}

struct freelist { struct freelist *next; };

struct large_object {
    struct large_object *next;
    size_t size;                     /* payload size (after header) */
};

#define LARGE_OBJECT_HEADER_SIZE ((size_t)sizeof(struct large_object))

static inline void *get_large_object_payload(struct large_object *obj) {
    return ((char *)obj) + LARGE_OBJECT_HEADER_SIZE;
}
static inline struct large_object *get_large_object(void *ptr) {
    return (struct large_object *)(((char *)ptr) - LARGE_OBJECT_HEADER_SIZE);
}

/* ------------------------------------------------------------------ */
/*  Global state                                                       */
/* ------------------------------------------------------------------ */

static struct freelist  *small_object_freelists[SMALL_OBJECT_CHUNK_KINDS];
static struct large_object *large_objects;
static int               pending_large_object_compact;

/* Arena — replaces WASM linear memory */
#define ARENA_MAX_SIZE  (256ULL * 1024 * 1024)   /* 256 MiB virtual */

static void   *arena_raw;           /* raw mmap ptr (for munmap)     */
static size_t  arena_raw_size;      /* raw mmap size                 */
static void   *arena_base;          /* WPAGE_SIZE-aligned base       */
static size_t  walloc_heap_size;    /* bytes committed from arena    */

/* Statistics */
static size_t  stats_total_alloc;
static size_t  stats_total_freed;
static size_t  stats_current_live;
static size_t  stats_peak_live;

/* ------------------------------------------------------------------ */
/*  Arena / page allocation (replaces WASM memory.size / memory.grow)  */
/* ------------------------------------------------------------------ */

static struct page *
allocate_pages(size_t payload_size, size_t *n_allocated) {
    size_t needed = payload_size + PAGE_HEADER_SIZE;
    size_t grow;

    if (!walloc_heap_size)
        grow = align_up(max_sz((size_t)WPAGE_SIZE, needed), WPAGE_SIZE);
    else
        grow = align_up(max_sz(walloc_heap_size / 2, needed), WPAGE_SIZE);

    if (walloc_heap_size + grow > ARENA_MAX_SIZE)
        return NULL;

    struct page *ret =
        (struct page *)((char *)arena_base + walloc_heap_size);
    /* Fresh pages are already zeroed by mmap(MAP_ANONYMOUS). */
    walloc_heap_size += grow;

    ASSERT(grow);
    ASSERT_ALIGNED(grow, WPAGE_SIZE);
    *n_allocated = grow / WPAGE_SIZE;
    return ret;
}

/* ------------------------------------------------------------------ */
/*  Chunk helpers                                                      */
/* ------------------------------------------------------------------ */

static char *
allocate_chunk(struct page *page, unsigned idx, enum chunk_kind kind) {
    page->header.chunk_kinds[idx] = (uint8_t)kind;
    return page->chunks[idx].data;
}

/* ------------------------------------------------------------------ */
/*  Large-object management (unchanged from original walloc logic)     */
/* ------------------------------------------------------------------ */

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
            pp = &walk->next;
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
            best = walk;
            best_prev = prev;
            if (best_size + LARGE_OBJECT_HEADER_SIZE
                == align_up(size + LARGE_OBJECT_HEADER_SIZE, CHUNK_SIZE))
                break;
        }
    }

    if (!best) {
        size_t size_with_header = size + LARGE_OBJECT_HEADER_SIZE;
        size_t n_allocated = 0;
        struct page *page = allocate_pages(size_with_header, &n_allocated);
        if (!page) return NULL;

        char *ptr = allocate_chunk(page, FIRST_ALLOCATABLE_CHUNK, LARGE_OBJECT);
        best = (struct large_object *)ptr;
        size_t page_hdr = (size_t)(ptr - (char *)page);
        best->next = large_objects;
        best->size = best_size =
            n_allocated * WPAGE_SIZE - page_hdr - LARGE_OBJECT_HEADER_SIZE;
        ASSERT(best_size >= size);
    }

    allocate_chunk(get_page(best), get_chunk_index(best), LARGE_OBJECT);

    struct large_object *next = best->next;
    *best_prev = next;

    size_t tail_size = (best_size - size) & ~(size_t)CHUNK_MASK;
    if (tail_size) {
        struct page *start_page = get_page(best);
        char *start = (char *)get_large_object_payload(best);
        char *end   = start + best_size;

        if (start_page == get_page(end - tail_size - 1)) {
            ASSERT_ALIGNED((uintptr_t)end, CHUNK_SIZE);
        } else if (size < WPAGE_SIZE - LARGE_OBJECT_HEADER_SIZE - CHUNK_SIZE) {
            ASSERT_ALIGNED((uintptr_t)end, WPAGE_SIZE);
            size_t first_page_size =
                WPAGE_SIZE - (((uintptr_t)start) & WPAGE_MASK);
            struct large_object *head = best;
            allocate_chunk(start_page, get_chunk_index(start),
                           FREE_LARGE_OBJECT);
            head->size = first_page_size;
            head->next = large_objects;
            large_objects = head;
            maybe_repurpose_single_chunk_large_objects_head();

            struct page *next_page = start_page + 1;
            char *ptr = allocate_chunk(next_page,
                                       FIRST_ALLOCATABLE_CHUNK, LARGE_OBJECT);
            best = (struct large_object *)ptr;
            best->size = best_size =
                best_size - first_page_size - CHUNK_SIZE
                - LARGE_OBJECT_HEADER_SIZE;
            ASSERT(best_size >= size);
            start = (char *)get_large_object_payload(best);
            tail_size = (best_size - size) & ~(size_t)CHUNK_MASK;
        } else {
            ASSERT_ALIGNED((uintptr_t)end, WPAGE_SIZE);
            size_t first_page_size =
                WPAGE_SIZE - (((uintptr_t)start) & WPAGE_MASK);
            size_t tail_pages_size =
                align_up(size - first_page_size, WPAGE_SIZE);
            size = first_page_size + tail_pages_size;
            tail_size = best_size - size;
        }
        best->size -= tail_size;

        unsigned tail_idx = get_chunk_index(end - tail_size);
        while (tail_idx < FIRST_ALLOCATABLE_CHUNK && tail_size) {
            tail_size -= CHUNK_SIZE;
            tail_idx++;
        }

        if (tail_size) {
            struct page *page = get_page(end - tail_size);
            char *tail_ptr =
                allocate_chunk(page, tail_idx, FREE_LARGE_OBJECT);
            struct large_object *tail = (struct large_object *)tail_ptr;
            tail->next = large_objects;
            tail->size = tail_size - LARGE_OBJECT_HEADER_SIZE;
            ASSERT_ALIGNED(
                (uintptr_t)((char *)get_large_object_payload(tail)
                            + tail->size),
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

/* ------------------------------------------------------------------ */
/*  Small-object management                                            */
/* ------------------------------------------------------------------ */

static struct freelist *
obtain_small_objects(enum chunk_kind kind) {
    struct freelist **whole =
        &small_object_freelists[GRANULES_32];
    void *chunk;
    if (*whole) {
        chunk = *whole;
        *whole = (*whole)->next;
    } else {
        chunk = allocate_large_object(0);
        if (!chunk) return NULL;
    }
    char *ptr = allocate_chunk(get_page(chunk),
                               get_chunk_index(chunk), kind);
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

static inline size_t size_to_granules(size_t size) {
    return (size + GRANULE_SIZE - 1) >> GRANULE_SIZE_LOG_2;
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

/* ------------------------------------------------------------------ */
/*  Freelist removal helper (for realloc in-place growth)              */
/* ------------------------------------------------------------------ */

static void remove_from_large_freelist(struct large_object *target) {
    struct large_object **prev = &large_objects;
    while (*prev) {
        if (*prev == target) { *prev = target->next; return; }
        prev = &(*prev)->next;
    }
}

/* ------------------------------------------------------------------ */
/*  Public API                                                         */
/* ------------------------------------------------------------------ */

void walloc_init(void) {
    arena_raw_size = ARENA_MAX_SIZE + WPAGE_SIZE;
    arena_raw = mmap(NULL, arena_raw_size,
                     PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (arena_raw == MAP_FAILED) abort();
    arena_base = (void *)align_up((uintptr_t)arena_raw, WPAGE_SIZE);

    walloc_heap_size = 0;
    memset(small_object_freelists, 0, sizeof(small_object_freelists));
    large_objects = NULL;
    pending_large_object_compact = 0;

    stats_total_alloc  = 0;
    stats_total_freed  = 0;
    stats_current_live = 0;
    stats_peak_live    = 0;
}

void walloc_destroy(void) {
    if (arena_raw) {
        munmap(arena_raw, arena_raw_size);
        arena_raw      = NULL;
        arena_base     = NULL;
        arena_raw_size = 0;
    }
    walloc_heap_size = 0;
    memset(small_object_freelists, 0, sizeof(small_object_freelists));
    large_objects = NULL;
    pending_large_object_compact = 0;
    stats_total_alloc  = 0;
    stats_total_freed  = 0;
    stats_current_live = 0;
    stats_peak_live    = 0;
}

void *walloc_malloc(size_t size) {
    if (!size) return NULL;

    size_t granules = size_to_granules(size);
    enum chunk_kind kind = granules_to_chunk_kind(granules);
    void  *ptr;
    size_t usable = 0;

    if (kind == LARGE_OBJECT) {
        ptr = allocate_large(size);
        if (ptr) usable = get_large_object(ptr)->size;
    } else {
        ptr = allocate_small(kind);
        if (ptr) usable = chunk_kind_to_granules(kind) * GRANULE_SIZE;
    }

    if (ptr) {
        stats_total_alloc  += usable;
        stats_current_live += usable;
        if (stats_current_live > stats_peak_live)
            stats_peak_live = stats_current_live;
    }
    return ptr;
}

void walloc_free(void *ptr) {
    if (!ptr) return;

    struct page *page = get_page(ptr);
    unsigned chunk_idx = get_chunk_index(ptr);
    uint8_t kind = page->header.chunk_kinds[chunk_idx];
    size_t usable;

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = get_large_object(ptr);
        usable = obj->size;
        obj->next = large_objects;
        large_objects = obj;
        allocate_chunk(page, chunk_idx, FREE_LARGE_OBJECT);
        pending_large_object_compact = 1;
    } else {
        usable = chunk_kind_to_granules((enum chunk_kind)kind) * GRANULE_SIZE;
        struct freelist **loc = get_small_object_freelist((enum chunk_kind)kind);
        struct freelist *fl = (struct freelist *)ptr;
        fl->next = *loc;
        *loc = fl;
    }

    stats_total_freed  += usable;
    stats_current_live -= usable;
}

void *walloc_realloc(void *ptr, size_t new_size) {
    if (!ptr)      return walloc_malloc(new_size);
    if (!new_size) { walloc_free(ptr); return NULL; }

    struct page *page = get_page(ptr);
    unsigned chunk_idx = get_chunk_index(ptr);
    uint8_t  kind = page->header.chunk_kinds[chunk_idx];

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = get_large_object(ptr);
        size_t old_usable = obj->size;

        /* ---- Shrinking ---- */
        if (new_size <= old_usable) {
            /* Transition to small if the new size fits a small class. */
            size_t ng = size_to_granules(new_size);
            enum chunk_kind nk = granules_to_chunk_kind(ng);
            if (nk != LARGE_OBJECT) {
                void *np = walloc_malloc(new_size);
                if (!np) return ptr;
                memcpy(np, ptr, new_size);
                walloc_free(ptr);
                return np;
            }
            return ptr;          /* stay large, keep same pointer */
        }

        /* ---- Growing: try in-place ---- */
        maybe_compact_free_large_objects();

        char    *payload_end = (char *)ptr + old_usable;
        unsigned end_ci      = get_chunk_index(payload_end);

        if (end_ci >= FIRST_ALLOCATABLE_CHUNK) {
            struct page *end_page = get_page(payload_end);
            if (end_page->header.chunk_kinds[end_ci] == FREE_LARGE_OBJECT) {
                struct large_object *adj =
                    (struct large_object *)payload_end;
                size_t adj_total = adj->size + LARGE_OBJECT_HEADER_SIZE;

                size_t growth_needed  = new_size - old_usable;
                size_t growth_rounded =
                    align_up(growth_needed, CHUNK_SIZE);

                if (growth_rounded <= adj_total) {
                    /* In-place growth possible. */
                    remove_from_large_freelist(adj);

                    size_t absorbed  = growth_rounded;
                    obj->size       += absorbed;

                    /* Mark newly-used chunks in page headers. */
                    for (size_t off = 0; off < absorbed; off += CHUNK_SIZE) {
                        char    *p  = payload_end + off;
                        unsigned ci = get_chunk_index(p);
                        if (ci >= FIRST_ALLOCATABLE_CHUNK)
                            get_page(p)->header.chunk_kinds[ci] = LARGE_OBJECT;
                    }

                    /* Put remainder back on freelist. */
                    size_t remaining = adj_total - absorbed;
                    if (remaining >= CHUNK_SIZE + LARGE_OBJECT_HEADER_SIZE) {
                        char    *nfs    = payload_end + absorbed;
                        unsigned nfs_ci = get_chunk_index(nfs);
                        struct page *nfs_pg = get_page(nfs);

                        /* Skip page-header chunk if growth crossed a page. */
                        while (nfs_ci < FIRST_ALLOCATABLE_CHUNK
                               && remaining >= CHUNK_SIZE) {
                            nfs += CHUNK_SIZE;
                            remaining -= CHUNK_SIZE;
                            nfs_ci = get_chunk_index(nfs);
                            nfs_pg = get_page(nfs);
                        }

                        if (remaining >= CHUNK_SIZE + LARGE_OBJECT_HEADER_SIZE
                            && nfs_ci >= FIRST_ALLOCATABLE_CHUNK) {
                            nfs_pg->header.chunk_kinds[nfs_ci] =
                                FREE_LARGE_OBJECT;
                            struct large_object *nf =
                                (struct large_object *)nfs;
                            nf->size = remaining - LARGE_OBJECT_HEADER_SIZE;
                            nf->next = large_objects;
                            large_objects = nf;
                        }
                    }

                    /* Update stats. */
                    stats_total_alloc  += absorbed;
                    stats_current_live += absorbed;
                    if (stats_current_live > stats_peak_live)
                        stats_peak_live = stats_current_live;

                    return ptr;
                }
            }
        }

        /* ---- Fallback: malloc + copy + free ---- */
        void *np = walloc_malloc(new_size);
        if (!np) return NULL;
        memcpy(np, ptr, old_usable < new_size ? old_usable : new_size);
        walloc_free(ptr);
        return np;

    } else {
        /* ---- Small object ---- */
        unsigned old_granules =
            chunk_kind_to_granules((enum chunk_kind)kind);
        size_t old_usable = old_granules * GRANULE_SIZE;

        size_t new_granules = size_to_granules(new_size);
        enum chunk_kind new_kind = granules_to_chunk_kind(new_granules);

        if (new_kind == (enum chunk_kind)kind)
            return ptr;               /* same size class */

        void *np = walloc_malloc(new_size);
        if (!np) return NULL;
        size_t copy = old_usable < new_size ? old_usable : new_size;
        memcpy(np, ptr, copy);
        walloc_free(ptr);
        return np;
    }
}

void *walloc_calloc(size_t nmemb, size_t size) {
    if (!nmemb || !size) return NULL;
    size_t total = nmemb * size;
    if (total / nmemb != size) return NULL;      /* overflow */
    void *ptr = walloc_malloc(total);
    if (ptr) memset(ptr, 0, total);
    return ptr;
}

void walloc_get_stats(struct walloc_stats *s) {
    s->total_allocated_bytes = stats_total_alloc;
    s->total_freed_bytes     = stats_total_freed;
    s->current_live_bytes    = stats_current_live;
    s->peak_live_bytes       = stats_peak_live;
    s->num_pages             = walloc_heap_size / WPAGE_SIZE;

    if (walloc_heap_size > 0 && stats_current_live <= walloc_heap_size)
        s->fragmentation_ratio =
            1.0 - (double)stats_current_live / (double)walloc_heap_size;
    else
        s->fragmentation_ratio = 0.0;
}
