
/*
 * Hardened size-class segregated memory allocator.
 *
 * Small allocations (<= 2048 bytes):
 *   Slab-based with per-size-class free lists.
 *   Each slot: [chunk_hdr (32B)] [user data (class bytes)] [footer canary (8B)]
 *
 * Large allocations (> 2048 bytes):
 *   mmap with PROT_NONE guard pages on both sides.
 *   [guard page] [data pages: hdr + user data] [guard page]
 *
 * Security:
 *   - Random 8-byte canary in header + footer, verified on free.
 *   - Double-free detection via is_free flag.
 *   - Freed memory poisoned with 0xAB.
 */

#include "allocator.h"
#include <sys/mman.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */
#define ALIGN          16
#define PAGE_SIZE      4096
#define MAX_SMALL_SIZE 2048
#define NUM_SIZE_CLASSES 12
#define POISON_BYTE    0xAB
#define ALIGN_UP(x)    (((x) + (ALIGN - 1)) & ~(ALIGN - 1))

static const size_t size_classes[NUM_SIZE_CLASSES] = {
    16, 32, 48, 64, 96, 128, 192, 256, 384, 512, 1024, 2048
};

/* ------------------------------------------------------------------ */
/*  Internal data structures                                           */
/* ------------------------------------------------------------------ */

/*
 * Chunk header: 32 bytes.
 * Placed immediately before the user pointer so that
 * user_ptr = (void *)(hdr + 1), which is 16-byte aligned
 * when the header starts at a 16-byte-aligned address.
 */
struct chunk_hdr {
    uint64_t canary;           /* 8: randomised canary */
    size_t   alloc_size;       /* 8: class size (small) or aligned user size (large) */
    uint32_t is_free;          /* 4: 1 if freed (double-free detection) */
    int32_t  sc_idx;           /* 4: size-class index, -1 for large */
    union {
        struct chunk_hdr *next_free;   /* 8: free-list link (small) */
        size_t            mmap_total;  /* 8: total mmap size (large) */
    };
};

_Static_assert(sizeof(struct chunk_hdr) == 32,
               "chunk_hdr must be 32 bytes for alignment");

#define HDR_SIZE    ((size_t)sizeof(struct chunk_hdr))
#define FOOTER_SIZE ((size_t)sizeof(uint64_t))

/* Per-size-class singly-linked free lists. */
static struct chunk_hdr *free_lists[NUM_SIZE_CLASSES];

/* Random canary value, set once by halloc_init(). */
static uint64_t canary_value;

/* Global statistics. */
static halloc_stats_t stats;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

static int sc_index(size_t aligned_size) {
    for (int i = 0; i < NUM_SIZE_CLASSES; i++) {
        if (aligned_size <= size_classes[i])
            return i;
    }
    return -1;                         /* large allocation */
}

/* Total slot size in a slab for size-class idx. */
static size_t slot_size(int idx) {
    return ALIGN_UP(HDR_SIZE + size_classes[idx] + FOOTER_SIZE);
}

/* Write footer canary after user data. */
static void set_footer(void *user, int idx) {
    uint64_t *f = (uint64_t *)((char *)user + size_classes[idx]);
    *f = canary_value;
}

/* Read footer canary. */
static uint64_t get_footer(void *user, int idx) {
    return *(uint64_t *)((char *)user + size_classes[idx]);
}

