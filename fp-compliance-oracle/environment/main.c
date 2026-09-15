#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "fp_oracle.h"


static const char *class_names[] = {
    "POS_ZERO",      "NEG_ZERO",
    "POS_SUBNORMAL", "NEG_SUBNORMAL",
    "POS_NORMAL",    "NEG_NORMAL",
    "POS_INFINITY",  "NEG_INFINITY",
    "QUIET_NAN",     "SIGNALING_NAN"
};

int main(void) {
    char line[512];

    while (fgets(line, sizeof(line), stdin)) {
        char cmd[32];
        if (sscanf(line, "%31s", cmd) != 1)
            continue;

        if (strcmp(cmd, "DECODE") == 0) {
            uint64_t bits;
            if (sscanf(line + strlen("DECODE"), " %" SCNx64, &bits) != 1)
                continue;
            decoded_fp64_t d = decode_binary64(bits);
            printf("%s %d %d %" PRIu64 "\n",
                   class_names[d.cls], d.sign, d.unbiased_exp,
                   d.nan_payload);

        } else if (strcmp(cmd, "NEXTAFTER") == 0) {
            uint64_t x, y;
            if (sscanf(line + strlen("NEXTAFTER"),
                       " %" SCNx64 " %" SCNx64, &x, &y) != 2)
                continue;
            int exc = 0;
            uint64_t r = soft_nextafter(x, y, &exc);
            printf("%016" PRIX64 " %d\n", r, exc);

        } else if (strcmp(cmd, "TOTALORDER") == 0) {
            uint64_t a, b;
            if (sscanf(line + strlen("TOTALORDER"),
                       " %" SCNx64 " %" SCNx64, &a, &b) != 2)
                continue;
            printf("%d\n", soft_totalorder(a, b));

        } else if (strcmp(cmd, "COUNTEREXAMPLE") == 0) {
            int id;
            if (sscanf(line + strlen("COUNTEREXAMPLE"), " %d", &id) != 1)
                continue;
            uint64_t r = find_counterexample(id);
            printf("%016" PRIX64 "\n", r);

        } else if (strcmp(cmd, "ROUNDING") == 0) {
            uint64_t a, b;
            int opcode;
            if (sscanf(line + strlen("ROUNDING"),
                       " %" SCNx64 " %" SCNx64 " %d",
                       &a, &b, &opcode) != 3)
                continue;
            uint64_t results[4];
            eval_rounding_modes(a, b, opcode, results);
            printf("%016" PRIX64 " %016" PRIX64
                   " %016" PRIX64 " %016" PRIX64 "\n",
                   results[0], results[1], results[2], results[3]);
        }
    }

    return 0;
}
