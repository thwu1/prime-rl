/*
 * test_driver.c — Command-line test driver for posit16 library
 *
 */

#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include "posit16.h"

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <convert|binop|fdp>\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "convert") == 0) {
        /* Dump p16_to_f64 for all 65536 values */
        for (uint32_t i = 0; i < 65536; i++) {
            posit16_t p = {(uint16_t)i};
            double d = p16_to_f64(p);
            printf("%04x %.17g\n", i, d);
        }
    }
    else if (strcmp(argv[1], "binop") == 0) {
        /* Read "OP HEX_A HEX_B" lines, output result hex */
        char op[16];
        unsigned int va, vb;
        while (scanf("%15s %x %x", op, &va, &vb) == 3) {
            posit16_t pa = {(uint16_t)va}, pb = {(uint16_t)vb};
            posit16_t result;

            if      (strcmp(op, "MUL") == 0) result = p16_mul(pa, pb);
            else if (strcmp(op, "DIV") == 0) result = p16_div(pa, pb);
            else if (strcmp(op, "ADD") == 0) result = p16_add(pa, pb);
            else if (strcmp(op, "SUB") == 0) result = p16_sub(pa, pb);
            else result = P16_NAR;

            printf("%04x\n", result.v);
        }
    }
    else if (strcmp(argv[1], "fdp") == 0) {
        /* Fused dot product: each line is "N a1 b1 a2 b2 ... aN bN" (hex) */
        int n;
        while (scanf("%d", &n) == 1) {
            quire16_t q = q16_clr();
            for (int i = 0; i < n; i++) {
                unsigned int va, vb;
                if (scanf("%x %x", &va, &vb) != 2) break;
                posit16_t pa = {(uint16_t)va}, pb = {(uint16_t)vb};
                q = q16_fdp_add(q, pa, pb);
            }
            posit16_t result = q16_to_p16(q);
            printf("%04x\n", result.v);
        }
    }
    else {
        fprintf(stderr, "Unknown mode: %s\n", argv[1]);
        return 1;
    }

    return 0;
}
