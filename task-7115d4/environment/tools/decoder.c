/*
 * ICFP Binary Format (icfpbin_v1) Decoder
 *
 * Reads binary-encoded ICFP tokens from a file (argument) or stdin.
 * Format: each token is [2-byte big-endian uint16 length][ASCII token bytes]
 * Outputs space-separated plaintext tokens to stdout.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

int main(int argc, char *argv[]) {
    FILE *f;
    if (argc > 1) {
        f = fopen(argv[1], "rb");
        if (!f) {
            fprintf(stderr, "Error: cannot open '%s'\n", argv[1]);
            return 1;
        }
    } else {
        f = stdin;
    }

    int first = 1;
    unsigned char len_buf[2];

    while (fread(len_buf, 1, 2, f) == 2) {
        uint16_t len = ((uint16_t)len_buf[0] << 8) | len_buf[1];

        char *token = (char *)malloc(len + 1);
        if (!token) {
            fprintf(stderr, "Error: memory allocation failed\n");
            if (f != stdin) fclose(f);
            return 1;
        }

        if (fread(token, 1, len, f) != (size_t)len) {
            fprintf(stderr, "Error: truncated input at token boundary\n");
            free(token);
            if (f != stdin) fclose(f);
            return 1;
        }
        token[len] = '\0';

        if (!first) putchar(' ');
        fputs(token, stdout);
        first = 0;

        free(token);
    }

    putchar('\n');
    if (f != stdin) fclose(f);
    return 0;
}
