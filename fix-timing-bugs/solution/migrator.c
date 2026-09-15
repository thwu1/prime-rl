/*
 * migrator.c - Convert buggy recordings to corrected timing format
 *
 * The original recorder has two interacting timing bugs:
 *
 *   1. The initial time reference uses time(NULL) which has only
 *      whole-second granularity, making the first timing entry's
 *      delay a random 0-1s value unrelated to actual subprocess timing.
 *
 *   2. gettimeofday() is called before read(), not after.  This means
 *      each timing delta measures the interval from the start of one
 *      read to the start of the next, rather than the time spent
 *      blocking in read.  The result is a persistent off-by-one shift:
 *      buggy_delay[i] for i >= 1 actually represents the correct delay
 *      for entry i-1.
 *
 * This tool applies the inverse transformation:
 *   corrected_delay[i] = buggy_delay[i+1]   for i = 0 .. N-2
 *   corrected_delay[N-1] = 0.0              (unrecoverable)
 *
 * Byte counts remain associated with their original entry positions.
 * The data file is copied unchanged.
 *
 * Usage: migrator [-d indata] [-t intiming] [-D outdata] [-T outtiming]
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_ENTRIES    100000
#define DEFAULT_IN_D   "recording.dat"
#define DEFAULT_IN_T   "recording.tim"
#define DEFAULT_OUT_D  "migrated.dat"
#define DEFAULT_OUT_T  "migrated.tim"

typedef struct {
    double delay;
    long   bytes;
} timing_entry;

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [options]\n\n"
        "  -d FILE   Input data file     (default: %s)\n"
        "  -t FILE   Input timing file   (default: %s)\n"
        "  -D FILE   Output data file    (default: %s)\n"
        "  -T FILE   Output timing file  (default: %s)\n"
        "  -h        Show help\n",
        prog, DEFAULT_IN_D, DEFAULT_IN_T,
        DEFAULT_OUT_D, DEFAULT_OUT_T);
}

static void skip_headers(FILE *fp) {
    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (c == '#') {
            while ((c = fgetc(fp)) != EOF && c != '\n')
                ;
        } else {
            ungetc(c, fp);
            return;
        }
    }
}

static int copy_file(const char *src, const char *dst) {
    FILE *fin = fopen(src, "rb");
    FILE *fout;
    char buf[4096];
    size_t n;

    if (!fin) {
        fprintf(stderr, "cannot open input data file: %s\n", src);
        return -1;
    }
    fout = fopen(dst, "wb");
    if (!fout) {
        fprintf(stderr, "cannot open output data file: %s\n", dst);
        fclose(fin);
        return -1;
    }

    while ((n = fread(buf, 1, sizeof(buf), fin)) > 0)
        fwrite(buf, 1, n, fout);

    fclose(fin);
    fclose(fout);
    return 0;
}

int main(int argc, char **argv) {
    const char *in_data   = DEFAULT_IN_D;
    const char *in_timing = DEFAULT_IN_T;
    const char *out_data  = DEFAULT_OUT_D;
    const char *out_timing = DEFAULT_OUT_T;
    int opt;
    FILE *ftin, *ftout;
    timing_entry entries[MAX_ENTRIES];
    int count = 0;
    int i;

    while ((opt = getopt(argc, argv, "d:t:D:T:h")) != -1) {
        switch (opt) {
        case 'd': in_data    = optarg; break;
        case 't': in_timing  = optarg; break;
        case 'D': out_data   = optarg; break;
        case 'T': out_timing = optarg; break;
        case 'h': usage(argv[0]); return 0;
        default:  usage(argv[0]); return 1;
        }
    }

    /* ---- Read all timing entries ---- */
    ftin = fopen(in_timing, "r");
    if (!ftin) {
        fprintf(stderr, "cannot open input timing file: %s\n", in_timing);
        return 1;
    }

    skip_headers(ftin);

    while (count < MAX_ENTRIES &&
           fscanf(ftin, "%lf %ld", &entries[count].delay,
                  &entries[count].bytes) == 2) {
        count++;
    }
    fclose(ftin);

    if (count == 0) {
        fprintf(stderr, "no timing entries found in %s\n", in_timing);
        return 1;
    }

    /* ---- Apply inverse transformation ---- */
    ftout = fopen(out_timing, "w");
    if (!ftout) {
        fprintf(stderr, "cannot open output timing file: %s\n",
                out_timing);
        return 1;
    }

    for (i = 0; i < count; i++) {
        double corrected_delay;
        if (i < count - 1) {
            /* Shift delay from the next buggy entry into this position */
            corrected_delay = entries[i + 1].delay;
        } else {
            /* Last entry: correct delay is unrecoverable */
            corrected_delay = 0.0;
        }
        fprintf(ftout, "%f %ld\n", corrected_delay, entries[i].bytes);
    }

    fclose(ftout);

    /* ---- Copy data file unchanged ---- */
    if (copy_file(in_data, out_data) != 0)
        return 1;

    return 0;
}
