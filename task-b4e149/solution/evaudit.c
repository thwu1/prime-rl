/*
 * evaudit - Validate recording integrity
 *
 * Usage: evaudit <timing_file> <data_file>
 *
 * Audits a recording produced by evrecord for defects including
 * malformed entries, anomalous timing, byte count mismatches,
 * and negative delays.
 *
 * Exit code: 0 = PASS, 1 = FAIL
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "common.h"

#define ANOMALOUS_DELAY_THRESHOLD 0.5

/*
 * compute_data_bytes - Count raw recorded content bytes in a data file
 *
 * The data file format is:
 *   [header lines starting with '#']
 *   [raw recorded output]
 *   [\n# Session ended (...)\n]
 *
 * This function skips leading header lines and the trailing footer,
 * returning only the byte count of raw recorded output.
 */
static long compute_data_bytes(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return -1;

    /* Skip leading header lines (lines starting with '#') */
    int c;
    long header_end = 0;
    for (;;) {
        long pos = ftell(f);
        c = fgetc(f);
        if (c == EOF) {
            header_end = pos;
            break;
        }
        if (c == '#') {
            while ((c = fgetc(f)) != EOF && c != '\n')
                ;
            header_end = ftell(f);
        } else {
            header_end = pos;
            break;
        }
    }

    /* Get file size and compute content length after header */
    fseek(f, 0, SEEK_END);
    long file_size = ftell(f);
    long content_len = file_size - header_end;

    if (content_len <= 0) {
        fclose(f);
        return 0;
    }

    /* Read content after header into buffer */
    char *buf = malloc(content_len);
    if (!buf) {
        fclose(f);
        return -1;
    }

    fseek(f, header_end, SEEK_SET);
    size_t nread = fread(buf, 1, content_len, f);
    fclose(f);

    /*
     * Search backwards for footer marker "\n# Session ended"
     * The recorder writes: fprintf(fdata, "\n# Session ended (%.3f seconds)\n", ...)
     * so the footer always starts with \n followed by "# Session ended"
     */
    const char *marker = "\n# Session ended";
    size_t mlen = strlen(marker);
    long footer_pos = (long)nread;  /* default: no footer found */

    if (nread >= mlen) {
        for (long i = (long)nread - (long)mlen; i >= 0; i--) {
            if (memcmp(buf + i, marker, mlen) == 0) {
                footer_pos = i;
                break;
            }
        }
    }

    free(buf);
    return footer_pos;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <timing_file> <data_file>\n", argv[0]);
        return 1;
    }

    /* Parse timing file */
    FILE *ft = fopen(argv[1], "r");
    if (!ft) {
        perror("evaudit: open timing file");
        return 1;
    }

    int entries = 0;
    size_t timing_bytes = 0;
    double first_delay = 0.0;
    int negative_count = 0;
    double delay;
    size_t blk;

    while (fscanf(ft, "%lf %zu", &delay, &blk) == 2) {
        entries++;
        timing_bytes += blk;
        if (entries == 1)
            first_delay = delay;
        if (delay < 0.0)
            negative_count++;
    }
    fclose(ft);

    /* Compute raw data content size (excluding header/footer metadata) */
    long data_bytes = compute_data_bytes(argv[2]);
    if (data_bytes < 0) {
        fprintf(stderr, "evaudit: cannot read data file '%s'\n", argv[2]);
        return 1;
    }

    /* Evaluate checks */
    int byte_match = ((long)timing_bytes == data_bytes);
    int first_ok = (entries > 0 && first_delay < ANOMALOUS_DELAY_THRESHOLD);
    int pass = (entries > 0 && byte_match && first_ok && negative_count == 0);

    /* Print structured report */
    printf("=== Recording Audit ===\n");
    printf("Timing entries: %d\n", entries);
    printf("Total bytes (timing): %zu\n", timing_bytes);
    printf("Total bytes (data): %ld\n", data_bytes);
    printf("Byte match: %s\n", byte_match ? "yes" : "no");
    if (entries > 0)
        printf("First delay: %.6fs [%s]\n", first_delay,
               first_ok ? "ok" : "anomalous");
    printf("Negative delays: %d\n", negative_count);
    printf("Verdict: %s\n", pass ? "PASS" : "FAIL");

    return pass ? 0 : 1;
}
