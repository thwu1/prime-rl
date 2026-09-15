/*
 * bitinfo.c — Parse and display structural metadata from a WGCF-compressed graph
 *
 * Compile:  gcc -O2 -o bitinfo bitinfo.c
 * Usage:    ./bitinfo <graph.bin> [max_nodes]
 *
 * Reads the binary file, parses the header and per-node structural fields
 * (degree, reference offset, block counts), and prints a summary. Does NOT
 * output decoded successor lists — those must be reconstructed separately.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef struct {
    const uint8_t *data;
    size_t len;
    size_t byte_pos;
    int bit_pos;
    size_t total_bits_read;
} BitReader;

static void br_init(BitReader *r, const uint8_t *data, size_t len) {
    r->data = data;
    r->len = len;
    r->byte_pos = 0;
    r->bit_pos = 7;
    r->total_bits_read = 0;
}

static int br_read_bit(BitReader *r) {
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

static uint64_t br_read_bits(BitReader *r, int n) {
    uint64_t v = 0;
    for (int i = 0; i < n; i++)
        v = (v << 1) | (uint64_t)br_read_bit(r);
    return v;
}

static uint64_t br_read_unary(BitReader *r) {
    uint64_t c = 0;
    while (br_read_bit(r) == 0) c++;
    return c;
}

static uint64_t br_read_gamma(BitReader *r) {
    uint64_t lam = br_read_unary(r);
    if (lam == 0) return 0;
    return br_read_bits(r, (int)lam) + (1ULL << lam) - 1;
}

static int ilog2_64(uint64_t v) {
    /* floor(log2(v)) for v > 0 */
    int r = 0;
    while (v >>= 1) r++;
    return r;
}

static uint64_t br_read_minimal_binary(BitReader *r, uint64_t bound) {
    if (bound == 0) return 0;
    int s = ilog2_64(bound);
    uint64_t threshold = (1ULL << (s + 1)) - bound;
    uint64_t x = br_read_bits(r, s);
    if (x < threshold) return x;
    return x * 2 + (uint64_t)br_read_bit(r) - threshold;
}

static uint64_t br_read_zeta3(BitReader *r) {
    uint64_t h = br_read_unary(r);
    uint64_t l = 1ULL << (h * 3);
    uint64_t upper = (l << 3) - l;
    uint64_t x = br_read_minimal_binary(r, upper);
    return l + x - 1;
}

int main(int argc, char **argv) {
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "Usage: %s <graph.bin> [max_nodes]\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 1; }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    rewind(f);

    uint8_t *data = (uint8_t *)malloc(fsize);
    if (!data || (long)fread(data, 1, fsize, f) != fsize) {
        fprintf(stderr, "Read error\n");
        return 1;
    }
    fclose(f);

    if (fsize < 4 || memcmp(data, "WGCF", 4) != 0) {
        fprintf(stderr, "Invalid magic (expected WGCF, got %02x%02x%02x%02x)\n",
                data[0], data[1], data[2], data[3]);
        return 1;
    }

    BitReader r;
    br_init(&r, data + 4, (size_t)(fsize - 4));

    uint64_t N = br_read_gamma(&r);
    uint64_t W = br_read_gamma(&r);

    uint64_t max_display = N;
    if (argc == 3) {
        max_display = (uint64_t)atol(argv[2]);
        if (max_display > N) max_display = N;
    }

    printf("=== WGCF Compressed Graph ===\n");
    printf("File size:     %ld bytes\n", fsize);
    printf("Payload bits:  %ld\n", (fsize - 4) * 8);
    printf("Nodes (N):     %lu\n", (unsigned long)N);
    printf("Window (W):    %lu\n", (unsigned long)W);
    printf("=============================\n\n");

    if (max_display > 0) {
        printf("%-8s %-8s %-8s %-10s %-8s %-8s\n",
               "Node", "Degree", "RefOff", "Mode", "Blocks", "Extras");
        printf("------   ------   ------   ----       ------   ------\n");
    }

    uint64_t copy_count = 0, direct_count = 0, empty_count = 0;
    uint64_t total_edges = 0;
    uint64_t max_deg = 0;

    for (uint64_t u = 0; u < N; u++) {
        uint64_t deg = br_read_gamma(&r);
        total_edges += deg;
        if (deg > max_deg) max_deg = deg;

        if (deg == 0) {
            if (u < max_display)
                printf("%-8lu %-8lu %-8s %-10s %-8s %-8s\n",
                       (unsigned long)u, 0UL, "-", "empty", "-", "-");
            empty_count++;
            continue;
        }

        uint64_t ref_off = br_read_gamma(&r);

        if (ref_off > 0) {
            uint64_t block_count = br_read_gamma(&r);
            for (uint64_t i = 0; i < block_count; i++)
                br_read_gamma(&r);  /* skip block lengths */

            uint64_t extra_count = br_read_gamma(&r);
            if (extra_count > 0) {
                br_read_zeta3(&r);
                for (uint64_t i = 1; i < extra_count; i++)
                    br_read_zeta3(&r);
            }

            if (u < max_display)
                printf("%-8lu %-8lu %-8lu %-10s %-8lu %-8lu\n",
                       (unsigned long)u, (unsigned long)deg,
                       (unsigned long)ref_off, "copy",
                       (unsigned long)block_count, (unsigned long)extra_count);
            copy_count++;
        } else {
            br_read_zeta3(&r);
            for (uint64_t i = 1; i < deg; i++)
                br_read_zeta3(&r);

            if (u < max_display)
                printf("%-8lu %-8lu %-8lu %-10s %-8s %-8s\n",
                       (unsigned long)u, (unsigned long)deg,
                       (unsigned long)ref_off, "direct", "-", "-");
            direct_count++;
        }
    }

    printf("\n=== Summary ===\n");
    printf("Total edges:   %lu\n", (unsigned long)total_edges);
    printf("Max degree:    %lu\n", (unsigned long)max_deg);
    printf("Copy-mode:     %lu nodes\n", (unsigned long)copy_count);
    printf("Direct-mode:   %lu nodes\n", (unsigned long)direct_count);
    printf("Empty nodes:   %lu nodes\n", (unsigned long)empty_count);
    printf("Bits consumed: %zu / %ld\n", r.total_bits_read, (fsize - 4) * 8);

    free(data);
    return 0;
}
