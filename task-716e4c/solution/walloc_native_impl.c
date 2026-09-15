// walloc_native.c — Native (Linux) port of walloc with extensions
// Original walloc: Copyright (c) 2020 Igalia, S.L. (MIT license)
// Port adds: mmap-based memory, realloc, calloc, heap diagnostics
//

#include "walloc_native.h"
#include <sys/mman.h>
#include <string.h>

// =========================================================================
//  Constants  (renamed PAGE_SIZE → WP_PAGE_SIZE to avoid system conflicts)
// =========================================================================

#define WP_CHUNK_SIZE      256u
#define WP_CHUNK_SIZE_LOG2 8
#define WP_CHUNK_MASK      (WP_CHUNK_SIZE - 1)

#define WP_PAGE_SIZE       65536u
#define WP_PAGE_SIZE_LOG2  16
#define WP_PAGE_MASK       (WP_PAGE_SIZE - 1)

#define WP_CHUNKS_PER_PAGE 256
#define WP_GRANULE_SIZE    8u
#define WP_GRANULE_LOG2    3
#define WP_LARGE_THRESH    256   /* bytes; objects >256 are large */
#define WP_FIRST_CHUNK     1     /* chunk 0 is the page header */

#ifndef NDEBUG
#define WP_ASSERT(x) do { if (!(x)) __builtin_trap(); } while (0)
#else
#define WP_ASSERT(x) do { (void)0; } while (0)
#endif

// =========================================================================
//  Size-class machinery  (identical to walloc.c)
// =========================================================================

#define FOR_EACH_SC(M) M(1) M(2) M(3) M(4) M(5) M(6) M(8) M(10) M(16) M(32)

enum chunk_kind {
#define DEF_CK(i) GRANULES_##i,
    FOR_EACH_SC(DEF_CK)
#undef DEF_CK
    SMALL_OBJECT_CHUNK_KINDS,      /* == 10 */
    FREE_LARGE_OBJECT = 254,
    LARGE_OBJECT      = 255
};

static enum chunk_kind granules_to_chunk_kind(unsigned g) {
#define TEST(i) if (g <= i) return GRANULES_##i;
    FOR_EACH_SC(TEST)
#undef TEST
    return LARGE_OBJECT;
}

static unsigned chunk_kind_to_granules(enum chunk_kind k) {
    switch (k) {
#define CKG(i) case GRANULES_##i: return i;
        FOR_EACH_SC(CKG)
#undef CKG
        default: return 0;
    }
}

static inline size_t size_to_granules(size_t s) {
    return (s + WP_GRANULE_SIZE - 1) >> WP_GRANULE_LOG2;
}

// =========================================================================
//  Data structures  (identical to walloc.c)
// =========================================================================

struct chunk      { char data[WP_CHUNK_SIZE]; };
struct page_header{ uint8_t chunk_kinds[WP_CHUNKS_PER_PAGE]; };
struct page {
    union {
        struct page_header header;
        struct chunk       chunks[WP_CHUNKS_PER_PAGE];
    };
};

struct freelist     { struct freelist     *next; };
struct large_object { struct large_object *next; size_t size; };

#define LO_HDR_SIZE ((size_t)sizeof(struct large_object))

// =========================================================================
//  Inline helpers  (identical to walloc.c, modulo renames)
// =========================================================================

static inline size_t    wp_max(size_t a, size_t b) { return a < b ? b : a; }
static inline uintptr_t wp_align(uintptr_t v, uintptr_t a) {
    return (v + a - 1) & ~(a - 1);
}
static inline struct page *get_page(void *p) {
    return (struct page *)(char *)(((uintptr_t)p) & ~((uintptr_t)WP_PAGE_MASK));
}
static inline unsigned get_chunk_index(void *p) {
    return (((uintptr_t)p) & WP_PAGE_MASK) / WP_CHUNK_SIZE;
}
static inline void *lo_payload(struct large_object *o) {
    return ((char *)o) + LO_HDR_SIZE;
}
static inline struct large_object *lo_from_payload(void *p) {
    return (struct large_object *)(((char *)p) - LO_HDR_SIZE);
}

