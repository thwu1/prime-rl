/*
 * mphf_impl.c — Pilot-based Minimal Perfect Hash Function (C implementation)
 *
 *
 * Algorithm: partition keys into buckets via a hash function, then for each
 * bucket (largest first) search for an 8-bit "pilot" value that maps all keys
 * in the bucket to distinct, previously-unoccupied slots.  When no collision-
 * free pilot exists, use cuckoo-style eviction of conflicting buckets.  After
 * all pilots are assigned, a remap table maps overflow slots (>= n) down to
 * free positions (< n), making the hash minimal.
 */

#include "mphf.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */
#define MIX_C 0x517cc1b727220a95ULL

/* ------------------------------------------------------------------ */
/* Struct                                                               */
/* ------------------------------------------------------------------ */
struct mphf {
    uint64_t seed;
    size_t   n;
    size_t   num_slots;
    size_t   num_buckets;
    size_t   remap_len;
    size_t   remap_count;   /* number of overflow slots actually occupied */
    uint8_t  *pilots;
    uint32_t *remap;
    uint64_t ph[256]; /* precomputed pilot hashes (derived from seed) */
};

/* ------------------------------------------------------------------ */
/* Hash helpers                                                        */
/* ------------------------------------------------------------------ */
static inline uint64_t sm64(uint64_t x) {
    x ^= x >> 30;  x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;  x *= 0x94d049bb133111ebULL;
    x ^= x >> 31;
    return x;
}

static inline size_t freduce(uint64_t h, size_t n) {
    return (size_t)(((__uint128_t)h * (__uint128_t)n) >> 64);
}

static void init_ph(mphf_t *mf) {
    for (int i = 0; i < 256; i++)
        mf->ph[i] = MIX_C * ((uint64_t)i ^ mf->seed);
}

/* ------------------------------------------------------------------ */
/* Max-heap for bucket processing during eviction                      */
/* ------------------------------------------------------------------ */
typedef struct { size_t b; size_t pri; } he_t;
typedef struct { he_t *d; size_t n, cap; } heap_t;

static void hp_init(heap_t *H, size_t c) {
    H->d = (he_t *)malloc(c * sizeof(he_t));
    H->n = 0; H->cap = c;
}
static void hp_push(heap_t *H, he_t e) {
    if (H->n >= H->cap) {
        H->cap = H->cap ? H->cap * 2 : 16;
        H->d = (he_t *)realloc(H->d, H->cap * sizeof(he_t));
    }
    size_t i = H->n++;
    H->d[i] = e;
    while (i > 0) {
        size_t p = (i - 1) / 2;
        if (H->d[p].pri >= H->d[i].pri) break;
        he_t t = H->d[p]; H->d[p] = H->d[i]; H->d[i] = t;
        i = p;
    }
}
static he_t hp_pop(heap_t *H) {
    he_t r = H->d[0];
    H->d[0] = H->d[--H->n];
    size_t i = 0;
    for (;;) {
        size_t l = 2*i+1, ri = 2*i+2, m = i;
        if (l  < H->n && H->d[l].pri  > H->d[m].pri) m = l;
        if (ri < H->n && H->d[ri].pri > H->d[m].pri) m = ri;
        if (m == i) break;
        he_t t = H->d[i]; H->d[i] = H->d[m]; H->d[m] = t;
        i = m;
    }
    return r;
}

/* ------------------------------------------------------------------ */
/* Sorting helpers                                                     */
/* ------------------------------------------------------------------ */
typedef struct { size_t idx; size_t cnt; } bsort_t;
static int bsort_cmp(const void *a, const void *b) {
    size_t ca = ((const bsort_t *)a)->cnt;
    size_t cb = ((const bsort_t *)b)->cnt;
    return (cb > ca) - (cb < ca);   /* descending */
}
static int u64cmp(const void *a, const void *b) {
    uint64_t va = *(const uint64_t *)a, vb = *(const uint64_t *)b;
    return (va > vb) - (va < vb);
}

