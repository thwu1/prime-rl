/*
 * keccak.c - Keccak-f[1600] permutation implementation
 *
 * Implements the 24-round Keccak-f[1600] permutation per FIPS 202.
 * Steps: theta, rho, pi, chi, iota.
 */

#include "keccak.h"
#include <string.h>

#define MASK64 0xFFFFFFFFFFFFFFFFULL

static inline uint64_t rot64(uint64_t val, int n) {
    n = n % 64;
    return ((val << n) | (val >> (64 - n))) & MASK64;
}

/* Rotation offsets for the rho step, indexed as [x][y] per FIPS 202 Table 2 */
static const int RHO_OFFSETS[5][5] = {
    { 0, 36,  3, 41, 18},
    { 1, 44, 10, 45,  2},
    {62,  6, 43, 15, 61},
    {28, 55, 25, 21, 56},
    {27, 20, 39,  8, 14},
};

/* Round constants for the iota step per FIPS 202 Table 3 */
static const uint64_t RC[24] = {
    0x0000000000000001ULL, 0x0000000000008082ULL,
    0x800000000000808AULL, 0x8000000080008000ULL,
    0x000000000000808BULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL,
    0x000000000000008AULL, 0x0000000000000088ULL,
    0x0000000080008009ULL, 0x000000008000000AULL,
    0x000000008000808BULL, 0x800000000000008BULL,
    0x8000000000008089ULL, 0x8000000000008003ULL,
    0x8000000000008002ULL, 0x8000000000000080ULL,
    0x000000000000800AULL, 0x800000008000000AULL,
    0x8000000080008081ULL, 0x8000000000008080ULL,
    0x0000000080000001ULL, 0x8000000080008008ULL,
};

static void bytes_to_state(const uint8_t *b, uint64_t state[5][5]) {
    int x, y, i;
    for (x = 0; x < 5; x++) {
        for (y = 0; y < 5; y++) {
            int offset = 8 * (5 * y + x);
            state[x][y] = 0;
            for (i = 0; i < 8; i++) {
                state[x][y] |= ((uint64_t)b[offset + i]) << (8 * i);
            }
        }
    }
}

static void state_to_bytes(const uint64_t state[5][5], uint8_t *b) {
    int x, y, i;
    for (x = 0; x < 5; x++) {
        for (y = 0; y < 5; y++) {
            int offset = 8 * (5 * y + x);
            for (i = 0; i < 8; i++) {
                b[offset + i] = (uint8_t)(state[x][y] >> (8 * i));
            }
        }
    }
}

void keccak_f1600(uint8_t state_bytes[200]) {
    uint64_t state[5][5];
    uint64_t C[5], D[5], B[5][5];
    int round_idx, x, y;

    bytes_to_state(state_bytes, state);

    for (round_idx = 0; round_idx < 24; round_idx++) {
        /* Theta */
        for (x = 0; x < 5; x++) {
            C[x] = state[x][0] ^ state[x][1] ^ state[x][2]
                 ^ state[x][3] ^ state[x][4];
        }
        for (x = 0; x < 5; x++) {
            D[x] = C[(x + 4) % 5] ^ rot64(C[(x + 1) % 5], 1);
        }
        for (x = 0; x < 5; x++) {
            for (y = 0; y < 5; y++) {
                state[x][y] ^= D[x];
            }
        }

        /* Rho */
        for (x = 0; x < 5; x++) {
            for (y = 0; y < 5; y++) {
                state[x][y] = rot64(state[x][y], RHO_OFFSETS[x][y]);
            }
        }

        /* Pi */
        for (x = 0; x < 5; x++) {
            for (y = 0; y < 5; y++) {
                B[y][(2 * x + 3 * y) % 5] = state[x][y];
            }
        }

        /* Chi */
        for (x = 0; x < 5; x++) {
            for (y = 0; y < 5; y++) {
                state[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y]);
            }
        }

        /* Iota */
        state[0][0] ^= RC[round_idx];
    }

    state_to_bytes(state, state_bytes);
}
