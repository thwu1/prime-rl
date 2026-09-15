/*
 * main.c - PPN codec round-trip test driver
 *
 */

#include "ppn_codec.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ----------------------------------------------------------------
 * Map comparison helper
 * ---------------------------------------------------------------- */

static int maps_equal(ppn_map_t *a, ppn_map_t *b)
{
    if (!a || !b) return 0;
    if (a->total_procs != b->total_procs) return 0;
    if (a->nnodes != b->nnodes) return 0;
    for (int n = 0; n < a->nnodes; n++) {
        if (a->nodes[n].nranks != b->nodes[n].nranks) return 0;
        for (int r = 0; r < a->nodes[n].nranks; r++) {
            if (a->nodes[n].ranks[r] != b->nodes[n].ranks[r]) return 0;
        }
    }
    return 1;
}

/* ----------------------------------------------------------------
 * Map generators for non-contiguous rank patterns
 * ---------------------------------------------------------------- */

static ppn_map_t *make_strided(int nnodes, int rpn, int stride)
{
    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;
    int base = 0;
    for (int n = 0; n < nnodes; n++) {
        map->nodes[n].node_id = n;
        map->nodes[n].nranks  = rpn;
        map->nodes[n].ranks   = calloc(rpn, sizeof(int));
        for (int r = 0; r < rpn; r++)
            map->nodes[n].ranks[r] = base + r * stride;
        base += rpn * stride;
        map->total_procs += rpn;
    }
    return map;
}

static ppn_map_t *make_irregular(int nnodes, int rpn)
{
    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;
    for (int n = 0; n < nnodes; n++) {
        map->nodes[n].node_id = n;
        map->nodes[n].nranks  = rpn;
        map->nodes[n].ranks   = calloc(rpn, sizeof(int));
        for (int r = 0; r < rpn; r++) {
            /* Quadratic + offset → non-uniform, non-constant stride */
            map->nodes[n].ranks[r] = r * r + n * rpn * rpn;
        }
        map->total_procs += rpn;
    }
    return map;
}

/* ----------------------------------------------------------------
 * Test functions
 * ---------------------------------------------------------------- */

static int test_roundtrip(int total_procs, int nnodes)
{
    printf("roundtrip %d procs/%d nodes... ", total_procs, nnodes);
    fflush(stdout);

    ppn_map_t *original = ppn_map_generate(total_procs, nnodes);
    if (!original) {
        printf("FAIL (generate)\n");
        return 1;
    }

    uint8_t *encoded;
    size_t   encoded_len;
    if (ppn_encode(original, &encoded, &encoded_len) != 0) {
        printf("FAIL (encode)\n");
        ppn_map_free(original);
        return 1;
    }

    const char *fmts[] = { "???", "raw", "compressed", "packed" };
    uint8_t tag = encoded[0];
    const char *fmt = (tag <= 3) ? fmts[tag] : "unknown";
    printf("[%s, %zu bytes] ", fmt, encoded_len);
    fflush(stdout);

    ppn_map_t *decoded = ppn_decode(encoded, encoded_len);
    if (!maps_equal(original, decoded)) {
        printf("FAIL (round-trip mismatch)\n");
        free(encoded);
        ppn_map_free(original);
        ppn_map_free(decoded);
        return 1;
    }

    printf("OK\n");
    free(encoded);
    ppn_map_free(original);
    ppn_map_free(decoded);
    return 0;
}

static int test_format_roundtrip(int total_procs, int nnodes,
                                 uint8_t expected_tag)
{
    const char *tag_names[] = { "???", "TAG_RAW", "TAG_BLOB", "TAG_PACKED" };
    const char *exp_name = (expected_tag <= 3) ? tag_names[expected_tag] : "?";

    printf("format %d/%d (expect %s)... ", total_procs, nnodes, exp_name);
    fflush(stdout);

    ppn_map_t *orig = ppn_map_generate(total_procs, nnodes);
    if (!orig) { printf("FAIL (generate)\n"); return 1; }

    uint8_t *enc;
    size_t elen;
    if (ppn_encode(orig, &enc, &elen) != 0) {
        printf("FAIL (encode)\n");
        ppn_map_free(orig);
        return 1;
    }

    if (enc[0] != expected_tag) {
        printf("FAIL (format: got 0x%02x, expected 0x%02x, size=%zu)\n",
               enc[0], expected_tag, elen);
        free(enc);
        ppn_map_free(orig);
        return 1;
    }

    ppn_map_t *dec = ppn_decode(enc, elen);
    if (!maps_equal(orig, dec)) {
        printf("FAIL (round-trip mismatch after %s decode)\n", exp_name);
        free(enc);
        ppn_map_free(orig);
        ppn_map_free(dec);
        return 1;
    }

    printf("OK [%zu bytes]\n", elen);
    free(enc);
    ppn_map_free(orig);
    ppn_map_free(dec);
    return 0;
}

