/*
 * PtrHash MPHF — reference implementation.
 *
 * Implements hash-and-displace construction with 8-bit pilots,
 * size-descending bucket ordering, seed-based retry, and
 * overflow remapping for minimality.
 *
 */

#include "ptrhash.h"
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* Internal data structure                                            */
/* ------------------------------------------------------------------ */

struct PtrHash {
    uint64_t seed;
    size_t   n;        /* number of keys                              */
    size_t   S;        /* number of slots  (S > n)                    */
    size_t   B;        /* number of buckets                           */
    uint8_t *pilots;   /* pilots[B]                                   */
    size_t  *remap;    /* remap[S - n]: overflow-to-gap mapping       */
};

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

static inline size_t bucket_of(uint64_t h, size_t B) {
    return (size_t)reduce32((uint32_t)(h >> 32), (uint32_t)B);
}

static inline size_t slot_of(uint64_t h, uint8_t pilot, uint64_t seed,
                              size_t S) {
    return (size_t)reduce64(fmix64(h ^ hash_pilot(pilot, seed)), (uint64_t)S);
}

/* Bucket descriptor for sorting */
struct binfo {
    size_t idx;
    size_t sz;
};

static int binfo_cmp_desc(const void *a, const void *b) {
    size_t sa = ((const struct binfo *)a)->sz;
    size_t sb = ((const struct binfo *)b)->sz;
    return (sa < sb) - (sa > sb);      /* descending by size */
}

/* ------------------------------------------------------------------ */
/* Single construction attempt with a given seed                      */
/* ------------------------------------------------------------------ */

static int try_construct(PtrHash *ph, const uint64_t *hashes,
                          const size_t *bucket_ids, size_t n, uint64_t seed) {
    ph->seed = seed;

    /* --- 1. Count bucket sizes --- */
    size_t *bsz = (size_t *)calloc(ph->B, sizeof(size_t));
    if (!bsz) return 0;
    for (size_t i = 0; i < n; i++)
        bsz[bucket_ids[i]]++;

    /* --- 2. CSR-style per-bucket key lists --- */
    size_t *off = (size_t *)calloc(ph->B + 1, sizeof(size_t));
    if (!off) { free(bsz); return 0; }
    for (size_t i = 0; i < ph->B; i++)
        off[i + 1] = off[i] + bsz[i];

    size_t *bkeys = (size_t *)malloc(n * sizeof(size_t));
    size_t *cur   = (size_t *)calloc(ph->B, sizeof(size_t));
    if (!bkeys || !cur) { free(bsz); free(off); free(bkeys); free(cur); return 0; }
    for (size_t i = 0; i < n; i++) {
        size_t b = bucket_ids[i];
        bkeys[off[b] + cur[b]++] = i;
    }
    free(cur);

    /* --- 3. Sort buckets by decreasing size --- */
    struct binfo *order = (struct binfo *)malloc(ph->B * sizeof(struct binfo));
    if (!order) { free(bsz); free(off); free(bkeys); return 0; }
    for (size_t i = 0; i < ph->B; i++) {
        order[i].idx = i;
        order[i].sz  = bsz[i];
    }
    qsort(order, ph->B, sizeof(struct binfo), binfo_cmp_desc);

    /* --- 4. Pilot search --- */
    uint8_t *taken = (uint8_t *)calloc(ph->S, 1);
    if (!taken) { free(bsz); free(off); free(bkeys); free(order); return 0; }
    memset(ph->pilots, 0, ph->B);

    /* Pre-allocate slot buffer — Poisson max is << 256 */
    size_t *sbuf = (size_t *)malloc(256 * sizeof(size_t));
    if (!sbuf) { free(taken); free(bsz); free(off); free(bkeys); free(order); return 0; }

    int success = 1;
    for (size_t bi = 0; bi < ph->B && success; bi++) {
        size_t b = order[bi].idx;
        size_t k = order[bi].sz;
        if (k == 0) continue;

        int found = 0;
        for (int p = 0; p < 256 && !found; p++) {
            int ok = 1;
            for (size_t j = 0; j < k && ok; j++) {
                size_t s = slot_of(hashes[bkeys[off[b] + j]],
                                   (uint8_t)p, seed, ph->S);
                sbuf[j] = s;
                if (taken[s]) { ok = 0; break; }
                /* Check intra-bucket collisions */
                for (size_t q = 0; q < j; q++)
                    if (sbuf[q] == s) { ok = 0; break; }
            }
            if (ok) {
                ph->pilots[b] = (uint8_t)p;
                for (size_t j = 0; j < k; j++)
                    taken[sbuf[j]] = 1;
                found = 1;
            }
        }
        if (!found) success = 0;
    }

    free(sbuf);
    free(order);
    free(bsz);
    free(off);
    free(bkeys);

    if (!success) { free(taken); return 0; }

    /* --- 5. Build remap table --- */
    /* Count gap slots (unused slots in [0, n)) */
    size_t gc = 0;
    for (size_t s = 0; s < ph->n; s++)
        if (!taken[s]) gc++;

    size_t *gaps = (size_t *)malloc((gc ? gc : 1) * sizeof(size_t));
    if (!gaps) { free(taken); return 0; }
    size_t gi = 0;
    for (size_t s = 0; s < ph->n; s++)
        if (!taken[s]) gaps[gi++] = s;

    /* Map each occupied overflow slot to a gap */
    gi = 0;
    for (size_t s = ph->n; s < ph->S; s++)
        if (taken[s]) ph->remap[s - ph->n] = gaps[gi++];

    free(gaps);
    free(taken);
    return 1;
}

