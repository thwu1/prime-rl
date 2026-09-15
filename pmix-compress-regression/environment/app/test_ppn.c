/*
 * Test harness for PMIx-inspired PPN encoding/decoding.
 * Exercises backend tests, roundtrip encode/decode for various process
 * counts, and backward compatibility with v1 blob format.
 */

#include "preg.h"
#include "compress.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    int nprocs;
    int nnodes;
    const char *label;
} test_case_t;

/* Direct access to v1 encoder for backward compat testing */
extern int preg_compress_generate(const pmix_proc_map_t *map,
                                  char **output, size_t *outlen);

static test_case_t cases[] = {
    {   100,   4, "small: 100 procs / 4 nodes"              },
    {   500,  10, "medium: 500 procs / 10 nodes"             },
    {  1000,   8, "large-raw: 1000 procs / 8 nodes"          },
    {  1041,   9, "boundary-under: 1041 procs / 9 nodes"     },
    {  1042,   9, "boundary-over: 1042 procs / 9 nodes"      },
    {  2000,  16, "large-compressed: 2000 procs / 16 nodes"  },
    {  5000,  32, "xlarge: 5000 procs / 32 nodes"            },
    { 10000,  64, "xxlarge: 10000 procs / 64 nodes"          },
    { 20000, 128, "jumbo: 20000 procs / 128 nodes"           },
    { 50000, 256, "massive: 50000 procs / 256 nodes"         },
};

