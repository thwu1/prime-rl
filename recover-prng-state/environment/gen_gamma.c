/*
 * PRNG generator — 64-bit LCG, outputs upper 32 bits.
 * Usage: ./gen_gamma <hex_seed_16chars> <count>
 * Outputs <count> raw 32-bit values (little-endian) to stdout.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define LCG_MULT 6364136223846793005ULL
#define LCG_INC  1442695040888963407ULL

static uint64_t state;

static uint32_t next_val(void) {
    state = state * LCG_MULT + LCG_INC;
    return (uint32_t)(state >> 32);
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <hex_seed> <count>\n", argv[0]);
        return 1;
    }

    state = strtoull(argv[1], NULL, 16);
    int count = atoi(argv[2]);

    for (int i = 0; i < count; i++) {
        uint32_t val = next_val();
        fwrite(&val, sizeof(uint32_t), 1, stdout);
    }

    return 0;
}
