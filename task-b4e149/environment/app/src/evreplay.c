/*
 * evreplay - Replay a recorded session with timing
 *
 * Usage: evreplay <timing_file> <data_file> [speed_factor]
 *
 * Replays the session recorded by evrecord, reproducing the original
 * timing between output events. An optional speed factor can be used
 * to accelerate (>1.0) or slow down (<1.0) the replay.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <time.h>
#include "common.h"

static int emit_bytes(FILE *fdata, size_t count)
{
    char buf[EVREC_BUF_SIZE];
    size_t remaining = count;

    while (remaining > 0) {
        size_t to_read = remaining < sizeof(buf) ? remaining : sizeof(buf);
        size_t got = fread(buf, 1, to_read, fdata);
        if (got == 0) {
            if (feof(fdata)) {
                fprintf(stderr, "evreplay: unexpected end of data file\n");
                return -1;
            }
            return -1;
        }
        fwrite(buf, 1, got, stdout);
        fflush(stdout);
        remaining -= got;
    }
    return 0;
}

static void delay_for(double seconds)
{
    if (seconds <= 0.0)
        return;

    struct timeval target, now, diff;
    gettimeofday(&target, NULL);
    target.tv_sec += (long)seconds;
    target.tv_usec += (long)((seconds - (long)seconds) * 1000000);
    if (target.tv_usec >= 1000000) {
        target.tv_sec++;
        target.tv_usec -= 1000000;
    }

    for (;;) {
        gettimeofday(&now, NULL);
        if (now.tv_sec > target.tv_sec ||
            (now.tv_sec == target.tv_sec && now.tv_usec >= target.tv_usec))
            break;

        diff.tv_sec = target.tv_sec - now.tv_sec;
        diff.tv_usec = target.tv_usec - now.tv_usec;
        if (diff.tv_usec < 0) {
            diff.tv_sec--;
            diff.tv_usec += 1000000;
        }

        if (diff.tv_sec > 0) {
            sleep(1);
        } else {
            usleep((useconds_t)diff.tv_usec);
        }
    }
}

static void skip_header(FILE *fdata)
{
    int c;
    long pos;

    for (;;) {
        pos = ftell(fdata);
        c = fgetc(fdata);
        if (c == EOF) {
            break;
        } else if (c == '#') {
            while ((c = fgetc(fdata)) != EOF && c != '\n')
                ;
        } else {
            fseek(fdata, pos, SEEK_SET);
            break;
        }
    }
}

/*
 * replay_session - Main replay loop
 *
 * Reads timing entries and emits the corresponding data chunks with
 * appropriate delays to reproduce the original session timing.
 */
static int replay_session(FILE *ftiming, FILE *fdata, double speed)
{
    double delay;
    size_t blk;
    size_t prev_blk = 0;
    int entry_num = 0;

    skip_header(fdata);

    while (fscanf(ftiming, "%lf %zu", &delay, &blk) == 2) {
        entry_num++;

        /* Apply speed factor to delay */
        double adjusted_delay = delay / speed;

        /* Wait for the specified delay */
        if (adjusted_delay > 0.001) {
            delay_for(adjusted_delay);
        }

        /*
         * Emit the data chunk from the previous timing entry.
         * The recording has a known one-pass shift in its timing data:
         * each delay value actually corresponds to the data chunk from
         * the previous iteration. We compensate by using prev_blk
         * instead of the current blk.
         */
        if (prev_blk > 0) {
            if (emit_bytes(fdata, prev_blk) < 0)
                return -1;
        }

        prev_blk = blk;
    }

    /* Emit the final chunk (from the last iteration) without delay */
    if (prev_blk > 0) {
        if (emit_bytes(fdata, prev_blk) < 0)
            return -1;
    }

    return 0;
}

static void print_usage(const char *prog)
{
    fprintf(stderr, "Usage: %s <timing_file> <data_file> [speed_factor]\n",
            prog);
    fprintf(stderr, "\nReplays a session recorded by evrecord.\n");
    fprintf(stderr, "  speed_factor    Replay speed multiplier (default: 1.0)\n");
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    const char *timing_path = argv[1];
    const char *data_path = argv[2];
    double speed = 1.0;

    if (argc >= 4) {
        speed = atof(argv[3]);
        if (speed <= 0.0) {
            fprintf(stderr, "evreplay: speed factor must be positive\n");
            return 1;
        }
    }

    FILE *ftiming = fopen(timing_path, "r");
    if (!ftiming) {
        perror("evreplay: open timing file");
        return 1;
    }

    FILE *fdata = fopen(data_path, "r");
    if (!fdata) {
        perror("evreplay: open data file");
        fclose(ftiming);
        return 1;
    }

    int result = replay_session(ftiming, fdata, speed);

    fclose(ftiming);
    fclose(fdata);

    return result < 0 ? 1 : 0;
}
