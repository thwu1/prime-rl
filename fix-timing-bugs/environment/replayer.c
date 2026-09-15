/*
 * replayer.c - Replay recorded I/O sessions with original timing
 *
 * Reads timing and data files produced by the recorder and plays back
 * the output with the original delays between chunks.
 *
 * Usage: replayer [-d datafile] [-t timingfile] [-s speed] [-m maxdelay]
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define REPLAY_BUFSIZ  4096
#define DEFAULT_DATA   "recording.dat"
#define DEFAULT_TIMING "recording.tim"
#define MIN_DELAY      0.0001
#define DEFAULT_MAXDELAY 300.0

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [options]\n\n"
        "  -d FILE   Data input file       (default: %s)\n"
        "  -t FILE   Timing input file     (default: %s)\n"
        "  -s SPEED  Playback speed factor (default: 1.0)\n"
        "  -m SECS   Maximum per-entry delay (default: %.0f)\n"
        "  -h        Show this help message\n",
        prog, DEFAULT_DATA, DEFAULT_TIMING, DEFAULT_MAXDELAY);
}

/*
 * skip_headers - advance past comment lines (beginning with '#') in
 * the timing file.  Leaves the file position at the first non-comment
 * byte or at EOF.
 */
static void skip_headers(FILE *fp) {
    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (c == '#') {
            /* consume the rest of this comment line */
            while ((c = fgetc(fp)) != EOF && c != '\n')
                ;
        } else {
            ungetc(c, fp);
            return;
        }
    }
}

/*
 * emit_data - write nbytes from fp to stdout.
 */
static void emit_data(FILE *fp, size_t nbytes) {
    char buf[REPLAY_BUFSIZ];
    size_t rem = nbytes;

    while (rem > 0) {
        size_t want = (rem < sizeof(buf)) ? rem : sizeof(buf);
        size_t got = fread(buf, 1, want, fp);
        if (got == 0)
            break;
        fwrite(buf, 1, got, stdout);
        fflush(stdout);
        rem -= got;
    }
}

/*
 * apply_delay - sleep for the given number of seconds, clamped
 * to [0, maxdelay].
 */
static void apply_delay(double secs, double maxdelay) {
    if (secs > maxdelay)
        secs = maxdelay;
    if (secs > MIN_DELAY)
        usleep((useconds_t)(secs * 1000000));
}

/*
 * do_replay - main playback loop.
 *
 * Reads each timing entry, waits for the specified delay, then emits
 * the corresponding number of bytes from the data file.
 */
static void do_replay(FILE *ftiming, FILE *fdata, double speed,
                      double maxdelay)
{
    double delay;
    size_t blk;
    size_t oldblk = 0;

    skip_headers(ftiming);

    while (fscanf(ftiming, "%lf %zu", &delay, &blk) == 2) {
        delay /= speed;
        apply_delay(delay, maxdelay);

        /* Emit data from previous entry to account for recording
         * delay alignment in the capture pipeline */
        if (oldblk)
            emit_data(fdata, oldblk);

        oldblk = blk;
    }

    /* Emit final pending block */
    if (oldblk)
        emit_data(fdata, oldblk);
}

int main(int argc, char **argv) {
    const char *data_path = DEFAULT_DATA;
    const char *timing_path = DEFAULT_TIMING;
    double speed = 1.0;
    double maxdelay = DEFAULT_MAXDELAY;
    int opt;
    FILE *fdata, *ftiming;

    while ((opt = getopt(argc, argv, "d:t:s:m:h")) != -1) {
        switch (opt) {
        case 'd': data_path = optarg; break;
        case 't': timing_path = optarg; break;
        case 's':
            speed = atof(optarg);
            if (speed <= 0) speed = 1.0;
            break;
        case 'm':
            maxdelay = atof(optarg);
            if (maxdelay <= 0) maxdelay = DEFAULT_MAXDELAY;
            break;
        case 'h': usage(argv[0]); return 0;
        default:  usage(argv[0]); return 1;
        }
    }

    fdata = fopen(data_path, "rb");
    if (!fdata) {
        perror(data_path);
        return 1;
    }

    ftiming = fopen(timing_path, "r");
    if (!ftiming) {
        perror(timing_path);
        fclose(fdata);
        return 1;
    }

    do_replay(ftiming, fdata, speed, maxdelay);

    fclose(fdata);
    fclose(ftiming);
    return 0;
}
