/*
 * Naive double-to-string converter using %.17g format.
 * Reads 16-char hex IEEE 754 bit patterns from stdin (one per line).
 * Outputs the %.17g formatted string for each value.
 * Always round-trip safe, but NOT the shortest representation.
 *
 * Usage: sqlite3 /app/challenge.db \
 *   "SELECT hex_bits FROM ieee754_values ORDER BY id" \
 *   | ./build/naive_convert
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <math.h>

int main(void) {
    char line[64];
    while (fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '\0') continue;

        uint64_t bits;
        if (sscanf(line, "%" SCNx64, &bits) != 1) {
            fprintf(stderr, "Bad hex: %s\n", line);
            continue;
        }

        double d;
        memcpy(&d, &bits, sizeof(d));

        if (isnan(d)) {
            printf("NaN\n");
        } else if (isinf(d)) {
            printf("%sInf\n", d < 0 ? "-" : "");
        } else if (d == 0.0 && signbit(d)) {
            printf("-0\n");
        } else if (d == 0.0) {
            printf("0\n");
        } else {
            printf("%.17g\n", d);
        }
    }
    return 0;
}