// =========================================================================
//  Global state
// =========================================================================

/* Native memory region (replaces WASM linear memory) */
static void  *g_raw_mmap  = NULL;   /* raw mmap result                    */
static size_t g_raw_size  = 0;      /* raw mmap size                      */
static char  *g_region    = NULL;   /* 64 KB-aligned start of heap region */
static size_t g_committed = 0;      /* logically committed bytes          */
static size_t g_max       = 0;      /* maximum heap size                  */

/* Allocator state (same roles as the globals in walloc.c) */
static struct freelist     *g_small_fl[SMALL_OBJECT_CHUNK_KINDS];
static struct large_object *g_large_fl       = NULL;
static size_t               g_heap_size      = 0;
static int                  g_compact_pend   = 0;

/* Counters for walloc_get_stats */
static size_t g_s_lcount = 0;   /* allocated large-object count */
static size_t g_s_lbytes = 0;   /* allocated large-object payload bytes */
static size_t g_s_scount = 0;   /* allocated small-object count */

// =========================================================================
//  Core helpers  (ported from walloc.c)
// =========================================================================

static char *alloc_chunk(struct page *pg, unsigned idx, enum chunk_kind k) {
    pg->header.chunk_kinds[idx] = (uint8_t)k;
    return pg->chunks[idx].data;
}

/*  allocate_pages — native port.
 *  In the original, heap_size = wasm_memory_size()*PAGE_SIZE (= end of
 *  linear memory).  Here, g_region + g_committed plays the same role. */
static struct page *
allocate_pages(size_t payload_size, size_t *n_out) {
    size_t needed   = payload_size + sizeof(struct page_header);
    uintptr_t heap_end = (uintptr_t)g_region + g_committed;
    uintptr_t base     = heap_end;
    size_t prealloc = 0, grow = 0;

    if (!g_heap_size) {
        /* First call — claim the initial committed page(s). */
        uintptr_t heap_base = wp_align((uintptr_t)g_region, WP_PAGE_SIZE);
        prealloc    = heap_end - heap_base;
        g_heap_size = prealloc;
        base       -= prealloc;
    }

    if (prealloc < needed) {
        grow = wp_align(wp_max(g_heap_size / 2, needed - prealloc),
                        WP_PAGE_SIZE);
        if (!grow) grow = WP_PAGE_SIZE;
        if (g_committed + grow > g_max) return NULL;
        g_committed += grow;
        g_heap_size += grow;
    }

    size_t total = grow + prealloc;
    if (!total) return NULL;
    *n_out = total / WP_PAGE_SIZE;
    return (struct page *)base;
}

/* Repurpose a single-chunk free large object as a GRANULES_32 slot. */
static void maybe_repurpose_head(void) {
    if (g_large_fl && g_large_fl->size < WP_CHUNK_SIZE) {
        unsigned idx = get_chunk_index(g_large_fl);
        char *ptr = alloc_chunk(get_page(g_large_fl), idx, GRANULES_32);
        g_large_fl = g_large_fl->next;
        struct freelist *h = (struct freelist *)ptr;
        h->next = g_small_fl[GRANULES_32];
        g_small_fl[GRANULES_32] = h;
    }
}

/* Merge a free large object with any adjacent successor. */
static struct large_object **
merge_adjacent(struct large_object **prev) {
    struct large_object *obj = *prev;
    for (;;) {
        char *end = (char *)lo_payload(obj) + obj->size;
        unsigned ci = get_chunk_index(end);
        if (ci < WP_FIRST_CHUNK) return prev;

        struct page *pg = get_page(end);

        /* Bounds check: don't read past the committed region. */
        if ((uintptr_t)end >= (uintptr_t)g_region + g_committed)
            return prev;

        if (pg->header.chunk_kinds[ci] != FREE_LARGE_OBJECT)
            return prev;

        struct large_object *nxt = (struct large_object *)end;

        /* Walk the freelist to find & unlink nxt. */
        struct large_object **pp = &g_large_fl, *w = g_large_fl;
        while (w) {
            if (w == nxt) {
                obj->size += LO_HDR_SIZE + w->size;
                *pp = w->next;
                if (prev == &w->next) prev = pp;
                break;
            }
            pp = &w->next;
            w  = w->next;
        }
        if (!w) return prev;          /* nxt not on list — stop */
    }
}

