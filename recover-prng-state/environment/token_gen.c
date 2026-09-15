/*
 * Custom token generator — modified MT19937 PRNG.
 * Usage: ./token_gen <hex_seed_string> <count>
 * Outputs <count> raw 32-bit tokens (little-endian) to stdout.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define N 624
#define M 397
#define MATRIX_A   0x9908B0DFUL
#define UPPER_MASK 0x80000000UL
#define LOWER_MASK 0x7FFFFFFFUL

/* Custom tempering parameters (non-standard) */
#define TEMPER_U  13
#define TEMPER_S  9
#define TEMPER_B  0xB5A7C4E0UL
#define TEMPER_T  17
#define TEMPER_C  0xD3E40000UL
#define TEMPER_L  15

static uint32_t mt[N];
static int mti = N + 1;

static void init_genrand(uint32_t s) {
    mt[0] = s;
    for (mti = 1; mti < N; mti++) {
        mt[mti] = (1812433253UL * (mt[mti - 1] ^ (mt[mti - 1] >> 30)) + mti);
        mt[mti] &= 0xFFFFFFFFUL;
    }
}

static void init_by_array(uint32_t init_key[], int key_length) {
    int i, j, k;
    init_genrand(19650218UL);
    i = 1; j = 0;
    k = (N > key_length ? N : key_length);
    for (; k; k--) {
        mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1664525UL))
                + init_key[j] + j;
        mt[i] &= 0xFFFFFFFFUL;
        i++; j++;
        if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
        if (j >= key_length) j = 0;
    }
    for (k = N - 1; k; k--) {
        mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1566083941UL))
                - i;
        mt[i] &= 0xFFFFFFFFUL;
        i++;
        if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
    }
    mt[0] = 0x80000000UL;
}

static uint32_t extract(void) {
    uint32_t y;
    static const uint32_t mag01[2] = {0x0UL, MATRIX_A};

    if (mti >= N) {
        int kk;
        for (kk = 0; kk < N - M; kk++) {
            y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
            mt[kk] = mt[kk + M] ^ (y >> 1) ^ mag01[y & 0x1UL];
        }
        for (; kk < N - 1; kk++) {
            y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
            mt[kk] = mt[kk + (M - N)] ^ (y >> 1) ^ mag01[y & 0x1UL];
        }
        y = (mt[N - 1] & UPPER_MASK) | (mt[0] & LOWER_MASK);
        mt[N - 1] = mt[M - 1] ^ (y >> 1) ^ mag01[y & 0x1UL];
        mti = 0;
    }

    y = mt[mti++];

    y ^= (y >> TEMPER_U);
    y ^= (y << TEMPER_S) & TEMPER_B;
    y ^= (y << TEMPER_T) & TEMPER_C;
    y ^= (y >> TEMPER_L);

    return y;
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <hex_seed> <count>\n", argv[0]);
        return 1;
    }

    char *hex_seed = argv[1];
    int count = atoi(argv[2]);
    int hex_len = (int)strlen(hex_seed);
    int key_length = (hex_len + 7) / 8;
    uint32_t *key = (uint32_t *)calloc(key_length, sizeof(uint32_t));

    for (int idx = 0; idx < hex_len; idx++) {
        int nibble;
        char c = hex_seed[idx];
        if (c >= '0' && c <= '9')      nibble = c - '0';
        else if (c >= 'a' && c <= 'f')  nibble = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F')  nibble = c - 'A' + 10;
        else { fprintf(stderr, "Invalid hex char: %c\n", c); free(key); return 1; }
        key[idx / 8] = (key[idx / 8] << 4) | (uint32_t)nibble;
    }

    init_by_array(key, key_length);
    free(key);

    for (int i = 0; i < count; i++) {
        uint32_t val = extract();
        fwrite(&val, sizeof(uint32_t), 1, stdout);
    }

    return 0;
}
