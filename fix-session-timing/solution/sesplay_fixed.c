/*
 * sesplay - Terminal session replayer (FIXED + ENHANCED)
 *
 * Replays sessions recorded by sesrec, using the timing data file
 * to reproduce the original pacing of output. Supports both v1 (delta)
 * and v2 (absolute monotonic) timing formats with auto-detection.
 *
 * Usage: sesplay [-T timingfile] [-s speed] [-m maxwait] [--analyze] [typescript]
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <time.h>
#include <errno.h>

#define SESPLAY_VERSION "1.0.0"
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
        "  -T FILE      Read timing data from FILE (default: %s)\n"
        "  -s SPEED     Playback speed multiplier (default: 1.0)\n"
        "  -m MAXWAIT   Maximum delay in seconds (default: no limit)\n"
        "  --analyze    Print JSON statistics without replaying\n"
        "  -V           Show version\n"
        "  -h           Show this help\n",
        prog, DEFAULT_TIMING);
    exit(1);
}

/* Detect timing format: returns 2 if v2 header found, 1 otherwise.
 * For v2, file position is left after the header line (ready for data).
 * For v1, file position is rewound to the start. */
static int detect_format(FILE *ftiming)
{
    char line[256];
    long pos = ftell(ftiming);

    if (fgets(line, sizeof(line), ftiming)) {
        if (strncmp(line, "# sesrec-timing v2", 18) == 0)
            return 2;
    }
    fseek(ftiming, pos, SEEK_SET);
    return 1;
}

static void do_analyze(FILE *ftiming, int format)
{
    double total_duration = 0;
    size_t total_bytes = 0;
    unsigned long total_chunks = 0;
    double max_delay_val = 0, min_delay_val = -1;

    if (format == 2) {
        double first_time = -1, prev_time = -1, abs_time;
        size_t blk;

        while (fscanf(ftiming, "%lf %zu", &abs_time, &blk) == 2) {
            total_chunks++;
            total_bytes += blk;
            if (first_time < 0)
                first_time = abs_time;
            if (prev_time >= 0) {
                double d = abs_time - prev_time;
                if (d > max_delay_val)
                    max_delay_val = d;
                if (min_delay_val < 0 || d < min_delay_val)
                    min_delay_val = d;
            }
            prev_time = abs_time;
        }
        if (total_chunks > 0 && prev_time >= 0 && first_time >= 0)
            total_duration = prev_time - first_time;
    } else {
        double d;
        size_t blk;

        while (fscanf(ftiming, "%lf %zu", &d, &blk) == 2) {
            total_chunks++;
            total_bytes += blk;
            total_duration += d;
            if (d > max_delay_val)
                max_delay_val = d;
            if (min_delay_val < 0 || d < min_delay_val)
                min_delay_val = d;
        }
    }

    double mean_delay;
    if (format == 2)
        mean_delay = (total_chunks > 1) ? total_duration / (total_chunks - 1) : 0.0;
    else
        mean_delay = (total_chunks > 0) ? total_duration / total_chunks : 0.0;

    if (min_delay_val < 0)
        min_delay_val = 0.0;

    printf("{\"format_version\": %d, \"total_chunks\": %lu, \"total_bytes\": %zu, "
           "\"total_duration_sec\": %.6f, \"mean_delay_sec\": %.6f, "
           "\"max_delay_sec\": %.6f, \"min_delay_sec\": %.6f}\n",
           format, total_chunks, total_bytes, total_duration,
           mean_delay, max_delay_val, min_delay_val);
}

static int replay_v1(FILE *ftiming, FILE *fscript, const char *ts_path,
                     double speed, double max_delay)
{
    double delay;
    size_t blk;
    unsigned long line = 0;

    while (fscanf(ftiming, "%lf %zu", &delay, &blk) == 2) {
        line++;

        double adj_delay = delay / speed;
        if (max_delay >= 0 && adj_delay > max_delay)
            adj_delay = max_delay;
        if (adj_delay > MIN_DELAY)
            delay_for(adj_delay);

        if (emit_bytes(fscript, ts_path, blk) < 0) {
            fprintf(stderr, "sesplay: replay error at timing line %lu\n", line);
            return 1;
        }
    }
    return 0;
}

static int replay_v2(FILE *ftiming, FILE *fscript, const char *ts_path,
                     double speed, double max_delay)
{
    double abs_time, prev_time = -1;
    size_t blk;
    unsigned long line = 0;

    while (fscanf(ftiming, "%lf %zu", &abs_time, &blk) == 2) {
        line++;

        if (prev_time >= 0) {
            double delay = (abs_time - prev_time) / speed;
            if (max_delay >= 0 && delay > max_delay)
                delay = max_delay;
            if (delay > MIN_DELAY)
                delay_for(delay);
        }

        if (emit_bytes(fscript, ts_path, blk) < 0) {
            fprintf(stderr, "sesplay: replay error at timing line %lu\n", line);
            return 1;
        }
        prev_time = abs_time;
    }
    return 0;
}

int main(int argc, char *argv[])
{
    const char *ts_path = DEFAULT_TYPESCRIPT;
    const char *tm_path = DEFAULT_TIMING;
    double speed = 1.0;
    double max_delay = -1.0;  /* negative = no limit */
    int analyze = 0;
    int opt;

    static struct option long_opts[] = {
        {"analyze", no_argument, NULL, 'A'},
        {NULL, 0, NULL, 0}
    };

    while ((opt = getopt_long(argc, argv, "T:s:m:Vh", long_opts, NULL)) != -1) {
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
        case 'A':
            analyze = 1;
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

    int format = detect_format(ftiming);

    if (analyze) {
        do_analyze(ftiming, format);
        fclose(ftiming);
        return 0;
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

    int ret;
    if (format == 2)
        ret = replay_v2(ftiming, fscript, ts_path, speed, max_delay);
    else
        ret = replay_v1(ftiming, fscript, ts_path, speed, max_delay);

    fclose(ftiming);
    fclose(fscript);

    return ret;
}
