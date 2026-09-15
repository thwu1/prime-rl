/*
 * Frame validator: reads a binary capture file, COBS-decodes frames,
 * validates CRC-8 checksum on each frame, and reports results.
 *
 * Usage:
 *   frame_validator <capture.bin>           # human-readable output
 *   frame_validator <capture.bin> --json    # JSON output
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "crc8.h"

#define MAX_FRAME 8192

/*
 * COBS decode. Returns decoded length, or -1 on error.
 */
static int cobs_decode(const uint8_t *enc, size_t enc_len, uint8_t *out) {
    size_t ei = 0, oi = 0;
    while (ei < enc_len) {
        uint8_t code = enc[ei++];
        if (code == 0) return -1;
        for (uint8_t i = 1; i < code; i++) {
            if (ei >= enc_len) return -1;
            out[oi++] = enc[ei++];
        }
        if (code < 0xFF && ei < enc_len) {
            out[oi++] = 0;
        }
    }
    return (int)oi;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <capture.bin> [--json]\n", argv[0]);
        return 1;
    }

    int json_out = (argc > 2 && strcmp(argv[2], "--json") == 0);

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 1; }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    uint8_t *data = (uint8_t *)malloc(fsize);
    if (!data) { perror("malloc"); fclose(f); return 1; }
    fread(data, 1, fsize, f);
    fclose(f);

    int frame_idx = 0;
    long start = 0;

    if (json_out) printf("[\n");

    for (long i = 0; i <= fsize; i++) {
        if (i == fsize || data[i] == 0x00) {
            size_t frame_len = i - start;
            if (frame_len > 0) {
                uint8_t decoded[MAX_FRAME];
                int dec_len = cobs_decode(data + start, frame_len, decoded);

                if (dec_len > 0) {
                    uint8_t stored_crc = decoded[dec_len - 1];
                    uint8_t computed_crc = crc8_compute(decoded, dec_len - 1);
                    int valid = (stored_crc == computed_crc);

                    if (json_out) {
                        if (frame_idx > 0) printf(",\n");
                        printf("  {\"frame_index\": %d, \"payload_bytes\": %d, "
                               "\"crc_stored\": %u, \"crc_computed\": %u, "
                               "\"crc_valid\": %s, \"key_hex\": \"",
                               frame_idx, dec_len - 1,
                               stored_crc, computed_crc,
                               valid ? "true" : "false");
                        for (int k = 0; k < 8 && k < dec_len - 1; k++)
                            printf("%02x", decoded[k]);
                        printf("\"}");
                    } else {
                        printf("Frame %d: %d payload bytes, CRC stored=0x%02x "
                               "computed=0x%02x %s, key=",
                               frame_idx, dec_len - 1,
                               stored_crc, computed_crc,
                               valid ? "OK" : "FAIL");
                        for (int k = 0; k < 8 && k < dec_len - 1; k++)
                            printf("%02x", decoded[k]);
                        printf("\n");
                    }
                }
                frame_idx++;
            }
            start = i + 1;
        }
    }

    if (json_out) printf("\n]\n");

    free(data);
    return 0;
}