static int test_strided_roundtrip(int nnodes, int rpn, int stride)
{
    printf("strided %d nodes/%d rpn/stride %d... ", nnodes, rpn, stride);
    fflush(stdout);

    ppn_map_t *orig = make_strided(nnodes, rpn, stride);
    if (!orig) { printf("FAIL (make)\n"); return 1; }

    uint8_t *enc;
    size_t elen;
    if (ppn_encode(orig, &enc, &elen) != 0) {
        printf("FAIL (encode)\n");
        ppn_map_free(orig);
        return 1;
    }

    ppn_map_t *dec = ppn_decode(enc, elen);
    if (!maps_equal(orig, dec)) {
        printf("FAIL (round-trip mismatch, size=%zu, tag=0x%02x)\n",
               elen, enc[0]);
        free(enc);
        ppn_map_free(orig);
        ppn_map_free(dec);
        return 1;
    }

    /*
     * Strided maps with stride > 1 and rpn >= 2 should use PACKED
     * with STRIDED encoding, producing very compact output.
     * PACKED_STRIDED per node = 2(nranks) + 1(enc) + 4(first) + 2(stride) = 9
     * Total = 1(tag) + 2(nnodes) + 9*nnodes
     * E.g. 4 nodes × 50 rpn → 39 bytes.
     * Check encoding is compact (under 200 bytes for these test sizes).
     */
    if (elen > 200) {
        printf("FAIL (encoded size %zu > 200, strided encoding not used?)\n",
               elen);
        free(enc);
        ppn_map_free(orig);
        ppn_map_free(dec);
        return 1;
    }

    printf("OK [%s, %zu bytes]\n",
           enc[0] == TAG_PACKED ? "packed" : "other", elen);
    free(enc);
    ppn_map_free(orig);
    ppn_map_free(dec);
    return 0;
}

static int test_irregular_roundtrip(int nnodes, int rpn)
{
    printf("irregular %d nodes/%d rpn... ", nnodes, rpn);
    fflush(stdout);

    ppn_map_t *orig = make_irregular(nnodes, rpn);
    if (!orig) { printf("FAIL (make)\n"); return 1; }

    uint8_t *enc;
    size_t elen;
    if (ppn_encode(orig, &enc, &elen) != 0) {
        printf("FAIL (encode)\n");
        ppn_map_free(orig);
        return 1;
    }

    ppn_map_t *dec = ppn_decode(enc, elen);
    if (!maps_equal(orig, dec)) {
        printf("FAIL (round-trip mismatch, size=%zu, tag=0x%02x)\n",
               elen, enc[0]);
        free(enc);
        ppn_map_free(orig);
        ppn_map_free(dec);
        return 1;
    }

    printf("OK [%s, %zu bytes]\n",
           enc[0] == TAG_PACKED ? "packed" :
           enc[0] == TAG_BLOB   ? "compressed" : "raw", elen);
    free(enc);
    ppn_map_free(orig);
    ppn_map_free(dec);
    return 0;
}

int main(void)
{
    int failures = 0;

    printf("=== PPN Codec Round-Trip Tests ===\n\n");

    printf("--- Contiguous Rank Round-Trips ---\n");
    failures += test_roundtrip(16, 2);
    failures += test_roundtrip(100, 4);
    failures += test_roundtrip(500, 8);
    failures += test_roundtrip(1000, 8);
    failures += test_roundtrip(1200, 9);
    failures += test_roundtrip(2000, 16);
    failures += test_roundtrip(5000, 32);

    printf("\n--- Format Selection ---\n");
    failures += test_format_roundtrip(3, 1, TAG_RAW);
    failures += test_format_roundtrip(100, 4, TAG_PACKED);
    failures += test_format_roundtrip(1200, 9, TAG_PACKED);
    failures += test_format_roundtrip(5000, 32, TAG_PACKED);

    printf("\n--- Strided Rank Patterns ---\n");
    failures += test_strided_roundtrip(4, 50, 2);
    failures += test_strided_roundtrip(8, 100, 3);
    failures += test_strided_roundtrip(16, 50, 5);

    printf("\n--- Irregular Rank Patterns ---\n");
    failures += test_irregular_roundtrip(4, 50);
    failures += test_irregular_roundtrip(8, 100);

    printf("\n=== Results: %d failures ===\n", failures);
    return failures ? 1 : 0;
}
