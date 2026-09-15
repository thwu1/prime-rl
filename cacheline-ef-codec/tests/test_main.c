/*
 * Test driver for PtrHash MPHF.
 *
 * Modes:
 *   verify <n> [seed]  - build MPHF on n random keys, verify bijectivity
 *   query  <n> [seed]  - build MPHF, print all query results
 *
 */

#include "ptrhash.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Deterministic PRNG for reproducible key generation */
static uint64_t xorshift64(uint64_t *state) {
    uint64_t x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *state = x;
    return x;
}

static uint64_t *gen_keys(size_t n, uint64_t seed) {
    uint64_t *keys = (uint64_t *)malloc(n * sizeof(uint64_t));
    if (!keys && n > 0) {
        fprintf(stderr, "malloc failed for %zu keys\n", n);
        exit(3);
    }
    uint64_t state = seed ? seed : 1;
    for (size_t i = 0; i < n; i++) {
        keys[i] = xorshift64(&state);
    }
    return keys;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <verify|query> <n> [seed]\n", argv[0]);
        return 1;
    }

    const char *mode = argv[1];
    size_t n = (size_t)strtoull(argv[2], NULL, 10);
    uint64_t seed = (argc > 3) ? (uint64_t)strtoull(argv[3], NULL, 10) : 42;

    uint64_t *keys = gen_keys(n, seed);

    PtrHash *ph = ptrhash_build(keys, n);
    if (!ph) {
        fprintf(stderr, "CONSTRUCTION_FAILED\n");
        free(keys);
        return 2;
    }

    if (strcmp(mode, "verify") == 0) {
        uint8_t *seen = (uint8_t *)calloc(n > 0 ? n : 1, 1);
        if (!seen) {
            fprintf(stderr, "calloc failed\n");
            ptrhash_free(ph);
            free(keys);
            return 3;
        }

        int ok = 1;
        for (size_t i = 0; i < n; i++) {
            size_t idx = ptrhash_query(ph, keys[i]);
            if (idx >= n) {
                fprintf(stderr, "OUT_OF_RANGE key_idx=%zu hash_idx=%zu n=%zu\n",
                        i, idx, n);
                ok = 0;
                break;
            }
            if (seen[idx]) {
                fprintf(stderr, "DUPLICATE key_idx=%zu hash_idx=%zu\n", i, idx);
                ok = 0;
                break;
            }
            seen[idx] = 1;
        }

        printf(ok ? "PASS\n" : "FAIL\n");
        free(seen);
    } else if (strcmp(mode, "query") == 0) {
        for (size_t i = 0; i < n; i++) {
            printf("%zu\n", ptrhash_query(ph, keys[i]));
        }
    } else {
        fprintf(stderr, "Unknown mode: %s\n", mode);
        ptrhash_free(ph);
        free(keys);
        return 1;
    }

    ptrhash_free(ph);
    free(keys);
    return 0;
}