/* ------------------------------------------------------------------ */
/* Public API                                                         */
/* ------------------------------------------------------------------ */

PtrHash *ptrhash_build(const uint64_t *keys, size_t n) {
    PtrHash *ph = (PtrHash *)calloc(1, sizeof(PtrHash));
    if (!ph) return NULL;
    ph->n = n;

    if (n == 0) {
        ph->S = 0;
        ph->B = 0;
        ph->pilots = NULL;
        ph->remap  = NULL;
        return ph;
    }

    /* --- Choose parameters --- */
    double alpha;
    if      (n <= 5)   alpha = 0.40;
    else if (n <= 20)  alpha = 0.65;
    else if (n <= 100) alpha = 0.80;
    else               alpha = 0.88;

    ph->S = (size_t)(n / alpha) + 1;
    if (ph->S <= n) ph->S = n + 1;

    ph->B = (n <= 3) ? 1 : (size_t)(n / 3.0) + 1;

    ph->pilots = (uint8_t *)calloc(ph->B, 1);
    size_t rlen = ph->S - n;
    ph->remap  = (size_t *)calloc(rlen ? rlen : 1, sizeof(size_t));
    if (!ph->pilots || !ph->remap) { ptrhash_free(ph); return NULL; }

    /* --- Pre-hash all keys --- */
    uint64_t *hashes = (uint64_t *)malloc(n * sizeof(uint64_t));
    if (!hashes) { ptrhash_free(ph); return NULL; }
    for (size_t i = 0; i < n; i++)
        hashes[i] = fx_hash(keys[i]);

    /* --- Bucket assignment (seed-independent) --- */
    size_t *bucket_ids = (size_t *)malloc(n * sizeof(size_t));
    if (!bucket_ids) { free(hashes); ptrhash_free(ph); return NULL; }
    for (size_t i = 0; i < n; i++)
        bucket_ids[i] = bucket_of(hashes[i], ph->B);

    /* --- Try construction with different seeds --- */
    int ok = 0;
    uint64_t seed = 0xBEEF1234CAFE5678ULL;
    for (int att = 0; att < 100 && !ok; att++) {
        seed = seed * 6364136223846793005ULL + 1442695040888963407ULL;
        ok = try_construct(ph, hashes, bucket_ids, n, seed);
    }

    free(bucket_ids);
    free(hashes);

    if (!ok) { ptrhash_free(ph); return NULL; }
    return ph;
}

size_t ptrhash_query(const PtrHash *ph, uint64_t key) {
    uint64_t h = fx_hash(key);
    size_t b = bucket_of(h, ph->B);
    size_t s = slot_of(h, ph->pilots[b], ph->seed, ph->S);
    return (s < ph->n) ? s : ph->remap[s - ph->n];
}

void ptrhash_free(PtrHash *ph) {
    if (!ph) return;
    free(ph->pilots);
    free(ph->remap);
    free(ph);
}
