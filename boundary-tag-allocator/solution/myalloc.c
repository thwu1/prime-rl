/*
 *
 * Custom boundary-tag memory allocator with coalescing and splitting.
 * Compile: gcc -O2 -fPIC -shared -Wno-deprecated-declarations \
 *          -o libmyalloc.so myalloc.c -lpthread
 */

#include <unistd.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>

/* ------------------------------------------------------------------ */
/* glibc original allocator — used for pointers outside our heap      */
/* ------------------------------------------------------------------ */

extern void  __libc_free(void *ptr);
extern void *__libc_realloc(void *ptr, size_t size);

/* ------------------------------------------------------------------ */
/* Layout constants                                                    */
/* ------------------------------------------------------------------ */

#define ALIGNMENT 16
#define ALIGN(x) (((x) + (ALIGNMENT - 1)) & ~(ALIGNMENT - 1))

/*
 * Block layout (all sizes multiples of 16):
 *
 *   +------------------+  <-- block_header_t *
 *   | size  (8 bytes)  |
 *   | alloc (8 bytes)  |  header: 16 bytes total
 *   +------------------+  <-- payload pointer returned to caller
 *   | payload ...      |     (ALIGN(requested) bytes, min 16)
 *   +------------------+
 *   | size  (8 bytes)  |
 *   | _pad  (8 bytes)  |  footer: 16 bytes total
 *   +------------------+
 *
 * Free blocks store next/prev free-list pointers at the start of the
 * payload area (requires minimum payload of 16 bytes).
 */

typedef struct block_header {
    size_t size;        /* total block size (header + payload + footer) */
    size_t allocated;   /* 0 = free, 1 = allocated */
} block_header_t;

typedef struct block_footer {
    size_t size;        /* mirrors header size for backward traversal */
    size_t _pad;        /* alignment padding */
} block_footer_t;

typedef struct free_ptrs {
    block_header_t *next;
    block_header_t *prev;
} free_ptrs_t;

#define HEADER_SIZE  ((size_t)sizeof(block_header_t))   /* 16 */
#define FOOTER_SIZE  ((size_t)sizeof(block_footer_t))   /* 16 */
#define OVERHEAD     (HEADER_SIZE + FOOTER_SIZE)         /* 32 */
#define MIN_PAYLOAD  ((size_t)16)  /* must hold free_ptrs_t */
#define MIN_BLOCK    (OVERHEAD + MIN_PAYLOAD)            /* 48 */

/* ------------------------------------------------------------------ */
/* Global state                                                        */
/* ------------------------------------------------------------------ */

static block_header_t *free_list_head = NULL;
static void           *heap_start     = NULL;
static void           *heap_end       = NULL;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

/* ------------------------------------------------------------------ */
/* Inline helpers                                                      */
/* ------------------------------------------------------------------ */

static inline void *hdr_to_payload(block_header_t *h) {
    return (char *)h + HEADER_SIZE;
}

static inline block_header_t *payload_to_hdr(void *p) {
    return (block_header_t *)((char *)p - HEADER_SIZE);
}

static inline block_footer_t *hdr_to_footer(block_header_t *h) {
    return (block_footer_t *)((char *)h + h->size - FOOTER_SIZE);
}

static inline free_ptrs_t *hdr_to_fptrs(block_header_t *h) {
    return (free_ptrs_t *)hdr_to_payload(h);
}

static inline int in_heap(void *p) {
    return heap_start && p >= heap_start && p < heap_end;
}

static inline block_header_t *next_adjacent(block_header_t *h) {
    char *n = (char *)h + h->size;
    if (n >= (char *)heap_end) return NULL;
    block_header_t *nh = (block_header_t *)n;
    /* Sanity: size must be valid and block must fit within heap */
    if (nh->size < MIN_BLOCK || (char *)nh + nh->size > (char *)heap_end)
        return NULL;
    if (nh->allocated != 0 && nh->allocated != 1)
        return NULL;
    return nh;
}

static inline block_header_t *prev_adjacent(block_header_t *h) {
    if ((void *)h <= heap_start) return NULL;
    block_footer_t *pf = (block_footer_t *)((char *)h - FOOTER_SIZE);
    size_t prev_size = pf->size;
    /* Sanity checks */
    if (prev_size < MIN_BLOCK) return NULL;
    if (prev_size > (size_t)((char *)h - (char *)heap_start)) return NULL;
    block_header_t *prev = (block_header_t *)((char *)h - prev_size);
    if ((void *)prev < heap_start) return NULL;
    /* Header and footer sizes must agree */
    if (prev->size != prev_size) return NULL;
    if (prev->allocated != 0 && prev->allocated != 1) return NULL;
    return prev;
}

static inline void write_footer(block_header_t *h) {
    hdr_to_footer(h)->size = h->size;
}

/* ------------------------------------------------------------------ */
/* Explicit free list operations                                       */
/* ------------------------------------------------------------------ */

static void fl_remove(block_header_t *h) {
    free_ptrs_t *fp = hdr_to_fptrs(h);
    if (fp->prev)
        hdr_to_fptrs(fp->prev)->next = fp->next;
    else
        free_list_head = fp->next;
    if (fp->next)
        hdr_to_fptrs(fp->next)->prev = fp->prev;
}

static void fl_insert(block_header_t *h) {
    free_ptrs_t *fp = hdr_to_fptrs(h);
    fp->next = free_list_head;
    fp->prev = NULL;
    if (free_list_head)
        hdr_to_fptrs(free_list_head)->prev = h;
    free_list_head = h;
}

