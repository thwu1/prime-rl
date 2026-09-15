/*
 * ef_dump.c — Decode and dump the Elias-Fano offset index from a WGEF file
 *
 * Usage:    ./ef_dump <graph.bin>
 *
 * Outputs a JSON object containing:
 *   - header:  {nodes, window, zeta_k}
 *   - ef:      {L, U, lower_bits_total, upper_bits_count}
 *   - layout:  {header_bits, ef_bits, node_data_start_bit}
 *   - offsets: array of N cumulative bit offsets into the node data section
 *
 * Pipe through jq for pretty-printing or field extraction.
 */

#include "bitstream.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <graph.bin>\n", argv[0]);
        fprintf(stderr, "\nDecodes the WGEF header and Elias-Fano offset index.\n");
        fprintf(stderr, "Outputs JSON to stdout. Use jq to filter results.\n");
        fprintf(stderr, "\nExamples:\n");
        fprintf(stderr, "  %s graph.bin | jq '.offsets[42]'\n", argv[0]);
        fprintf(stderr, "  %s graph.bin | jq '.layout.node_data_start_bit'\n", argv[0]);
        fprintf(stderr, "  %s graph.bin | jq '[.offsets[] | select(. > 0)] | length'\n", argv[0]);
        return 1;
    }

    size_t fsize;
    uint8_t *data = wgef_load(argv[1], &fsize);
    if (!data) return 1;

    WgefBitReader r;
    wgef_br_init(&r, data + 4, fsize - 4);

    /* Header */
    size_t header_start = r.total_bits_read;
    uint64_t N = wgef_br_read_gamma(&r);
    uint64_t W = wgef_br_read_gamma(&r);
    uint64_t K = wgef_br_read_gamma(&r);
    size_t header_bits = r.total_bits_read - header_start;

    /* Elias-Fano parameters */
    size_t ef_start = r.total_bits_read;
    uint64_t L = wgef_br_read_gamma(&r);
    uint64_t U = wgef_br_read_gamma(&r);

    /* Read lower bits: N values, each L bits wide */
    uint64_t *lowers = (uint64_t *)calloc(N, sizeof(uint64_t));
    if (!lowers) { fprintf(stderr, "alloc failed\n"); return 1; }
    for (uint64_t i = 0; i < N; i++) {
        if (L > 0)
            lowers[i] = wgef_br_read_bits(&r, (int)L);
    }

    /* Read upper bits: unary-coded gaps */
    uint64_t *offsets = (uint64_t *)calloc(N, sizeof(uint64_t));
    if (!offsets) { fprintf(stderr, "alloc failed\n"); return 1; }
    uint64_t cur_upper = 0;
    for (uint64_t i = 0; i < N; i++) {
        uint64_t gap = wgef_br_read_unary(&r);
        cur_upper += gap;
        offsets[i] = (cur_upper << L) | lowers[i];
    }

    size_t ef_bits = r.total_bits_read - ef_start;
    size_t node_data_start = r.total_bits_read;

    /* Output JSON */
    printf("{\n");
    printf("  \"header\": {\"nodes\": %lu, \"window\": %lu, \"zeta_k\": %lu},\n",
           (unsigned long)N, (unsigned long)W, (unsigned long)K);
    printf("  \"ef\": {\"L\": %lu, \"U\": %lu, \"lower_bits_total\": %lu, \"upper_bits_count\": %lu},\n",
           (unsigned long)L, (unsigned long)U,
           (unsigned long)(N * L), (unsigned long)(ef_bits - (N * L)));
    printf("  \"layout\": {\"header_bits\": %zu, \"ef_bits\": %zu, \"node_data_start_bit\": %zu},\n",
           header_bits, ef_bits, node_data_start);
    printf("  \"file_size_bytes\": %zu,\n", fsize);
    printf("  \"offsets\": [");
    for (uint64_t i = 0; i < N; i++) {
        if (i > 0) printf(",");
        if (i % 20 == 0) printf("\n    ");
        printf("%lu", (unsigned long)offsets[i]);
    }
    printf("\n  ]\n");
    printf("}\n");

    free(lowers);
    free(offsets);
    free(data);
    return 0;
}
