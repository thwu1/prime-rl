/*
 * validator.c - Recording integrity checker
 *
 * Validates that a timing file and data file are internally consistent.
 *
 * Checks:
 *   - Sum of byte counts across timing entries equals data file size
 *   - No timing entry has a negative delay value
 *
 * Usage: validator [-d datafile] [-t timingfile]
 *
 * Exits 0 silently if valid, 1 with diagnostic on stderr if invalid.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

#define DEFAULT_DATA   "recording.dat"
#define DEFAULT_TIMING "recording.tim"

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [options]\n\n"
        "  -d FILE   Data file    (default: %s)\n"
        "  -t FILE   Timing file  (default: %s)\n"
        "  -h        Show help\n",
        prog, DEFAULT_DATA, DEFAULT_TIMING);
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

int main(int argc, char **argv) {
    const char *data_path = DEFAULT_DATA;
    const char *timing_path = DEFAULT_TIMING;
    int opt;
    FILE *ftiming;
    struct stat st;
    double delay;
    long bytes;
    long total_bytes = 0;
    int entry_num = 0;
    int errors = 0;

    while ((opt = getopt(argc, argv, "d:t:h")) != -1) {
        switch (opt) {
        case 'd': data_path = optarg; break;
        case 't': timing_path = optarg; break;
        case 'h': usage(argv[0]); return 0;
        default:  usage(argv[0]); return 1;
        }
    }

    if (stat(data_path, &st) != 0) {
        fprintf(stderr, "cannot stat data file: %s\n", data_path);
        return 1;
    }

    ftiming = fopen(timing_path, "r");
    if (!ftiming) {
        fprintf(stderr, "cannot open timing file: %s\n", timing_path);
        return 1;
    }

    skip_headers(ftiming);

    while (fscanf(ftiming, "%lf %ld", &delay, &bytes) == 2) {
        entry_num++;
        if (delay < 0) {
            fprintf(stderr, "entry %d: negative delay %.6f\n",
                    entry_num, delay);
            errors++;
        }
        if (bytes < 0) {
            fprintf(stderr, "entry %d: negative byte count %ld\n",
                    entry_num, bytes);
            errors++;
        }
        total_bytes += bytes;
    }

    fclose(ftiming);

    if (total_bytes != (long)st.st_size) {
        fprintf(stderr,
                "byte count mismatch: timing total %ld, "
                "data file %ld bytes\n",
                total_bytes, (long)st.st_size);
        errors++;
    }

    return errors > 0 ? 1 : 0;
}