/* ------------------------------------------------------------------ */
/* Split & coalesce                                                    */
/* ------------------------------------------------------------------ */

static void try_split(block_header_t *h, size_t needed) {
    size_t rem = h->size - needed;
    if (rem >= MIN_BLOCK) {
        h->size = needed;
        write_footer(h);

        block_header_t *nb = (block_header_t *)((char *)h + needed);
        nb->size      = rem;
        nb->allocated = 0;
        write_footer(nb);
        fl_insert(nb);
    }
}

static block_header_t *coalesce(block_header_t *h) {
    block_header_t *prev = prev_adjacent(h);
    block_header_t *next = next_adjacent(h);
    int pf = prev && !prev->allocated;
    int nf = next && !next->allocated;

    if (pf && nf) {
        fl_remove(prev);
        fl_remove(next);
        prev->size += h->size + next->size;
        write_footer(prev);
        fl_insert(prev);
        return prev;
    }
    if (pf) {
        fl_remove(prev);
        prev->size += h->size;
        write_footer(prev);
        fl_insert(prev);
        return prev;
    }
    if (nf) {
        fl_remove(next);
        h->size += next->size;
        write_footer(h);
        fl_insert(h);
        return h;
    }
    fl_insert(h);
    return h;
}

/* ------------------------------------------------------------------ */
/* Heap extension via sbrk                                             */
/* ------------------------------------------------------------------ */

static block_header_t *extend_heap(size_t blk_size) {
    /* First call: align the program break to 16 bytes */
    if (!heap_start) {
        uintptr_t brk = (uintptr_t)sbrk(0);
        uintptr_t aligned = ALIGN(brk);
        if (aligned != brk) {
            if (sbrk((intptr_t)(aligned - brk)) == (void *)-1)
                return NULL;
        }
        heap_start = sbrk(0);
        heap_end   = heap_start;
    }

    /* Detect if someone else moved the break (e.g. glibc internals) */
    void *cur_brk = sbrk(0);
    if (cur_brk != heap_end) {
        /* Gap: re-align and reset heap_end past the gap.
         * Blocks in the gap are untouchable; the safety checks in
         * prev_adjacent/next_adjacent prevent coalescing across it. */
        uintptr_t brk = (uintptr_t)cur_brk;
        uintptr_t aligned = ALIGN(brk);
        if (aligned != brk) {
            if (sbrk((intptr_t)(aligned - brk)) == (void *)-1)
                return NULL;
            cur_brk = sbrk(0);
        }
        heap_end = cur_brk;
    }

    block_header_t *blk = (block_header_t *)sbrk((intptr_t)blk_size);
    if (blk == (void *)-1) return NULL;

    heap_end = (char *)blk + blk_size;

    blk->size      = blk_size;
    blk->allocated = 0;
    write_footer(blk);
    return blk;
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

void *malloc(size_t size) {
    if (size == 0) size = 1;   /* glibc compat: return valid freeable ptr */

    size_t payload = ALIGN(size);
    if (payload < MIN_PAYLOAD) payload = MIN_PAYLOAD;
    size_t total = payload + OVERHEAD;

    pthread_mutex_lock(&lock);

    /* First-fit search */
    block_header_t *cur = free_list_head;
    while (cur) {
        if (cur->size >= total) {
            fl_remove(cur);
            cur->allocated = 1;
            try_split(cur, total);
            pthread_mutex_unlock(&lock);
            return hdr_to_payload(cur);
        }
        cur = hdr_to_fptrs(cur)->next;
    }

    /* No fit — grow the heap */
    block_header_t *blk = extend_heap(total);
    if (!blk) {
        pthread_mutex_unlock(&lock);
        return NULL;
    }
    blk->allocated = 1;

    pthread_mutex_unlock(&lock);
    return hdr_to_payload(blk);
}

void free(void *ptr) {
    if (!ptr) return;

    pthread_mutex_lock(&lock);

    /* Verify pointer belongs to our heap; if not, delegate to glibc */
    if (!in_heap(ptr)) {
        pthread_mutex_unlock(&lock);
        __libc_free(ptr);
        return;
    }

    block_header_t *h = payload_to_hdr(ptr);

    /* Double-free protection */
    if (!h->allocated) {
        pthread_mutex_unlock(&lock);
        return;
    }

    h->allocated = 0;
    coalesce(h);

    pthread_mutex_unlock(&lock);
}

void *calloc(size_t nmemb, size_t size) {
    if (nmemb == 0 || size == 0) return malloc(1);

    size_t total = nmemb * size;
    if (total / nmemb != size) return NULL;  /* overflow */

    void *p = malloc(total);
    if (p) memset(p, 0, total);
    return p;
}

void *realloc(void *ptr, size_t size) {
    if (!ptr) return malloc(size);
    if (size == 0) { free(ptr); return NULL; }

    pthread_mutex_lock(&lock);

    /* Verify pointer belongs to our heap; if not, delegate to glibc */
    if (!in_heap(ptr)) {
        pthread_mutex_unlock(&lock);
        return __libc_realloc(ptr, size);
    }

    block_header_t *h = payload_to_hdr(ptr);
    size_t old_payload = h->size - OVERHEAD;

    if (old_payload >= size) {
        pthread_mutex_unlock(&lock);
        return ptr;
    }

    pthread_mutex_unlock(&lock);

    void *np = malloc(size);
    if (!np) return NULL;
    memcpy(np, ptr, old_payload < size ? old_payload : size);
    free(ptr);
    return np;
}
