/*
 * walloc_native.c — Native Linux x86_64 port of walloc
 *
 * Original: walloc.c (c) 2020 Igalia, S.L. — MIT License
 *
 * This is a port of walloc, a segregated-freelist memory allocator originally
 * targeting WebAssembly.  WebAssembly-specific primitives (__builtin_wasm_
 * memory_grow, __builtin_wasm_memory_size, extern __heap_base) are replaced
 * with mmap/mprotect-based virtual memory management for native Linux.
 *
 * Extensions: walloc_realloc, walloc_malloc_usable_size.
 *
 */

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <stdlib.h>

/* ================================================================
 * Utility macros
 * ================================================================ */

#ifndef NDEBUG
#define ASSERT(x) do { if (!(x)) abort(); } while (0)
#else
#define ASSERT(x) do { } while (0)
#endif
#define ASSERT_EQ(a, b) ASSERT((a) == (b))

static inline size_t max_sz(size_t a, size_t b) {
    return a < b ? b : a;
}

static inline uintptr_t align_up(uintptr_t val, uintptr_t alignment) {
    return (val + alignment - 1) & ~(alignment - 1);
}

#define ASSERT_ALIGNED(x, y) ASSERT((x) == align_up((x), y))

/* ================================================================
 * Constants  (PAGE_SIZE renamed to WALLOC_PAGE_SIZE to avoid
 *             conflict with Linux system headers)
 * ================================================================ */

#define CHUNK_SIZE          256
#define CHUNK_SIZE_LOG_2    8
#define CHUNK_MASK          (CHUNK_SIZE - 1)

#define WALLOC_PAGE_SIZE        65536
#define WALLOC_PAGE_SIZE_LOG_2  16
#define WALLOC_PAGE_MASK        (WALLOC_PAGE_SIZE - 1)

#define CHUNKS_PER_PAGE     256

#define GRANULE_SIZE                    8
#define GRANULE_SIZE_LOG_2              3
#define LARGE_OBJECT_THRESHOLD          256
#define LARGE_OBJECT_GRANULE_THRESHOLD  32

_Static_assert(CHUNK_SIZE == (1 << CHUNK_SIZE_LOG_2), "chunk_size");
_Static_assert(WALLOC_PAGE_SIZE == (1 << WALLOC_PAGE_SIZE_LOG_2), "page_size");
_Static_assert(WALLOC_PAGE_SIZE == CHUNK_SIZE * CHUNKS_PER_PAGE, "chunks");
_Static_assert(GRANULE_SIZE == (1 << GRANULE_SIZE_LOG_2), "granule_size");
_Static_assert(LARGE_OBJECT_THRESHOLD ==
               LARGE_OBJECT_GRANULE_THRESHOLD * GRANULE_SIZE, "large_thresh");

/* ================================================================
 * Data structures — identical to original walloc
 * ================================================================ */

struct chunk {
    char data[CHUNK_SIZE];
};

#define FOR_EACH_SMALL_OBJECT_GRANULES(M) \
    M(1) M(2) M(3) M(4) M(5) M(6) M(8) M(10) M(16) M(32)

enum chunk_kind {
#define DEFINE_SMALL_OBJECT_CHUNK_KIND(i) GRANULES_##i,
    FOR_EACH_SMALL_OBJECT_GRANULES(DEFINE_SMALL_OBJECT_CHUNK_KIND)
#undef DEFINE_SMALL_OBJECT_CHUNK_KIND
    SMALL_OBJECT_CHUNK_KINDS,
    FREE_LARGE_OBJECT = 254,
    LARGE_OBJECT = 255
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
    default:
        return (unsigned)-1;
    }
}

struct page_header {
    uint8_t chunk_kinds[CHUNKS_PER_PAGE];
};

struct page {
    union {
        struct page_header header;
        struct chunk chunks[CHUNKS_PER_PAGE];
    };
};

#define PAGE_HEADER_SIZE        (sizeof(struct page_header))
#define FIRST_ALLOCATABLE_CHUNK 1
_Static_assert(PAGE_HEADER_SIZE == FIRST_ALLOCATABLE_CHUNK * CHUNK_SIZE,
               "page_header_size");

static struct page *get_page(void *ptr) {
    return (struct page *)(char *)(((uintptr_t)ptr) & ~(uintptr_t)WALLOC_PAGE_MASK);
}

static unsigned get_chunk_index(void *ptr) {
    return (((uintptr_t)ptr) & WALLOC_PAGE_MASK) / CHUNK_SIZE;
}

struct freelist {
    struct freelist *next;
};

struct large_object {
    struct large_object *next;
    size_t size;
};

#define LARGE_OBJECT_HEADER_SIZE (sizeof(struct large_object))

static inline void *get_large_object_payload(struct large_object *obj) {
    return ((char *)obj) + LARGE_OBJECT_HEADER_SIZE;
}

static inline struct large_object *get_large_object(void *ptr) {
    return (struct large_object *)(((char *)ptr) - LARGE_OBJECT_HEADER_SIZE);
}

/* ================================================================
 * Global allocator state
 * ================================================================ */

