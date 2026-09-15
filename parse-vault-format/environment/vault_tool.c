/* vault_tool - vault archive encryption utility (no source provided to solver) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <zlib.h>

static void file_crypt(uint8_t *buf, size_t len, uint8_t seed, const char *fname) {
    uint32_t state = (uint32_t)seed ^ (uint32_t)crc32(0L, (const Bytef *)fname, (uInt)strlen(fname));
    for (size_t i = 0; i < len; i++) {
        state = (uint32_t)((uint64_t)state * 0x41C64E6DULL + 0x3039ULL);
        buf[i] ^= (uint8_t)((state >> 16) & 0xFF);
    }
}

static void meta_crypt(uint8_t *buf, size_t len, uint8_t seed) {
    uint32_t s = (uint32_t)seed;
    uint32_t state = (s << 24) | (s << 16) | (s << 8) | s;
    for (size_t i = 0; i < len; i++) {
        state = (uint32_t)((uint64_t)state * 0x6C078965ULL + 1ULL);
        buf[i] ^= (uint8_t)((state >> 24) & 0xFF);
    }
}

int main(int argc, char **argv) {
    if (argc < 3) return 1;
    uint8_t seed = (uint8_t)strtol(argv[2], NULL, 0);

    size_t cap = 65536, len = 0;
    uint8_t *buf = (uint8_t *)malloc(cap);
    if (!buf) return 2;
    int c;
    while ((c = fgetc(stdin)) != EOF) {
        if (len >= cap) { cap *= 2; buf = (uint8_t *)realloc(buf, cap); }
        buf[len++] = (uint8_t)c;
    }

    if (strcmp(argv[1], "fe") == 0 || strcmp(argv[1], "fd") == 0) {
        if (argc < 4) { free(buf); return 1; }
        file_crypt(buf, len, seed, argv[3]);
    } else if (strcmp(argv[1], "me") == 0 || strcmp(argv[1], "md") == 0) {
        meta_crypt(buf, len, seed);
    } else {
        free(buf);
        return 1;
    }

    fwrite(buf, 1, len, stdout);
    free(buf);
    return 0;
}