/* ------------------------------------------------------------------ */
/* Core construction (one seed attempt)                                */
/* ------------------------------------------------------------------ */
static int try_build(mphf_t *mf, const uint64_t *keys)
{
    const size_t n  = mf->n;
    const size_t nb = mf->num_buckets;
    const size_t ns = mf->num_slots;

    init_ph(mf);

    /* --- hash all keys ------------------------------------------------ */
    uint64_t *H = (uint64_t *)malloc(n * sizeof(uint64_t));
    for (size_t i = 0; i < n; i++)
        H[i] = sm64(keys[i] ^ mf->seed);

    /* check for duplicate hashes */
    uint64_t *Hs = (uint64_t *)malloc(n * sizeof(uint64_t));
    memcpy(Hs, H, n * sizeof(uint64_t));
    qsort(Hs, n, sizeof(uint64_t), u64cmp);
    for (size_t i = 1; i < n; i++) {
        if (Hs[i] == Hs[i-1]) { free(H); free(Hs); return 0; }
    }
    free(Hs);

    /* --- bucket assignment -------------------------------------------- */
    size_t *bcnt = (size_t *)calloc(nb, sizeof(size_t));
    for (size_t i = 0; i < n; i++)
        bcnt[freduce(H[i], nb)]++;

    size_t *boff = (size_t *)malloc(nb * sizeof(size_t));
    size_t acc = 0;
    for (size_t b = 0; b < nb; b++) { boff[b] = acc; acc += bcnt[b]; }

    uint64_t *bh = (uint64_t *)malloc(n * sizeof(uint64_t));
    size_t *bf   = (size_t *)calloc(nb, sizeof(size_t));
    for (size_t i = 0; i < n; i++) {
        size_t b = freduce(H[i], nb);
        bh[boff[b] + bf[b]++] = H[i];
    }
    free(H); free(bf);

    /* sort buckets by size descending */
    bsort_t *bo = (bsort_t *)malloc(nb * sizeof(bsort_t));
    for (size_t b = 0; b < nb; b++) { bo[b].idx = b; bo[b].cnt = bcnt[b]; }
    qsort(bo, nb, sizeof(bsort_t), bsort_cmp);

    /* --- pilot search ------------------------------------------------- */
    memset(mf->pilots, 0, nb);
    uint8_t *taken  = (uint8_t *)calloc(ns, 1);
    int64_t *owners = (int64_t *)malloc(ns * sizeof(int64_t));
    for (size_t i = 0; i < ns; i++) owners[i] = -1;

    size_t max_bkt = (bo[0].cnt > 0) ? bo[0].cnt : 1;
    size_t *slots  = (size_t *)malloc(max_bkt * sizeof(size_t));

    const size_t max_evict = 10 * ns;
    size_t tot_evict = 0;
    int ok = 1;

    heap_t heap;
    hp_init(&heap, 256);

    for (size_t bi = 0; bi < nb && ok; bi++) {
        size_t new_b  = bo[bi].idx;
        size_t new_cn = bcnt[new_b];
        if (new_cn == 0) continue;

        heap.n = 0;
        hp_push(&heap, (he_t){new_b, new_cn});

        size_t recent[32];
        size_t rcnt = 1;
        recent[0] = new_b;

        while (heap.n > 0 && ok) {
            he_t top = hp_pop(&heap);
            size_t b   = top.b;
            size_t cnt = bcnt[b];
            if (cnt == 0) continue;

            uint64_t *bhp = bh + boff[b];

            /* Phase 1: collision-free pilot */
            int placed = 0;
            for (int p = 0; p < 256 && !placed; p++) {
                uint64_t phv = mf->ph[p];
                int sc = 0;
                for (size_t k = 0; k < cnt; k++) {
                    slots[k] = (bhp[k] ^ phv) % ns;
                    for (size_t j = 0; j < k; j++) {
                        if (slots[j] == slots[k]) { sc = 1; break; }
                    }
                    if (sc) break;
                }
                if (sc) continue;

                int af = 1;
                for (size_t k = 0; k < cnt; k++) {
                    if (taken[slots[k]]) { af = 0; break; }
                }
                if (!af) continue;

                mf->pilots[b] = (uint8_t)p;
                for (size_t k = 0; k < cnt; k++) {
                    taken[slots[k]] = 1;
                    owners[slots[k]] = (int64_t)b;
                }
                placed = 1;
            }
            if (placed) continue;

            /* Phase 2: eviction pilot */
            int best_p = -1;
            size_t best_sc = (size_t)-1;
            uint8_t p0 = (uint8_t)((b * 2654435761ULL) & 0xFF);

            for (int delta = 0; delta < 256; delta++) {
                uint8_t p = (uint8_t)((p0 + delta) & 0xFF);
                uint64_t phv = mf->ph[p];
                int sc = 0;
                for (size_t k = 0; k < cnt; k++) {
                    slots[k] = (bhp[k] ^ phv) % ns;
                    for (size_t j = 0; j < k; j++) {
                        if (slots[j] == slots[k]) { sc = 1; break; }
                    }
                    if (sc) break;
                }
                if (sc) continue;

                size_t score = 0;
                int skip = 0;
                for (size_t k = 0; k < cnt; k++) {
                    int64_t o = owners[slots[k]];
                    if (o >= 0 && (size_t)o != b) {
                        for (size_t r = 0; r < rcnt; r++) {
                            if (recent[r] == (size_t)o) { skip = 1; break; }
                        }
                        if (skip) break;
                        score += bcnt[(size_t)o] * bcnt[(size_t)o];
                    }
                }
                if (skip) continue;
                if (score < best_sc) {
                    best_sc = score;
                    best_p  = (int)p;
                    if (score <= 1) break;
                }
            }

            if (best_p < 0) { ok = 0; break; }

            /* apply eviction */
            mf->pilots[b] = (uint8_t)best_p;
            {
                uint64_t phv = mf->ph[(uint8_t)best_p];
                for (size_t k = 0; k < cnt; k++)
                    slots[k] = (bhp[k] ^ phv) % ns;
            }

            for (size_t k = 0; k < cnt && ok; k++) {
                int64_t o = owners[slots[k]];
                if (o >= 0 && (size_t)o != b) {
                    tot_evict++;
                    if (tot_evict > max_evict) { ok = 0; break; }
                    /* remove evicted bucket's slots */
                    size_t oc  = bcnt[(size_t)o];
                    uint64_t *op = bh + boff[(size_t)o];
                    uint64_t oph = mf->ph[mf->pilots[(size_t)o]];
                    for (size_t j = 0; j < oc; j++) {
                        size_t os = (op[j] ^ oph) % ns;
                        taken[os]  = 0;
                        owners[os] = -1;
                    }
                    hp_push(&heap, (he_t){(size_t)o, oc});
                }
                taken[slots[k]]  = 1;
                owners[slots[k]] = (int64_t)b;
            }

            /* update recent list (keep last 16) */
            if (rcnt < 16) {
                recent[rcnt++] = b;
            } else {
                memmove(recent, recent + 1, 15 * sizeof(size_t));
                recent[15] = b;
            }
        }
    }

    free(bh); free(bcnt); free(boff); free(bo);
    free(taken); free(owners); free(slots);
    free(heap.d);

    return ok;
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

mphf_t *mphf_build(const uint64_t *keys, size_t n,
                    double alpha, double lambda)
{
    if (n == 0) return NULL;

    mphf_t *mf = (mphf_t *)calloc(1, sizeof(mphf_t));
    mf->n = n;

    mf->num_slots = (size_t)(n / alpha) + 1;
    if (mf->num_slots <= n) mf->num_slots = n + 1;
    /* avoid power-of-two table size (hurts modular reduction quality) */
    if ((mf->num_slots & (mf->num_slots - 1)) == 0) mf->num_slots++;

    mf->num_buckets = (size_t)(n / lambda) + 3;
    if (mf->num_buckets < 4) mf->num_buckets = 4;

    mf->remap_len = mf->num_slots - n;
    mf->remap_count = 0;
    mf->pilots    = (uint8_t *)calloc(mf->num_buckets, sizeof(uint8_t));
    mf->remap     = (uint32_t *)calloc(mf->remap_len,  sizeof(uint32_t));

    for (int attempt = 0; attempt < 10; attempt++) {
        mf->seed = sm64(0xCAFEBABE42ULL + (uint64_t)attempt * 0x9E3779B97F4A7C15ULL);

        if (try_build(mf, keys)) {
            /* --- build remap table ------------------------------------ */
            uint8_t *tk = (uint8_t *)calloc(mf->num_slots, 1);
            for (size_t i = 0; i < n; i++) {
                uint64_t h = sm64(keys[i] ^ mf->seed);
                size_t b   = freduce(h, mf->num_buckets);
                size_t s   = (h ^ mf->ph[mf->pilots[b]]) % mf->num_slots;
                tk[s] = 1;
            }
            uint32_t *fb = (uint32_t *)malloc(n * sizeof(uint32_t));
            size_t fi = 0;
            for (size_t i = 0; i < n; i++)
                if (!tk[i]) fb[fi++] = (uint32_t)i;

            size_t rc = 0;
            size_t fri = 0;
            for (size_t j = 0; j < mf->remap_len; j++) {
                if (tk[n + j]) {
                    mf->remap[j] = fb[fri++];
                    rc++;
                } else {
                    mf->remap[j] = 0;
                }
            }
            mf->remap_count = rc;
            free(fb); free(tk);
            return mf;
        }
    }

    /* all attempts failed */
    free(mf->pilots); free(mf->remap); free(mf);
    return NULL;
}

uint64_t mphf_query(const mphf_t *mf, uint64_t key)
{
    uint64_t h = sm64(key ^ mf->seed);
    size_t   b = freduce(h, mf->num_buckets);
    size_t   s = (h ^ mf->ph[mf->pilots[b]]) % mf->num_slots;
    if (s < mf->n) return (uint64_t)s;
    return mf->remap[s - mf->n];
}

double mphf_bits_per_key(const mphf_t *mf)
{
    if (mf->n == 0) return 0.0;
    /* pilots: 1 byte each.  remap entries: 4 bytes each. */
    return 8.0 * ((double)mf->num_buckets + 4.0 * (double)mf->remap_len)
         / (double)mf->n;
}

int mphf_save(const mphf_t *mf, const char *path)
{
    FILE *f = fopen(path, "wb");
    if (!f) return -1;
    fwrite(&mf->seed,         sizeof(uint64_t), 1, f);
    fwrite(&mf->n,            sizeof(size_t),   1, f);
    fwrite(&mf->num_slots,    sizeof(size_t),   1, f);
    fwrite(&mf->num_buckets,  sizeof(size_t),   1, f);
    fwrite(&mf->remap_len,    sizeof(size_t),   1, f);
    fwrite(&mf->remap_count,  sizeof(size_t),   1, f);
    fwrite(mf->pilots,        sizeof(uint8_t),  mf->num_buckets, f);
    fwrite(mf->remap,         sizeof(uint32_t), mf->remap_len,   f);
    fclose(f);
    return 0;
}

mphf_t *mphf_load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    mphf_t *mf = (mphf_t *)calloc(1, sizeof(mphf_t));
    if (fread(&mf->seed,         sizeof(uint64_t), 1, f) != 1) goto fail;
    if (fread(&mf->n,            sizeof(size_t),   1, f) != 1) goto fail;
    if (fread(&mf->num_slots,    sizeof(size_t),   1, f) != 1) goto fail;
    if (fread(&mf->num_buckets,  sizeof(size_t),   1, f) != 1) goto fail;
    if (fread(&mf->remap_len,    sizeof(size_t),   1, f) != 1) goto fail;
    if (fread(&mf->remap_count,  sizeof(size_t),   1, f) != 1) goto fail;
    mf->pilots = (uint8_t  *)malloc(mf->num_buckets * sizeof(uint8_t));
    mf->remap  = (uint32_t *)malloc(mf->remap_len   * sizeof(uint32_t));
    if (fread(mf->pilots, sizeof(uint8_t),  mf->num_buckets, f) != mf->num_buckets) goto fail;
    if (fread(mf->remap,  sizeof(uint32_t), mf->remap_len,   f) != mf->remap_len)   goto fail;
    fclose(f);
    init_ph(mf);
    return mf;
fail:
    free(mf->pilots); free(mf->remap); free(mf);
    fclose(f);
    return NULL;
}

void mphf_free(mphf_t *mf)
{
    if (!mf) return;
    free(mf->pilots);
    free(mf->remap);
    free(mf);
}

/* ---- Decomposed statistics API ---- */

size_t mphf_key_count(const mphf_t *mf)
{
    return mf->n;
}

size_t mphf_pilots_bytes(const mphf_t *mf)
{
    return mf->num_buckets * sizeof(uint8_t);
}

size_t mphf_remap_bytes(const mphf_t *mf)
{
    return mf->remap_len * sizeof(uint32_t);
}

size_t mphf_remap_count(const mphf_t *mf)
{
    return mf->remap_count;
}