static struct freelist *small_object_freelists[SMALL_OBJECT_CHUNK_KINDS];
static struct large_object *large_objects;

/* ================================================================
 * Native memory management
 *
 * Replaces WebAssembly's memory.grow / memory.size / __heap_base
 * with a large mmap reservation + on-demand mprotect commit.
 * ================================================================ */

#define MAX_HEAP_SIZE (512UL * 1024 * 1024)   /* 512 MiB */

static char  *heap_base;        /* 64KB-aligned start of reserved region */
static size_t heap_committed;   /* bytes committed so far               */
static size_t walloc_heap_size; /* tracks growth for 50% expansion rule */
static int    heap_initialized;

static void ensure_heap_init(void) {
    if (heap_initialized) return;
    heap_initialized = 1;

    /* Reserve virtual address space without committing physical pages. */
    size_t reserve = MAX_HEAP_SIZE + WALLOC_PAGE_SIZE;
    char *raw = (char *)mmap(NULL, reserve, PROT_NONE,
                             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (raw == MAP_FAILED) abort();

    /* Align to 64KB so that get_page(ptr) = ptr & ~0xFFFF works. */
    heap_base = (char *)align_up((uintptr_t)raw, WALLOC_PAGE_SIZE);
}

/*
 * allocate_pages — commit fresh pages from the reserved region.
 *
 * Mirrors the original walloc behaviour: first call commits just enough,
 * subsequent calls grow by at least 50% of the current heap.
 */
static struct page *
allocate_pages(size_t payload_size, size_t *n_allocated) {
    ensure_heap_init();

    size_t needed = payload_size + PAGE_HEADER_SIZE;
    uintptr_t base = (uintptr_t)heap_base + heap_committed;

    size_t grow;
    if (!walloc_heap_size)
        grow = needed;
    else
        grow = max_sz(walloc_heap_size / 2, needed);

    grow = align_up(grow, WALLOC_PAGE_SIZE);
    if (grow < WALLOC_PAGE_SIZE)
        grow = WALLOC_PAGE_SIZE;

    if (heap_committed + grow > MAX_HEAP_SIZE)
        return NULL;

    if (mprotect((void *)base, grow, PROT_READ | PROT_WRITE) != 0)
        return NULL;

    heap_committed  += grow;
    walloc_heap_size += grow;

    struct page *ret = (struct page *)base;
    ASSERT(grow);
    ASSERT_ALIGNED(grow, WALLOC_PAGE_SIZE);
    *n_allocated = grow / WALLOC_PAGE_SIZE;
    return ret;
}

/* ================================================================
 * Core allocation algorithm  (preserved from original walloc)
 * ================================================================ */

static char *
allocate_chunk(struct page *page, unsigned idx, enum chunk_kind kind) {
    page->header.chunk_kinds[idx] = kind;
    return page->chunks[idx].data;
}

static void
maybe_repurpose_single_chunk_large_objects_head(void) {
    if (large_objects->size < CHUNK_SIZE) {
        unsigned idx = get_chunk_index(large_objects);
        char *ptr = allocate_chunk(get_page(large_objects), idx, GRANULES_32);
        large_objects = large_objects->next;
        struct freelist *head = (struct freelist *)ptr;
        head->next = small_object_freelists[GRANULES_32];
        small_object_freelists[GRANULES_32] = head;
    }
}

static int pending_large_object_compact;

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

static void
maybe_compact_free_large_objects(void) {
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
            if (best_size + LARGE_OBJECT_HEADER_SIZE
                == align_up(size + LARGE_OBJECT_HEADER_SIZE, CHUNK_SIZE))
                break;
        }
    }

    if (!best) {
        size_t size_with_header = size + sizeof(struct large_object);
        size_t n_allocated = 0;
        struct page *page = allocate_pages(size_with_header, &n_allocated);
        if (!page) return NULL;

        char *ptr  = allocate_chunk(page, FIRST_ALLOCATABLE_CHUNK, LARGE_OBJECT);
        best       = (struct large_object *)ptr;
        size_t ph  = ptr - (char *)page;
        best->next = large_objects;
        best->size = best_size =
            n_allocated * WALLOC_PAGE_SIZE - ph - LARGE_OBJECT_HEADER_SIZE;
    }

    allocate_chunk(get_page(best), get_chunk_index(best), LARGE_OBJECT);

    struct large_object *next_lo = best->next;
    *best_prev = next_lo;

    size_t tail_size = (best_size - size) & ~(size_t)CHUNK_MASK;
    if (tail_size) {
        struct page *start_page = get_page(best);
        char *start = (char *)get_large_object_payload(best);
        char *end   = start + best_size;

        if (start_page == get_page(end - tail_size - 1)) {
            ASSERT_ALIGNED((uintptr_t)end, CHUNK_SIZE);
        } else if (size < WALLOC_PAGE_SIZE - LARGE_OBJECT_HEADER_SIZE - CHUNK_SIZE) {
            ASSERT_ALIGNED((uintptr_t)end, WALLOC_PAGE_SIZE);
            size_t fps = WALLOC_PAGE_SIZE -
                         (((uintptr_t)start) & WALLOC_PAGE_MASK);
            struct large_object *head = best;
            allocate_chunk(start_page, get_chunk_index(start), FREE_LARGE_OBJECT);
            head->size = fps;
            head->next = large_objects;
            large_objects = head;

            maybe_repurpose_single_chunk_large_objects_head();

            struct page *np = start_page + 1;
            char *nptr = allocate_chunk(np, FIRST_ALLOCATABLE_CHUNK, LARGE_OBJECT);
            best = (struct large_object *)nptr;
            best->size = best_size =
                best_size - fps - CHUNK_SIZE - LARGE_OBJECT_HEADER_SIZE;
            ASSERT(best_size >= size);
            start     = (char *)get_large_object_payload(best);
            tail_size = (best_size - size) & ~(size_t)CHUNK_MASK;
        } else {
            ASSERT_ALIGNED((uintptr_t)end, WALLOC_PAGE_SIZE);
            size_t fps = WALLOC_PAGE_SIZE -
                         (((uintptr_t)start) & WALLOC_PAGE_MASK);
            size_t tps = align_up(size - fps, WALLOC_PAGE_SIZE);
            size      = fps + tps;
            tail_size = best_size - size;
        }

        best->size -= tail_size;

        unsigned tail_idx = get_chunk_index(end - tail_size);
        while (tail_idx < FIRST_ALLOCATABLE_CHUNK && tail_size) {
            tail_size -= CHUNK_SIZE;
            tail_idx++;
        }

        if (tail_size) {
            struct page *tp  = get_page(end - tail_size);
            char *tail_ptr   = allocate_chunk(tp, tail_idx, FREE_LARGE_OBJECT);
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
    struct freelist *head = NULL;
    size_t sz = chunk_kind_to_granules(kind) * GRANULE_SIZE;
    for (size_t i = sz; i <= CHUNK_SIZE; i += sz) {
        struct freelist *fl = (struct freelist *)(end - i);
        fl->next = head;
        head     = fl;
    }
    return head;
}

static inline size_t size_to_granules(size_t size) {
    return (size + GRANULE_SIZE - 1) >> GRANULE_SIZE_LOG_2;
}

static struct freelist **get_small_object_freelist(enum chunk_kind kind) {
    ASSERT(kind < SMALL_OBJECT_CHUNK_KINDS);
    return &small_object_freelists[kind];
}

static void *
allocate_small(enum chunk_kind kind) {
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

static void *
allocate_large(size_t size) {
    struct large_object *obj = allocate_large_object(size);
    return obj ? get_large_object_payload(obj) : NULL;
}

/* ================================================================
 * Public API
 * ================================================================ */

void *
walloc_malloc(size_t size) {
    size_t granules     = size_to_granules(size);
    enum chunk_kind kind = granules_to_chunk_kind(granules);
    return (kind == LARGE_OBJECT) ? allocate_large(size)
                                  : allocate_small(kind);
}

void
walloc_free(void *ptr) {
    if (!ptr) return;
    struct page *page = get_page(ptr);
    unsigned chunk    = get_chunk_index(ptr);
    uint8_t kind      = page->header.chunk_kinds[chunk];

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = get_large_object(ptr);
        obj->next     = large_objects;
        large_objects  = obj;
        allocate_chunk(page, chunk, FREE_LARGE_OBJECT);
        pending_large_object_compact = 1;
    } else {
        struct freelist **loc = get_small_object_freelist(kind);
        struct freelist *obj  = (struct freelist *)ptr;
        obj->next = *loc;
        *loc      = obj;
    }
}

size_t
walloc_malloc_usable_size(void *ptr) {
    if (!ptr) return 0;
    struct page *page = get_page(ptr);
    unsigned chunk    = get_chunk_index(ptr);
    uint8_t kind      = page->header.chunk_kinds[chunk];

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = get_large_object(ptr);
        return obj->size;
    }
    if (kind >= SMALL_OBJECT_CHUNK_KINDS)
        return 0;
    return chunk_kind_to_granules(kind) * GRANULE_SIZE;
}

void *
walloc_realloc(void *ptr, size_t new_size) {
    if (!ptr)
        return walloc_malloc(new_size);
    if (new_size == 0) {
        walloc_free(ptr);
        return NULL;
    }

    size_t old_usable = walloc_malloc_usable_size(ptr);

    struct page *page = get_page(ptr);
    unsigned chunk    = get_chunk_index(ptr);
    uint8_t kind      = page->header.chunk_kinds[chunk];

    if (kind != LARGE_OBJECT) {
        /* Small object: return same pointer if still in same size class. */
        size_t new_granules     = size_to_granules(new_size);
        enum chunk_kind new_kind = granules_to_chunk_kind(new_granules);
        if (new_kind == kind)
            return ptr;
    } else {
        /* Large object: shrinking within current allocation is free. */
        if (new_size <= old_usable)
            return ptr;
    }

    /* Must move: allocate new, copy, free old. */
    void *new_ptr = walloc_malloc(new_size);
    if (!new_ptr) return NULL;
    size_t copy = old_usable < new_size ? old_usable : new_size;
    memcpy(new_ptr, ptr, copy);
    walloc_free(ptr);
    return new_ptr;
}