static void maybe_compact(void) {
    if (g_compact_pend) {
        g_compact_pend = 0;
        struct large_object **p = &g_large_fl;
        while (*p)
            p = &(*merge_adjacent(p))->next;
    }
}

/* allocate_large_object — identical logic to walloc.c */
static struct large_object *
allocate_large_object(size_t size) {
    maybe_compact();

    /* Best-fit search on the free list. */
    struct large_object *best = NULL, **best_prev = &g_large_fl;
    size_t best_size = (size_t)-1;
    for (struct large_object **pv = &g_large_fl, *w = g_large_fl;
         w; pv = &w->next, w = w->next) {
        if (w->size >= size && w->size < best_size) {
            best_size = w->size;
            best      = w;
            best_prev = pv;
            if (best_size + LO_HDR_SIZE ==
                wp_align(size + LO_HDR_SIZE, WP_CHUNK_SIZE))
                break;
        }
    }

    if (!best) {
        size_t swh = size + LO_HDR_SIZE;
        size_t na  = 0;
        struct page *pg = allocate_pages(swh, &na);
        if (!pg) return NULL;
        char *ptr = alloc_chunk(pg, WP_FIRST_CHUNK, LARGE_OBJECT);
        best = (struct large_object *)ptr;
        size_t ph = (size_t)(ptr - (char *)pg);
        best->next = g_large_fl;
        best->size = best_size = na * WP_PAGE_SIZE - ph - LO_HDR_SIZE;
    }

    alloc_chunk(get_page(best), get_chunk_index(best), LARGE_OBJECT);

    struct large_object *nx = best->next;
    *best_prev = nx;

    /* ---- Split tail ---- */
    size_t tail = (best_size - size) & ~(size_t)WP_CHUNK_MASK;
    if (tail) {
        struct page *sp = get_page(best);
        char *start = (char *)lo_payload(best);
        char *end   = start + best_size;

        if (sp == get_page(end - tail - 1)) {
            /* allocation does not span page boundary */
        } else if (size < WP_PAGE_SIZE - LO_HDR_SIZE - WP_CHUNK_SIZE) {
            /* allocation < 1 page: split head to stay in-page */
            size_t fps = WP_PAGE_SIZE - (((uintptr_t)start) & WP_PAGE_MASK);
            struct large_object *head = best;
            alloc_chunk(sp, get_chunk_index(start), FREE_LARGE_OBJECT);
            head->size = fps;
            head->next = g_large_fl;
            g_large_fl = head;
            maybe_repurpose_head();

            struct page *npage = sp + 1;
            char *p2 = alloc_chunk(npage, WP_FIRST_CHUNK, LARGE_OBJECT);
            best = (struct large_object *)p2;
            best->size = best_size =
                best_size - fps - WP_CHUNK_SIZE - LO_HDR_SIZE;
            start = (char *)lo_payload(best);
            tail  = (best_size - size) & ~(size_t)WP_CHUNK_MASK;
        } else {
            size_t fps  = WP_PAGE_SIZE - (((uintptr_t)start) & WP_PAGE_MASK);
            size_t tps  = wp_align(size - fps, WP_PAGE_SIZE);
            size  = fps + tps;
            tail  = best_size - size;
        }
        best->size -= tail;

        unsigned ti = get_chunk_index(end - tail);
        while (ti < WP_FIRST_CHUNK && tail) { tail -= WP_CHUNK_SIZE; ti++; }

        if (tail) {
            struct page *tp = get_page(end - tail);
            char *tp_ptr = alloc_chunk(tp, ti, FREE_LARGE_OBJECT);
            struct large_object *t = (struct large_object *)tp_ptr;
            t->next = g_large_fl;
            t->size = tail - LO_HDR_SIZE;
            g_large_fl = t;
            maybe_repurpose_head();
        }
    }
    return best;
}

