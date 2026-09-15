/*
 * sesplay - Terminal session replayer
 *
 * Replays sessions recorded by sesrec, using the timing data file
 * to reproduce the original pacing of output.
 *
 * Usage: sesplay [-T timingfile] [-s speed] [-m maxwait] [typescript]
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <time.h>
#include <errno.h>

#define SESPLAY_VERSION "0.9.3"
#define DEFAULT_TYPESCRIPT "typescript"
#define DEFAULT_TIMING "timing"
#define MIN_DELAY 0.000100

static void delay_for(double seconds)
{
    if (seconds < MIN_DELAY)
        return;
    struct timespec req;
    req.tv_sec = (time_t)seconds;
    req.tv_nsec = (long)((seconds - req.tv_sec) * 1e9);
    while (nanosleep(&req, &req) == -1 && errno == EINTR)
        ;
}

static int emit_bytes(FILE *fp, const char *name, size_t count)
{
    char buf[4096];
    size_t remaining = count;

    while (remaining > 0) {
        size_t chunk = remaining < sizeof(buf) ? remaining : sizeof(buf);
        size_t nread = fread(buf, 1, chunk, fp);
        if (nread == 0) {
            fprintf(stderr, "sesplay: unexpected end of %s\n", name);
            return -1;
        }
        fwrite(buf, 1, nread, stdout);
        remaining -= nread;
    }
    fflush(stdout);
    return 0;
}

static void usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s [options] [typescript]\n"
        "Options:\n"
        "  -T FILE    Read timing data from FILE (default: %s)\n"
        "  -s SPEED   Playback speed multiplier (default: 1.0)\n"
        "  -m MAXWAIT Maximum delay in seconds (default: no limit)\n"
        "  -V         Show version\n"
        "  -h         Show this help\n",
        prog, DEFAULT_TIMING);
    exit(1);
}

int main(int argc, char *argv[])
{
    const char *ts_path = DEFAULT_TYPESCRIPT;
    const char *tm_path = DEFAULT_TIMING;
    double speed = 1.0;
    double max_delay = -1.0;  /* negative = no limit */
    int opt;

    while ((opt = getopt(argc, argv, "T:s:m:Vh")) != -1) {
        switch (opt) {
        case 'T':
            tm_path = optarg;
            break;
        case 's':
            speed = atof(optarg);
            if (speed <= 0) {
                fprintf(stderr, "sesplay: speed must be positive\n");
                return 1;
            }
            break;
        case 'm':
            max_delay = atof(optarg);
            break;
        case 'V':
            printf("sesplay %s\n", SESPLAY_VERSION);
            return 0;
        case 'h':
        default:
            usage(argv[0]);
        }
    }

    if (optind < argc)
        ts_path = argv[optind];

    FILE *ftiming = fopen(tm_path, "r");
    if (!ftiming) {
        perror(tm_path);
        return 1;
    }

    FILE *fscript = fopen(ts_path, "r");
    if (!fscript) {
        perror(ts_path);
        fclose(ftiming);
        return 1;
    }

    /* Skip header lines written by the recorder */
    char hdr[1024];
    long pos = ftell(fscript);
    while (fgets(hdr, sizeof(hdr), fscript)) {
        if (strncmp(hdr, "Script ", 7) == 0 ||
            strncmp(hdr, "Command:", 8) == 0) {
            pos = ftell(fscript);
        } else {
            break;
        }
    }
    fseek(fscript, pos, SEEK_SET);

    setvbuf(stdout, NULL, _IONBF, 0);

    double delay;
    size_t blk;
    unsigned long line = 0;
    size_t oldblk = 0;

    while (fscanf(ftiming, "%lf %zu", &delay, &blk) == 2) {
        line++;

        /* Apply speed factor */
        double adj_delay = delay / speed;

        /* Apply max delay cap if set */
        if (max_delay >= 0 && adj_delay > max_delay)
            adj_delay = max_delay;

        if (adj_delay > MIN_DELAY)
            delay_for(adj_delay);

        if (oldblk) {
            if (emit_bytes(fscript, ts_path, oldblk) < 0) {
                fprintf(stderr, "sesplay: replay error at timing line %lu\n", line);
                break;
            }
        }

        oldblk = blk;
    }

    if (oldblk) {
        if (emit_bytes(fscript, ts_path, oldblk) < 0) {
            fprintf(stderr, "sesplay: error emitting final block\n");
        }
    }

    fclose(ftiming);
    fclose(fscript);

    return 0;
}
