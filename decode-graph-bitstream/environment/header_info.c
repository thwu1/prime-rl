/*
 * header_info.c — Dump header and Elias-Fano index parameters from a WGEF file
 *
 * Usage:    ./header_info <graph.bin>
 *
 * Reads the WGEF binary, decodes the header fields (N, W, K) and the
 * Elias-Fano offset index parameters (L, U). Reports structural
 * information about the file layout.
 */

#include "bitstream.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <graph.bin>\n", argv[0]);
        return 1;
    }

    size_t fsize;
    uint8_t *data = wgef_load(argv[1], &fsize);
    if (!data) return 1;

    WgefBitReader r;
    wgef_br_init(&r, data + 4, fsize - 4);

    size_t header_start = r.total_bits_read;
    uint64_t N = wgef_br_read_gamma(&r);
    uint64_t W = wgef_br_read_gamma(&r);
    uint64_t K = wgef_br_read_gamma(&r);
    size_t header_bits = r.total_bits_read - header_start;

    /* Read EF parameters */
    size_t ef_start = r.total_bits_read;
    uint64_t L = wgef_br_read_gamma(&r);
    uint64_t U = wgef_br_read_gamma(&r);
    size_t ef_params_bits = r.total_bits_read - ef_start;

    uint64_t lower_total = N * L;
    uint64_t max_upper = (L < 64) ? ((U + ((1ULL << L) - 1)) >> L) : 0;
    uint64_t upper_approx = N + max_upper;

    printf("=== WGEF Compressed Graph ===\n");
    printf("File size:          %zu bytes\n", fsize);
    printf("Payload bits:       %zu\n", (fsize - 4) * 8);
    printf("\n");
    printf("--- Header ---\n");
    printf("Nodes (N):          %lu\n", (unsigned long)N);
    printf("Window (W):         %lu\n", (unsigned long)W);
    printf("Zeta param (K):     %lu\n", (unsigned long)K);
    printf("Header bits:        %zu\n", header_bits);
    printf("\n");
    printf("--- Elias-Fano Offset Index ---\n");
    printf("Lower-bit width L:  %lu\n", (unsigned long)L);
    printf("Upper bound U:      %lu\n", (unsigned long)U);
    printf("EF param bits:      %zu (gamma(L) + gamma(U))\n", ef_params_bits);
    printf("Lower bits total:   %lu (N * L = %lu * %lu)\n",
           (unsigned long)lower_total, (unsigned long)N, (unsigned long)L);
    printf("Upper bits approx:  ~%lu (N + U/2^L)\n", (unsigned long)upper_approx);
    printf("EF section approx:  ~%lu bits total\n",
           (unsigned long)(ef_params_bits + lower_total + upper_approx));
    printf("\n");
    printf("--- Estimated Layout ---\n");
    printf("Header ends at:     bit %zu (from payload start)\n", header_bits);
    printf("EF params end at:   bit %zu\n", header_bits + ef_params_bits);
    printf("Lower bits span:    bit %zu to ~%zu\n",
           header_bits + ef_params_bits,
           header_bits + ef_params_bits + lower_total);
    printf("Upper bits span:    bit ~%zu to ~%zu\n",
           header_bits + ef_params_bits + lower_total,
           header_bits + ef_params_bits + lower_total + upper_approx);
    printf("Node data starts:   ~bit %zu (approximate)\n",
           header_bits + ef_params_bits + lower_total + upper_approx);
    printf("=============================\n");

    free(data);
    return 0;
}