/* obtain_small_objects — identical to walloc.c */
static struct freelist *
obtain_small_objects(enum chunk_kind kind) {
    struct freelist **wcfl = &g_small_fl[GRANULES_32];
    void *chunk;
    if (*wcfl) {
        chunk = *wcfl;
        *wcfl = (*wcfl)->next;
    } else {
        chunk = allocate_large_object(0);
        if (!chunk) return NULL;
    }
    char *ptr = alloc_chunk(get_page(chunk), get_chunk_index(chunk), kind);
    char *end = ptr + WP_CHUNK_SIZE;
    struct freelist *nxt = NULL;
    size_t sz = chunk_kind_to_granules(kind) * WP_GRANULE_SIZE;
    for (size_t i = sz; i <= WP_CHUNK_SIZE; i += sz) {
        struct freelist *h = (struct freelist *)(end - i);
        h->next = nxt;
        nxt = h;
    }
    return nxt;
}

static void *allocate_small(enum chunk_kind kind) {
    struct freelist **loc = &g_small_fl[kind];
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
    return obj ? lo_payload(obj) : NULL;
}

// =========================================================================
//  Public API
// =========================================================================

void walloc_init(size_t max_heap_size) {
    if (max_heap_size < WP_PAGE_SIZE) max_heap_size = WP_PAGE_SIZE;
    max_heap_size = wp_align(max_heap_size, WP_PAGE_SIZE);

    /* Reserve virtual address space. Extra 2 pages for alignment + guard. */
    size_t raw = max_heap_size + 2 * WP_PAGE_SIZE;
    void *m = mmap(NULL, raw, PROT_READ | PROT_WRITE,
                   MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
    if (m == MAP_FAILED) return;

    g_raw_mmap = m;
    g_raw_size = raw;
    g_region   = (char *)wp_align((uintptr_t)m, WP_PAGE_SIZE);
    g_committed = WP_PAGE_SIZE;    /* one initial page */
    g_max       = max_heap_size;

    /* Zero allocator state */
    memset(g_small_fl, 0, sizeof g_small_fl);
    g_large_fl     = NULL;
    g_heap_size    = 0;
    g_compact_pend = 0;
    g_s_lcount     = 0;
    g_s_lbytes     = 0;
    g_s_scount     = 0;
}

void walloc_destroy(void) {
    if (g_raw_mmap) {
        munmap(g_raw_mmap, g_raw_size);
        g_raw_mmap = NULL;
    }
    g_region    = NULL;
    g_committed = 0;
    g_max       = 0;
    g_heap_size = 0;
    g_large_fl  = NULL;
    g_compact_pend = 0;
    memset(g_small_fl, 0, sizeof g_small_fl);
    g_s_lcount = g_s_lbytes = g_s_scount = 0;
}

void *walloc_malloc(size_t size) {
    if (size == 0) size = 1;
    size_t gran = size_to_granules(size);
    enum chunk_kind kind = granules_to_chunk_kind(gran);
    void *ret;
    if (kind == LARGE_OBJECT) {
        ret = allocate_large(size);
        if (ret) {
            g_s_lcount++;
            g_s_lbytes += lo_from_payload(ret)->size;
        }
    } else {
        ret = allocate_small(kind);
        if (ret) g_s_scount++;
    }
    return ret;
}

void walloc_free(void *ptr) {
    if (!ptr) return;
    struct page *pg   = get_page(ptr);
    unsigned     ci   = get_chunk_index(ptr);
    uint8_t      kind = pg->header.chunk_kinds[ci];

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = lo_from_payload(ptr);
        g_s_lcount--;
        g_s_lbytes -= obj->size;
        obj->next   = g_large_fl;
        g_large_fl  = obj;
        alloc_chunk(pg, ci, FREE_LARGE_OBJECT);
        g_compact_pend = 1;
    } else {
        g_s_scount--;
        struct freelist **loc = &g_small_fl[kind];
        struct freelist *f = (struct freelist *)ptr;
        f->next = *loc;
        *loc = f;
    }
}