int main(void)
{
    int total_tests = 12;
    int npass = 0;
    int test_num = 0;

    printf("PMIx PPN encode/decode test suite (v2 multi-backend)\n");
    printf("=====================================================\n\n");

    /* --- Section 1: Backend Tests --- */
    printf("--- Backend Tests ---\n\n");

    /* Test 1: LZ4 compress/decompress roundtrip */
    test_num++;
    printf("[%d/%d] lz4-backend: compress/decompress roundtrip\n",
           test_num, total_tests);
    {
        size_t test_size = 8192;
        uint8_t *test_data = (uint8_t *)malloc(test_size);
        for (size_t i = 0; i < test_size; i++) {
            test_data[i] = (uint8_t)(i % 64 + '0');
        }

        uint8_t *compressed = NULL;
        size_t comp_len = 0;

        if (!pmix_lz4_compress(test_data, test_size, &compressed, &comp_len)) {
            printf("  FAIL: pmix_lz4_compress returned false\n\n");
        } else {
            printf("  compressed %zu -> %zu bytes (%.1f%%)\n",
                   test_size, comp_len, 100.0 * comp_len / test_size);

            size_t decomp_len = test_size;
            uint8_t *decompressed = NULL;

            if (!pmix_lz4_decompress(compressed, comp_len,
                                     &decompressed, &decomp_len)) {
                printf("  FAIL: pmix_lz4_decompress returned false\n\n");
            } else if (decomp_len != test_size ||
                       memcmp(test_data, decompressed, test_size) != 0) {
                printf("  FAIL: decompressed data does not match original\n\n");
            } else {
                printf("  PASS\n\n");
                npass++;
            }
            free(decompressed);
            free(compressed);
        }
        free(test_data);
    }

    /* --- Section 2: Roundtrip Encode/Decode Tests --- */
    printf("--- Roundtrip Tests ---\n\n");

    int ncases = (int)(sizeof(cases) / sizeof(cases[0]));
    for (int t = 0; t < ncases; t++) {
        test_case_t *tc = &cases[t];
        test_num++;
        printf("[%d/%d] %s\n", test_num, total_tests, tc->label);

        /* Create the reference process map */
        pmix_proc_map_t orig;
        if (pmix_proc_map_create(tc->nprocs, tc->nnodes, &orig) != 0) {
            printf("  FAIL: pmix_proc_map_create failed\n\n");
            continue;
        }

        /* Encode */
        char *encoded = NULL;
        size_t elen = 0;
        if (pmix_preg_generate(&orig, &encoded, &elen) != 0) {
            printf("  FAIL: pmix_preg_generate failed\n\n");
            pmix_proc_map_free(&orig);
            continue;
        }

        /* Display format info */
        if (elen >= 6 && strncmp(encoded, "blob2:", 6) == 0) {
            uint8_t algo = (uint8_t)encoded[6];
            const char *algo_name = (algo == 1) ? "zlib" :
                                    (algo == 2) ? "lz4" : "unknown";
            printf("  encoded: format=blob2: algo=%s length=%zu\n",
                   algo_name, elen);
        } else if (elen >= 5 && strncmp(encoded, "blob:", 5) == 0) {
            printf("  encoded: format=blob: length=%zu\n", elen);
        } else {
            printf("  encoded: format=raw: length=%zu\n", elen);
        }

        /* Decode */
        pmix_proc_map_t decoded;
        memset(&decoded, 0, sizeof(decoded));
        if (pmix_preg_parse(encoded, elen, &decoded) != 0) {
            printf("  FAIL: pmix_preg_parse failed\n\n");
            pmix_proc_map_free(&orig);
            free(encoded);
            continue;
        }

        /* Verify roundtrip integrity */
        int ok = 1;

        if (decoded.nnodes != orig.nnodes) {
            printf("  FAIL: nnodes %d != expected %d\n",
                   decoded.nnodes, orig.nnodes);
            ok = 0;
        }

        if (decoded.nprocs != orig.nprocs) {
            printf("  FAIL: nprocs %d != expected %d\n",
                   decoded.nprocs, orig.nprocs);
            ok = 0;
        }

        if (ok) {
            for (int n = 0; n < orig.nnodes; n++) {
                if (decoded.nodes[n].nranks != orig.nodes[n].nranks) {
                    printf("  FAIL: node[%d].nranks %d != expected %d\n",
                           n, decoded.nodes[n].nranks,
                           orig.nodes[n].nranks);
                    ok = 0;
                    break;
                }
                for (int r = 0; r < orig.nodes[n].nranks; r++) {
                    if (decoded.nodes[n].ranks[r] !=
                        orig.nodes[n].ranks[r]) {
                        printf("  FAIL: node[%d].ranks[%d] = %d, "
                               "expected %d\n",
                               n, r, decoded.nodes[n].ranks[r],
                               orig.nodes[n].ranks[r]);
                        ok = 0;
                        break;
                    }
                }
                if (!ok) break;
            }
        }

        if (ok) {
            printf("  PASS\n\n");
            npass++;
        } else {
            printf("\n");
        }

        pmix_proc_map_free(&orig);
        pmix_proc_map_free(&decoded);
        free(encoded);
    }

    /* --- Section 3: Backward Compatibility --- */
    printf("--- Backward Compatibility ---\n\n");

    test_num++;
    printf("[%d/%d] v1-compat: encode with v1 blob, decode with general parser\n",
           test_num, total_tests);
    {
        pmix_proc_map_t orig;
        if (pmix_proc_map_create(2000, 16, &orig) != 0) {
            printf("  FAIL: pmix_proc_map_create failed\n\n");
        } else {
            char *v1_encoded = NULL;
            size_t v1_len = 0;
            if (preg_compress_generate(&orig, &v1_encoded, &v1_len) != 0) {
                printf("  FAIL: v1 preg_compress_generate failed\n\n");
            } else {
                printf("  v1 encoded: format=blob: length=%zu\n", v1_len);

                pmix_proc_map_t decoded;
                memset(&decoded, 0, sizeof(decoded));
                if (pmix_preg_parse(v1_encoded, v1_len, &decoded) != 0) {
                    printf("  FAIL: general parser could not decode "
                           "v1 blob\n\n");
                } else {
                    int ok = 1;
                    if (decoded.nprocs != orig.nprocs ||
                        decoded.nnodes != orig.nnodes) {
                        printf("  FAIL: nprocs/nnodes mismatch after "
                               "v1 roundtrip\n\n");
                        ok = 0;
                    }
                    if (ok) {
                        for (int n = 0; n < orig.nnodes && ok; n++) {
                            for (int r = 0; r < orig.nodes[n].nranks
                                     && ok; r++) {
                                if (decoded.nodes[n].ranks[r] !=
                                    orig.nodes[n].ranks[r]) {
                                    printf("  FAIL: rank mismatch in "
                                           "v1 roundtrip at node[%d]"
                                           ".ranks[%d]\n", n, r);
                                    ok = 0;
                                }
                            }
                        }
                    }
                    if (ok) {
                        printf("  PASS\n\n");
                        npass++;
                    }
                    pmix_proc_map_free(&decoded);
                }
                free(v1_encoded);
            }
            pmix_proc_map_free(&orig);
        }
    }

    printf("=====================================================\n");
    printf("Result: %d/%d tests passed\n", npass, total_tests);

    return (npass == total_tests) ? 0 : 1;
}
