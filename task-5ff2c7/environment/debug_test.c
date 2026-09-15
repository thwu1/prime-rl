/*
 * debug_test.c - Test harness for Keccak-f[1600] permutation debugging
 *
 * Compile: make debug_test
 * Run:     ./debug_test
 * Debug:   gdb -x debug_keccak.gdb ./debug_test
 *
 * Uses the NIST reference input block from cSHAKE128 Sample 1 to validate
 * the permutation output. Shows first byte of divergence on failure.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "keccak.h"

static int hex_to_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int hex_decode(const char *hex, uint8_t *out, size_t max_bytes) {
    size_t len = strlen(hex);
    size_t i;
    for (i = 0; i + 1 < len && i / 2 < max_bytes; i += 2) {
        int hi = hex_to_nibble(hex[i]);
        int lo = hex_to_nibble(hex[i + 1]);
        if (hi < 0 || lo < 0) return -1;
        out[i / 2] = (uint8_t)((hi << 4) | lo);
    }
    return (int)(i / 2);
}

int main(int argc, char *argv[]) {
    uint8_t state[200];
    char output_hex[401];
    int i, decoded;

    memset(state, 0, sizeof(state));

    /*
     * Default: NIST reference input block for cSHAKE128 Sample 1.
     * This is bytepad(encode_string("") || encode_string("Email Signature"), 168)
     * XORed into the all-zeros initial state.
     */
    const char *input_hex =
        "01a801000178456d61696c205369676e61747572650000000000000000"
        "0000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000"
        "000000000000000000000000000000000000000000000000000000";

    const char *expected_hex =
        "194ccd058b2a83d60229dc6984d14f158b694fa4bd39b21f84fb06c8cb"
        "c67b842def9e2bdbf0f8e1bd14eaccdc582684624b41b64a0851068179"
        "fdfbcadb731e17593647ed96c6e35cda77069754f5f825664292c67978"
        "fcb7bd5831ed1076a6fd14f34fffab28729660ab82df4afdff81ef671c"
        "9181e5c6eb8227f6a072c8e29178282ee5a9e683925e97c5f15f716823"
        "b8e1056c7dc84614947e4a31ece00d8b1edab478740e824178e7c28065"
        "c0c5cc84749cad7fc3c60de727618b56fe3af003fdd5ab025428";

    if (argc > 1) {
        input_hex = argv[1];
    }

    decoded = hex_decode(input_hex, state, 200);
    if (decoded < 0) {
        fprintf(stderr, "Error: invalid hex input\n");
        return 1;
    }

    printf("Input (%d bytes, first 20): ", decoded);
    for (i = 0; i < 20 && i < decoded; i++) printf("%02x", state[i]);
    printf("...\n");

    /* Apply the Keccak-f[1600] permutation */
    keccak_f1600(state);

    /* Format output as hex */
    for (i = 0; i < 200; i++) {
        sprintf(output_hex + 2 * i, "%02x", state[i]);
    }
    output_hex[400] = '\0';

    printf("Output:   %.80s...\n", output_hex);
    printf("Expected: %.80s...\n", expected_hex);

    if (strcmp(output_hex, expected_hex) == 0) {
        printf("\nPASS: Keccak-f[1600] output matches NIST reference\n");
        return 0;
    } else {
        printf("\nFAIL: Output does not match NIST reference\n");
        for (i = 0; i < 400; i++) {
            if (output_hex[i] != expected_hex[i]) {
                printf("First difference at hex position %d (byte %d, lane [%d][%d])\n",
                       i, i / 2, (i / 2 / 8) % 5, (i / 2 / 8) / 5);
                break;
            }
        }
        return 1;
    }
}
