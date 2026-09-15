#include <stdio.h>
#include <string.h>
#include "ndp.h"

/*
 * PROBE payload:
 *   [0-3]  sequence_num  uint32_be
 *   [4-7]  timestamp     uint32_be
 *   [8..]  echo_data     variable (optional)
 */
int handle_probe(const uint8_t *payload, size_t len, uint8_t flags) {
    if (len < 8) {
        fprintf(stderr, "PROBE: payload too short (%zu < 8)\n", len);
        return -1;
    }

    uint32_t seq = read_u32_be(payload);
    uint32_t ts = read_u32_be(payload + 4);
    size_t echo_len = len - 8;

    printf("PROBE: seq=%u timestamp=%u echo_bytes=%zu\n", seq, ts, echo_len);

    if ((flags & NDP_FLAG_VERBOSE) && echo_len > 0) {
        printf("PROBE echo: ");
        size_t display = echo_len > 64 ? 64 : echo_len;
        for (size_t i = 0; i < display; i++) {
            printf("%02x", payload[8 + i]);
        }
        if (echo_len > 64)
            printf("...");
        printf("\n");
    }

    return 0;
}
