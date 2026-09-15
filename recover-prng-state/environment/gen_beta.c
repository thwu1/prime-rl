/*
 * PRNG generator — xorshift128.
 * Usage: ./gen_beta <hex_seed_32chars> <count>
 * Outputs <count> raw 32-bit values (little-endian) to stdout.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

static uint32_t sa, sb, sc, sd;

static uint32_t next_val(void) {
    uint32_t t = sd;
    uint32_t s = sa;
    sd = sc;
    sc = sb;
    sb = sa;
    t ^= (t << 11);
    t ^= (t >> 8);
    s ^= (s >> 19);
    sa = t ^ s;
    return sa;
}

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <hex_seed> <count>\n", argv[0]);
        return 1;
    }

    char *hex = argv[1];
    int count = atoi(argv[2]);
    int hlen = (int)strlen(hex);
    uint32_t seeds[4] = {0, 0, 0, 0};

    for (int i = 0; i < hlen && i < 32; i++) {
        int n = hex_nibble(hex[i]);
        if (n < 0) {
            fprintf(stderr, "Invalid hex char: %c\n", hex[i]);
            return 1;
        }
        seeds[i / 8] = (seeds[i / 8] << 4) | (uint32_t)n;
    }

    sa = seeds[0];
    sb = seeds[1];
    sc = seeds[2];
    sd = seeds[3];

    for (int i = 0; i < count; i++) {
        uint32_t val = next_val();
        fwrite(&val, sizeof(uint32_t), 1, stdout);
    }

    return 0;
}
