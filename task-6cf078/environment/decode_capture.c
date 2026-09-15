/*
 * decode_capture.c - CLI tool to decode COBS-postcard binary captures
 *
 * Usage: decode_capture <capture.bin>
 * Outputs: JSON array to stdout, summary to stderr.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "cobs_postcard.h"

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <capture.bin>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (fsize < 8) {
        fprintf(stderr, "File too short for header\n");
        fclose(f);
        return 1;
    }

    uint8_t *raw = malloc((size_t)fsize);
    if (!raw) {
        fprintf(stderr, "Out of memory\n");
        fclose(f);
        return 1;
    }
    if (fread(raw, 1, (size_t)fsize, f) != (size_t)fsize) {
        fprintf(stderr, "Read error\n");
        free(raw);
        fclose(f);
        return 1;
    }
    fclose(f);

    if (memcmp(raw, "PCOB", 4) != 0) {
        fprintf(stderr, "Bad magic: expected PCOB\n");
        free(raw);
        return 1;
    }

    uint8_t *stream = raw + 8;
    size_t stream_len = (size_t)fsize - 8;

    int frame_idx = 0;
    int valid_count = 0;
    int corrupt_count = 0;
    size_t pos = 0;

    printf("[\n");
    int first = 1;

    while (pos < stream_len) {
        size_t start = pos;
        while (pos < stream_len && stream[pos] != 0x00)
            pos++;

        size_t frame_len = pos - start;
        if (pos < stream_len) pos++;

        if (frame_len == 0) continue;

        uint8_t decoded[4096];
        size_t decoded_len;

        if (cobs_decode(stream + start, frame_len,
                        decoded, sizeof(decoded), &decoded_len) != 0) {
            corrupt_count++;
            frame_idx++;
            continue;
        }

        sensor_reading_t reading;
        if (decode_reading(decoded, decoded_len, &reading) != 0) {
            corrupt_count++;
            frame_idx++;
            continue;
        }

        if (!first) printf(",\n");
        first = 0;

        printf("  {\"frame_idx\": %d, "
               "\"sensor_id\": %u, "
               "\"timestamp_ms\": %" PRIu64 ", "
               "\"temperature_cdeg\": %" PRId32 ", "
               "\"humidity_pct_x10\": %u, "
               "\"pressure_pa\": %" PRIu32 ", "
               "\"battery_mv\": %u, "
               "\"status\": \"%s\", "
               "\"num_sub_readings\": %zu, "
               "\"sub_readings\": [",
               frame_idx,
               (unsigned)reading.sensor_id,
               reading.timestamp_ms,
               reading.temperature_cdeg,
               (unsigned)reading.humidity_pct_x10,
               reading.pressure_pa,
               (unsigned)reading.battery_mv,
               status_name(reading.status),
               reading.num_sub_readings);

        for (size_t i = 0; i < reading.num_sub_readings; i++) {
            if (i > 0) printf(", ");
            printf("%d", reading.sub_readings[i]);
        }
        printf("]}");

        valid_count++;
        frame_idx++;
    }

    printf("\n]\n");

    fprintf(stderr, "Total: %d frames, Valid: %d, Corrupted: %d\n",
            frame_idx, valid_count, corrupt_count);

    free(raw);
    return 0;
}
