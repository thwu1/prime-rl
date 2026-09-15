/* naive_mphf.c — A straightforward attempt at a minimal perfect hash function.
 *
 *
 * Compiles against mphf.h.  Build with:
 *     gcc -O2 -Wall -fPIC -shared -o libmphf.so naive_mphf.c -lm
 *
 * This implementation stores full keys in an open-addressing table with 3x
 * overallocation, yielding ~312 bits per key.  It fails the space requirement
 * (target: 1.5 to 4.0 bits/key) by orders of magnitude.  Investigate it to
 * understand the API contract, then write a fundamentally different solution.
 */

#include "mphf.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

struct mphf {
    size_t   n;
    size_t   capacity;
    uint64_t *slot_key;    /* open-addressing table: key */
    uint32_t *slot_val;    /* open-addressing table: assigned value */
    uint8_t  *slot_occ;    /* 1 = occupied, 0 = empty */
};

static uint64_t naive_hash(uint64_t k) {
    return k * 0x9E3779B97F4A7C15ULL;
}

mphf_t *mphf_build(const uint64_t *keys, size_t n,
                    double alpha, double lambda)
{
    (void)alpha; (void)lambda;          /* ignored */
    mphf_t *mf  = calloc(1, sizeof(*mf));
    if (!mf) return NULL;
    mf->n        = n;
    mf->capacity = n * 3;               /* 3x overallocation */
    mf->slot_key = calloc(mf->capacity, sizeof(uint64_t));
    mf->slot_val = calloc(mf->capacity, sizeof(uint32_t));
    mf->slot_occ = calloc(mf->capacity, sizeof(uint8_t));

    for (size_t i = 0; i < n; i++) {
        uint64_t h = naive_hash(keys[i]) % mf->capacity;
        while (mf->slot_occ[h])
            h = (h + 1) % mf->capacity;
        mf->slot_key[h] = keys[i];
        mf->slot_val[h] = (uint32_t)i;
        mf->slot_occ[h] = 1;
    }
    return mf;
}

uint64_t mphf_query(const mphf_t *mf, uint64_t key)
{
    uint64_t h = naive_hash(key) % mf->capacity;
    while (mf->slot_occ[h]) {
        if (mf->slot_key[h] == key) return mf->slot_val[h];
        h = (h + 1) % mf->capacity;
    }
    return 0;   /* key not found — undefined behaviour anyway */
}

double mphf_bits_per_key(const mphf_t *mf)
{
    /* Each slot: key(8 B) + val(4 B) + occ(1 B) = 13 B.
     * Total = capacity * 13 bytes = 3n * 13 bytes.
     * bits_per_key = 8 * 3 * 13 = 312.  */
    return 8.0 * (double)mf->capacity
         * (sizeof(uint64_t) + sizeof(uint32_t) + sizeof(uint8_t))
         / (double)mf->n;
}

int mphf_save(const mphf_t *mf, const char *path)
{
    FILE *f = fopen(path, "wb");
    if (!f) return -1;
    fwrite(&mf->n,        sizeof(size_t), 1, f);
    fwrite(&mf->capacity, sizeof(size_t), 1, f);
    fwrite(mf->slot_key,  sizeof(uint64_t), mf->capacity, f);
    fwrite(mf->slot_val,  sizeof(uint32_t), mf->capacity, f);
    fwrite(mf->slot_occ,  sizeof(uint8_t),  mf->capacity, f);
    fclose(f);
    return 0;
}

mphf_t *mphf_load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    mphf_t *mf = calloc(1, sizeof(*mf));
    if (fread(&mf->n,        sizeof(size_t), 1, f) != 1) goto fail;
    if (fread(&mf->capacity, sizeof(size_t), 1, f) != 1) goto fail;
    mf->slot_key = malloc(mf->capacity * sizeof(uint64_t));
    mf->slot_val = malloc(mf->capacity * sizeof(uint32_t));
    mf->slot_occ = malloc(mf->capacity * sizeof(uint8_t));
    fread(mf->slot_key, sizeof(uint64_t), mf->capacity, f);
    fread(mf->slot_val, sizeof(uint32_t), mf->capacity, f);
    fread(mf->slot_occ, sizeof(uint8_t),  mf->capacity, f);
    fclose(f);
    return mf;
fail:
    free(mf);
    fclose(f);
    return NULL;
}

void mphf_free(mphf_t *mf)
{
    if (!mf) return;
    free(mf->slot_key);
    free(mf->slot_val);
    free(mf->slot_occ);
    free(mf);
}

/* ---- Decomposed statistics stubs ---- */

size_t mphf_key_count(const mphf_t *mf)
{
    return mf->n;
}

size_t mphf_pilots_bytes(const mphf_t *mf)
{
    /* Naive approach has no pilots — report 0. */
    (void)mf;
    return 0;
}

size_t mphf_remap_bytes(const mphf_t *mf)
{
    /* Naive approach has no remap table — report full table size. */
    return mf->capacity * (sizeof(uint64_t) + sizeof(uint32_t) + sizeof(uint8_t));
}

size_t mphf_remap_count(const mphf_t *mf)
{
    (void)mf;
    return 0;
}
