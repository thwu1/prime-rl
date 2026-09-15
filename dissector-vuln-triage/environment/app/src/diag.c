#include <stdio.h>
#include <string.h>
#include "ndp.h"

/*
 * DIAG payload:
 *   [0]     command   uint8
 *   [1-2]   arg_len   uint16_be
 *   [3..]   argument  variable (printable ASCII)
 */

int handle_diag(const uint8_t *payload, size_t len, uint8_t flags) {
    (void)flags;

    if (len < 3) {
        fprintf(stderr, "DIAG: payload too short\n");
        return -1;
    }

    uint8_t command = payload[0];
    uint16_t arg_len = read_u16_be(payload + 1);

    if (3 + (size_t)arg_len > len) {
        fprintf(stderr, "DIAG: argument extends past payload\n");
        return -1;
    }

    /* Safely copy argument with bounds check */
    char cmd_arg[DIAG_CMD_BUF];
    size_t copy_len = arg_len;
    if (copy_len >= sizeof(cmd_arg)) {
        copy_len = sizeof(cmd_arg) - 1;
    }
    memcpy(cmd_arg, payload + 3, copy_len);
    cmd_arg[copy_len] = '\0';

    switch (command) {
        case DIAG_CMD_STATUS:
            printf("DIAG: status query arg=\"%s\"\n", cmd_arg);
            break;
        case DIAG_CMD_RESET:
            printf("DIAG: reset arg=\"%s\"\n", cmd_arg);
            break;
        case DIAG_CMD_QUERY:
            printf("DIAG: query arg=\"%s\"\n", cmd_arg);
            break;
        default:
            fprintf(stderr, "DIAG: unknown command 0x%02X\n", command);
            return -1;
    }

    return 0;
}
