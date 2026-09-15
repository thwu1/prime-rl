/*
 * bitstream.c — WGEF bitstream reader implementation
 */

#include "bitstream.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void wgef_br_init(WgefBitReader *r, const uint8_t *data, size_t len) {
    r->data = data;
    r->len = len;
    r->byte_pos = 0;
    r->bit_pos = 7;
    r->total_bits_read = 0;
}

void wgef_br_seek(WgefBitReader *r, size_t bit_offset) {
    r->byte_pos = bit_offset / 8;
    r->bit_pos = 7 - (int)(bit_offset % 8);
    r->total_bits_read = bit_offset;
}

int wgef_br_read_bit(WgefBitReader *r) {
    if (r->byte_pos >= r->len) {
        fprintf(stderr, "Error: unexpected end of bitstream at bit %zu\n",
                r->total_bits_read);
        exit(2);
    }
    int b = (r->data[r->byte_pos] >> r->bit_pos) & 1;
    if (--r->bit_pos < 0) {
        r->byte_pos++;
        r->bit_pos = 7;
    }
    r->total_bits_read++;
    return b;
}

uint64_t wgef_br_read_bits(WgefBitReader *r, int n) {
    uint64_t v = 0;
    for (int i = 0; i < n; i++)
        v = (v << 1) | (uint64_t)wgef_br_read_bit(r);
    return v;
}

uint64_t wgef_br_read_unary(WgefBitReader *r) {
    uint64_t c = 0;
    while (wgef_br_read_bit(r) == 0) c++;
    return c;
}

uint64_t wgef_br_read_gamma(WgefBitReader *r) {
    uint64_t lam = wgef_br_read_unary(r);
    if (lam == 0) return 0;
    return wgef_br_read_bits(r, (int)lam) + (1ULL << lam) - 1;
}

static int ilog2_64(uint64_t v) {
    int r = 0;
    while (v >>= 1) r++;
    return r;
}

uint64_t wgef_br_read_minimal_binary(WgefBitReader *r, uint64_t bound) {
    if (bound == 0) return 0;
    int s = ilog2_64(bound);
    uint64_t threshold = (1ULL << (s + 1)) - bound;
    uint64_t x = wgef_br_read_bits(r, s);
    if (x < threshold) return x;
    return x * 2 + (uint64_t)wgef_br_read_bit(r) - threshold;
}

uint64_t wgef_br_read_zeta(WgefBitReader *r, int k) {
    uint64_t h = wgef_br_read_unary(r);
    uint64_t l = 1ULL << (h * k);
    uint64_t upper = (l << k) - l;
    uint64_t x = wgef_br_read_minimal_binary(r, upper);
    return l + x - 1;
}

uint8_t *wgef_load(const char *path, size_t *fsize_out) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror("fopen"); return NULL; }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    rewind(f);

    uint8_t *data = (uint8_t *)malloc(fsize);
    if (!data || (long)fread(data, 1, fsize, f) != fsize) {
        fprintf(stderr, "Read error\n");
        fclose(f);
        free(data);
        return NULL;
    }
    fclose(f);

    if (fsize < 4 || memcmp(data, "WGEF", 4) != 0) {
        fprintf(stderr, "Invalid magic (expected WGEF)\n");
        free(data);
        return NULL;
    }

    *fsize_out = (size_t)fsize;
    return data;
}