/* Allocate a new slab for size-class idx, populate free list. */
static int alloc_slab(int idx) {
    size_t ss = slot_size(idx);
    size_t slab = PAGE_SIZE;
    while (slab / ss < 2)              /* ensure >=2 objects */
        slab += PAGE_SIZE;

    void *mem = mmap(NULL, slab, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mem == MAP_FAILED) return -1;

    stats.slab_pages += slab / PAGE_SIZE;

    size_t n = slab / ss;
    for (size_t i = 0; i < n; i++) {
        struct chunk_hdr *h =
            (struct chunk_hdr *)((char *)mem + i * ss);
        h->canary    = canary_value;
        h->alloc_size = size_classes[idx];
        h->is_free   = 1;
        h->sc_idx    = idx;
        set_footer((void *)(h + 1), idx);

        h->next_free      = free_lists[idx];
        free_lists[idx] = h;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Public API                                                         */
/* ------------------------------------------------------------------ */

void halloc_init(void) {
    int fd = open("/dev/urandom", O_RDONLY);
    if (fd >= 0) {
        ssize_t r = read(fd, &canary_value, sizeof(canary_value));
        close(fd);
        if (r != (ssize_t)sizeof(canary_value))
            canary_value = (uint64_t)(uintptr_t)&canary_value
                         ^ 0xDEADBEEFCAFEBABEULL;
    } else {
        canary_value = (uint64_t)(uintptr_t)&canary_value
                     ^ 0xDEADBEEFCAFEBABEULL;
    }
    if (canary_value == 0)
        canary_value = 0xDEADBEEFCAFEBABEULL;

    memset(free_lists, 0, sizeof(free_lists));
    memset(&stats, 0, sizeof(stats));
}

void *halloc(size_t size) {
    if (size == 0) return NULL;

    size_t aligned = ALIGN_UP(size);
    int    idx     = sc_index(aligned);

    /* ── large allocation ─────────────────────────────────── */
    if (idx < 0) {
        size_t data_bytes = HDR_SIZE + aligned;
        size_t data_pages = (data_bytes + PAGE_SIZE - 1) / PAGE_SIZE;
        size_t total      = (data_pages + 2) * PAGE_SIZE;

        void *mem = mmap(NULL, total, PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mem == MAP_FAILED) return NULL;

        /* guard pages */
        if (mprotect(mem, PAGE_SIZE, PROT_NONE) < 0 ||
            mprotect((char *)mem + (data_pages + 1) * PAGE_SIZE,
                     PAGE_SIZE, PROT_NONE) < 0) {
            munmap(mem, total);
            return NULL;
        }

        struct chunk_hdr *h = (struct chunk_hdr *)((char *)mem + PAGE_SIZE);
        h->canary     = canary_value;
        h->alloc_size = aligned;
        h->is_free    = 0;
        h->sc_idx     = -1;
        h->mmap_total = total;

        stats.total_allocs++;
        stats.bytes_allocated += aligned;
        stats.large_allocs++;

        return (void *)(h + 1);
    }

    /* ── small allocation ─────────────────────────────────── */
    if (!free_lists[idx]) {
        if (alloc_slab(idx) < 0) return NULL;
    }

    struct chunk_hdr *h = free_lists[idx];
    free_lists[idx]     = h->next_free;

    h->canary    = canary_value;
    h->is_free   = 0;
    h->next_free = NULL;

    void *user = (void *)(h + 1);
    set_footer(user, idx);

    stats.total_allocs++;
    stats.bytes_allocated += size_classes[idx];

    return user;
}

void hfree(void *ptr, size_t size) {
    if (!ptr) return;
    (void)size;                        /* size used only for caller contract */

    struct chunk_hdr *h = (struct chunk_hdr *)ptr - 1;

    /* header canary */
    if (h->canary != canary_value) {
        fprintf(stderr,
                "HALLOC: heap corruption detected (header canary) at %p\n",
                ptr);
        abort();
    }

    /* double-free */
    if (h->is_free) {
        fprintf(stderr, "HALLOC: double-free detected at %p\n", ptr);
        abort();
    }

    if (h->sc_idx >= 0) {
        /* ── small ─────────────────────────────────────────── */
        int idx = h->sc_idx;

        /* footer canary */
        if (get_footer(ptr, idx) != canary_value) {
            fprintf(stderr,
                    "HALLOC: heap overflow detected (footer canary) at %p\n",
                    ptr);
            abort();
        }

        memset(ptr, POISON_BYTE, size_classes[idx]);
        h->is_free   = 1;
        h->next_free = free_lists[idx];
        free_lists[idx] = h;

        stats.total_frees++;
        stats.bytes_allocated -= size_classes[idx];
    } else {
        /* ── large ─────────────────────────────────────────── */
        size_t total_mmap = h->mmap_total;
        size_t alloc_sz   = h->alloc_size;
        void  *base       = (char *)h - PAGE_SIZE;

        stats.total_frees++;
        stats.bytes_allocated -= alloc_sz;
        stats.large_allocs--;

        munmap(base, total_mmap);
    }
}

void *hrealloc(void *ptr, size_t old_size, size_t new_size) {
    if (!ptr) return halloc(new_size);
    if (new_size == 0) {
        hfree(ptr, old_size);
        return NULL;
    }

    struct chunk_hdr *h = (struct chunk_hdr *)ptr - 1;
    size_t new_aligned  = ALIGN_UP(new_size);

    /* Check if current allocation is large enough. */
    if (h->sc_idx >= 0) {
        if (new_aligned <= size_classes[h->sc_idx])
            return ptr;
    } else {
        if (new_aligned <= h->alloc_size)
            return ptr;
    }

    /* Allocate new, copy, free old. */
    void *dst = halloc(new_size);
    if (!dst) return NULL;

    size_t copy = old_size < new_size ? old_size : new_size;
    memcpy(dst, ptr, copy);
    hfree(ptr, old_size);

    return dst;
}

void halloc_get_stats(halloc_stats_t *s) {
    if (s) *s = stats;
}
