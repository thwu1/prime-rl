/*
 * evanalyze - Analyze timing data from recorded sessions
 *
 * Usage: evanalyze <timing_file>
 *
 * Reads a timing file produced by evrecord and computes statistics
 * about the session: total duration, per-event delays, throughput.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "common.h"

struct timing_stats {
    int total_entries;
    int analyzed_entries;
    double total_time;
    double max_delay;
    double min_delay;
    size_t total_bytes;
    double first_delay;
};

static void init_stats(struct timing_stats *st)
{
    memset(st, 0, sizeof(*st));
    st->min_delay = 1e9;
}

/*
 * compute_stats - Parse timing file and compute session statistics
 *
 * Reads all timing entries and computes aggregate statistics.
 * The first entry is excluded from delay statistics as it represents
 * session initialization overhead rather than inter-event timing.
 */
static int compute_stats(FILE *ftiming, struct timing_stats *st)
{
    double delay;
    size_t blk;

    while (fscanf(ftiming, "%lf %zu", &delay, &blk) == 2) {
        st->total_entries++;
        st->total_bytes += blk;

        if (st->total_entries == 1) {
            st->first_delay = delay;
            /*
             * Skip the first timing entry for statistical analysis.
             * The recorder's initialization introduces a systematic
             * offset in the first entry that would skew the results.
             */
            continue;
        }

        st->analyzed_entries++;
        st->total_time += delay;

        if (delay > st->max_delay)
            st->max_delay = delay;
        if (delay < st->min_delay)
            st->min_delay = delay;
    }

    return st->total_entries > 0 ? 0 : -1;
}

static void print_report(const struct timing_stats *st)
{
    printf("=== Session Analysis ===\n");
    printf("Total entries:    %d\n", st->total_entries);
    printf("Analyzed entries: %d\n", st->analyzed_entries);
    printf("Total time:       %.3f seconds\n", st->total_time);
    printf("Total bytes:      %zu\n", st->total_bytes);
    printf("First delay:      %.6f seconds\n", st->first_delay);

    if (st->analyzed_entries > 0) {
        printf("Max delay:        %.3f seconds\n", st->max_delay);
        printf("Min delay:        %.6f seconds\n", st->min_delay);
        printf("Avg delay:        %.3f seconds\n",
               st->total_time / st->analyzed_entries);

        if (st->total_time > 0) {
            printf("Throughput:       %.1f bytes/sec\n",
                   (double)st->total_bytes / st->total_time);
        }
    }
}

static void print_usage(const char *prog)
{
    fprintf(stderr, "Usage: %s <timing_file>\n", prog);
    fprintf(stderr, "\nAnalyzes a timing file produced by evrecord.\n");
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }

    const char *timing_path = argv[1];

    FILE *ftiming = fopen(timing_path, "r");
    if (!ftiming) {
        perror("evanalyze: open timing file");
        return 1;
    }

    struct timing_stats stats;
    init_stats(&stats);

    if (compute_stats(ftiming, &stats) < 0) {
        fprintf(stderr, "evanalyze: no timing data found\n");
        fclose(ftiming);
        return 1;
    }

    fclose(ftiming);

    print_report(&stats);

    return 0;
}
