/*
 * main.c - Interactive test driver for the HSM engine
 *
 * Reads single-letter commands from stdin, dispatches events to the
 * test state machine, and prints action traces to stdout.
 *
 * Commands:
 *   INIT        Initialize the state machine
 *   P..X        Dispatch the corresponding signal
 *   STATE       Print current state name
 *   FOO         Print current guard variable value
 */

#include "hsm.h"
#include "test_sm.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

int main(void) {
    char line[64];

    TestSM_ctor(&test_sm);

    while (fgets(line, sizeof(line), stdin) != NULL) {
        /* Strip trailing newline/carriage return */
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        if (len == 0) continue;

        if (strcmp(line, "INIT") == 0) {
            HsmEvent evt = {0};
            hsm_init((Hsm *)&test_sm, &evt);
            printf("\n");
            fflush(stdout);
        }
        else if (strcmp(line, "STATE") == 0) {
            printf("%s\n", TestSM_state_name(&test_sm));
            fflush(stdout);
        }
        else if (strcmp(line, "FOO") == 0) {
            printf("%u\n", (unsigned)TestSM_get_foo(&test_sm));
            fflush(stdout);
        }
        else {
            /* Map command string to signal */
            int sig = -1;
            if (strcmp(line, "P") == 0) sig = P_SIG;
            else if (strcmp(line, "Q") == 0) sig = Q_SIG;
            else if (strcmp(line, "R") == 0) sig = R_SIG;
            else if (strcmp(line, "S") == 0) sig = S_SIG;
            else if (strcmp(line, "T") == 0) sig = T_SIG;
            else if (strcmp(line, "U") == 0) sig = U_SIG;
            else if (strcmp(line, "V") == 0) sig = V_SIG;
            else if (strcmp(line, "W") == 0) sig = W_SIG;
            else if (strcmp(line, "X") == 0) sig = X_SIG;

            if (sig >= 0) {
                HsmEvent evt = {(uint16_t)sig};
                hsm_dispatch((Hsm *)&test_sm, &evt);
                printf("\n");
                fflush(stdout);
            }
            else {
                fprintf(stderr, "Unknown command: %s\n", line);
            }
        }
    }
    return 0;
}
