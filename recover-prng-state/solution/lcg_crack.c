/*
 * Brute-force recovery of 64-bit LCG state from two consecutive 32-bit outputs.
 * The LCG is: state = state * MULT + INC (mod 2^64), output = state >> 32.
 * Given output[0] and output[1], find state_1 (after first advance) such that:
 *   state_1 >> 32 == output[0]
 *   (state_1 * MULT + INC) >> 32 == output[1]
 *
 * Usage: ./lcg_crack <output0_hex> <output1_hex>
 * Prints the full 64-bit state_1 in hex.
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <out0_hex> <out1_hex>\n", argv[0]);
        return 1;
    }

    uint64_t mult = 6364136223846793005ULL;
    uint64_t inc = 1442695040888963407ULL;

    uint32_t o0 = (uint32_t)strtoul(argv[1], NULL, 16);
    uint32_t o1 = (uint32_t)strtoul(argv[2], NULL, 16);

    for (uint64_t lo = 0; lo < (1ULL << 32); lo++) {
        uint64_t s1 = ((uint64_t)o0 << 32) | lo;
        uint64_t s2 = s1 * mult + inc;
        if ((uint32_t)(s2 >> 32) == o1) {
            printf("0x%016llx\n", (unsigned long long)s1);
            return 0;
        }
    }

    fprintf(stderr, "No solution found\n");
    return 1;
}
