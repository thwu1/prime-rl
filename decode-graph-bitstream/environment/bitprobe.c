/*
 * bitprobe.c — Probe and decode codes at specific bit positions in a WGEF file
 *
 * Usage:
 *   ./bitprobe <file> <bit_offset> raw <count>
 *   ./bitprobe <file> <bit_offset> gamma
 *   ./bitprobe <file> <bit_offset> unary
 *   ./bitprobe <file> <bit_offset> zeta <k>
 *   ./bitprobe <file> <bit_offset> minbin <bound>
 *
 * bit_offset is counted from the start of the payload (after 4 magic bytes).
 */

#include "bitstream.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s <file> <bit_offset> raw <count>\n", argv[0]);
        fprintf(stderr, "  %s <file> <bit_offset> gamma\n", argv[0]);
        fprintf(stderr, "  %s <file> <bit_offset> unary\n", argv[0]);
        fprintf(stderr, "  %s <file> <bit_offset> zeta <k>\n", argv[0]);
        fprintf(stderr, "  %s <file> <bit_offset> minbin <bound>\n", argv[0]);
        fprintf(stderr, "\nbit_offset is from the start of payload (after 4 magic bytes)\n");
        return 1;
    }

    const char *filepath = argv[1];
    size_t bit_offset = (size_t)atol(argv[2]);
    const char *mode = argv[3];

    size_t fsize;
    uint8_t *data = wgef_load(filepath, &fsize);
    if (!data) return 1;

    WgefBitReader r;
    wgef_br_init(&r, data + 4, fsize - 4);
    wgef_br_seek(&r, bit_offset);

    if (strcmp(mode, "raw") == 0) {
        if (argc < 5) {
            fprintf(stderr, "raw mode requires <count>\n");
            return 1;
        }
        int count = atoi(argv[4]);
        printf("Raw bits at offset %zu (%d bits): ", bit_offset, count);
        for (int i = 0; i < count; i++) {
            printf("%d", wgef_br_read_bit(&r));
            if ((i + 1) % 8 == 0 && i + 1 < count) printf(" ");
        }
        printf("\n");
        printf("Bits consumed: %d\n", count);
    }
    else if (strcmp(mode, "gamma") == 0) {
        size_t start = r.total_bits_read;
        uint64_t val = wgef_br_read_gamma(&r);
        size_t consumed = r.total_bits_read - start;
        printf("Gamma at offset %zu: value = %lu, bits consumed = %zu\n",
               bit_offset, (unsigned long)val, consumed);
    }
    else if (strcmp(mode, "unary") == 0) {
        size_t start = r.total_bits_read;
        uint64_t val = wgef_br_read_unary(&r);
        size_t consumed = r.total_bits_read - start;
        printf("Unary at offset %zu: value = %lu, bits consumed = %zu\n",
               bit_offset, (unsigned long)val, consumed);
    }
    else if (strcmp(mode, "zeta") == 0) {
        if (argc < 5) {
            fprintf(stderr, "zeta mode requires <k>\n");
            return 1;
        }
        int k = atoi(argv[4]);
        size_t start = r.total_bits_read;
        uint64_t val = wgef_br_read_zeta(&r, k);
        size_t consumed = r.total_bits_read - start;
        printf("Zeta_%d at offset %zu: value = %lu, bits consumed = %zu\n",
               k, bit_offset, (unsigned long)val, consumed);
    }
    else if (strcmp(mode, "minbin") == 0) {
        if (argc < 5) {
            fprintf(stderr, "minbin mode requires <bound>\n");
            return 1;
        }
        uint64_t bound = (uint64_t)atol(argv[4]);
        size_t start = r.total_bits_read;
        uint64_t val = wgef_br_read_minimal_binary(&r, bound);
        size_t consumed = r.total_bits_read - start;
        printf("MinBin (bound=%lu) at offset %zu: value = %lu, bits consumed = %zu\n",
               (unsigned long)bound, bit_offset, (unsigned long)val, consumed);
    }
    else {
        fprintf(stderr, "Unknown mode: %s\n", mode);
        fprintf(stderr, "Modes: raw, gamma, unary, zeta, minbin\n");
        return 1;
    }

    free(data);
    return 0;
}