void *walloc_realloc(void *ptr, size_t new_size) {
    if (!ptr) return walloc_malloc(new_size);
    if (new_size == 0) { walloc_free(ptr); return NULL; }

    struct page *pg   = get_page(ptr);
    unsigned     ci   = get_chunk_index(ptr);
    uint8_t      kind = pg->header.chunk_kinds[ci];
    size_t       old_size;

    if (kind == LARGE_OBJECT) {
        struct large_object *obj = lo_from_payload(ptr);
        old_size = obj->size;
        if (new_size <= old_size) return ptr;       /* shrink in-place */
    } else if (kind < SMALL_OBJECT_CHUNK_KINDS) {
        unsigned g = chunk_kind_to_granules(kind);
        old_size = g * WP_GRANULE_SIZE;
        size_t new_g = size_to_granules(new_size);
        enum chunk_kind new_k = granules_to_chunk_kind(new_g);
        if (new_k == kind) return ptr;              /* same size class */
    } else {
        return NULL;  /* invalid pointer */
    }

    void *np = walloc_malloc(new_size);
    if (!np) return NULL;
    size_t copy = old_size < new_size ? old_size : new_size;
    memcpy(np, ptr, copy);
    walloc_free(ptr);
    return np;
}

void *walloc_calloc(size_t nmemb, size_t size) {
    if (nmemb && size && nmemb > (size_t)-1 / size) return NULL; /* overflow */
    size_t total = nmemb * size;
    void *p = walloc_malloc(total);
    if (p) memset(p, 0, total);
    return p;
}

// =========================================================================
//  Diagnostics
// =========================================================================

void walloc_get_stats(walloc_stats_t *s) {
    memset(s, 0, sizeof *s);
    s->heap_pages     = g_heap_size / WP_PAGE_SIZE;
    s->large_obj_count = g_s_lcount;
    s->large_obj_bytes = g_s_lbytes;
    s->small_obj_count = g_s_scount;

    /* Walk large-object free list for free_large_bytes. */
    for (struct large_object *o = g_large_fl; o; o = o->next)
        s->free_large_bytes += LO_HDR_SIZE + o->size;

    /* Walk small-object free lists for free_small_count. */
    for (int i = 0; i < SMALL_OBJECT_CHUNK_KINDS; i++)
        for (struct freelist *f = g_small_fl[i]; f; f = f->next)
            s->free_small_count++;
}

int walloc_validate_heap(void) {
    if (!g_region) return 1;   /* uninitialised → trivially valid */

    uintptr_t lo = (uintptr_t)g_region;
    uintptr_t hi = lo + g_committed;
    size_t max_entries = g_committed / WP_GRANULE_SIZE + 1;

    /* --- check large-object free list --- */
    size_t cnt = 0;
    for (struct large_object *o = g_large_fl; o; o = o->next) {
        uintptr_t a = (uintptr_t)o;
        if (a < lo || a >= hi) return 0;               /* out of region */
        if (a & WP_CHUNK_MASK)  return 0;               /* not chunk-aligned */
        unsigned ci = get_chunk_index(o);
        if (ci < WP_FIRST_CHUNK) return 0;
        struct page *pg = get_page(o);
        if (pg->header.chunk_kinds[ci] != FREE_LARGE_OBJECT) return 0;

        uintptr_t end = (uintptr_t)lo_payload(o) + o->size;
        if (end > hi) return 0;                         /* size overflows heap */
        if (++cnt > max_entries) return 0;              /* cycle detected */
    }

    /* --- check small-object free lists --- */
    for (int i = 0; i < SMALL_OBJECT_CHUNK_KINDS; i++) {
        cnt = 0;
        for (struct freelist *f = g_small_fl[i]; f; f = f->next) {
            uintptr_t a = (uintptr_t)f;
            if (a < lo || a >= hi) return 0;
            unsigned ci = get_chunk_index(f);
            if (ci < WP_FIRST_CHUNK) return 0;
            struct page *pg = get_page(f);
            if (pg->header.chunk_kinds[ci] != (uint8_t)i) return 0;
            if (++cnt > max_entries) return 0;
        }
    }
    return 1;
}
