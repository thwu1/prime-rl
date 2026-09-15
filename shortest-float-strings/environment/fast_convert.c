/*
 * Fast (but buggy) double-to-shortest-string converter.
 * Uses iterative precision search with C's %e format.
 *
 * Reads 16-char hex IEEE 754 bit patterns from stdin (one per line).
 * Outputs attempted "shortest" representations.
 *
 * Build: make (builds both naive_convert and fast_convert)
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

        /* Handle NaN and Inf correctly */
        if (isnan(d)) {
            printf("NaN\n");
            continue;
        }
        if (isinf(d)) {
            printf("%sInf\n", d < 0 ? "-" : "");
            continue;
        }

        /* BUG 1: Does not detect negative zero.
         * Outputs "0" for both +0 and -0. */
        if (d == 0.0) {
            printf("0\n");
            continue;
        }

        double ad = fabs(d);
        uint64_t target;
        memcpy(&target, &ad, sizeof(target));

        const char *sign = (d < 0) ? "-" : "";
        char best[64];
        int found = 0;

        /* Find minimum precision p such that %.*e round-trips.
         *
         * BUG 2: C's %e format pads exponents to >= 2 digits and
         *   always includes sign (+/-) in the exponent.
         *   e.g., outputs "1.5e-07" instead of "1.5e-7",
         *         outputs "1e+03" instead of "1e3".
         *
         * BUG 3: Only considers scientific notation (%e), never
         *   tries fixed notation. Even when fixed is shorter
         *   (e.g., "0.5" vs "5e-01"), always outputs scientific. */
        for (int p = 0; p < 17; p++) {
            char buf[64];
            snprintf(buf, sizeof(buf), "%.*e", p, ad);
            double parsed = strtod(buf, NULL);
            uint64_t parsed_bits;
            memcpy(&parsed_bits, &parsed, sizeof(parsed_bits));
            if (parsed_bits == target) {
                snprintf(best, sizeof(best), "%s%s", sign, buf);
                found = 1;
                break;
            }
        }

        if (!found) {
            snprintf(best, sizeof(best), "%s%.16e", sign, ad);
        }

        printf("%s\n", best);
    }
    return 0;
}
