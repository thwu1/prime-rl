/*
 * ert_bw_profile.c - ERT bandwidth profile extractor
 *
 * Reads an ERT raw data file and outputs a gnuplot-compatible TSV
 * with the maximum observed bandwidth at each working-set size.
 *
 * Build:  (requires libm)
 * Usage:  ./ert_bw_profile <input.dat> <output.tsv>
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MAX_WS 512

typedef struct {
    long   ws_bytes;
    double max_bw_gbps;
    double max_gflops;
    int    count;
} WSBucket;

static int cmp_bucket(const void *a, const void *b)
{
    long da = ((const WSBucket *)a)->ws_bytes;
    long db = ((const WSBucket *)b)->ws_bytes;
    return (da > db) - (da < db);
}

static int find_bucket(WSBucket *b, int n, long ws)
{
    for (int i = 0; i < n; i++)
        if (b[i].ws_bytes == ws)
            return i;
    return -1;
}

int main(int argc, char *argv[])
{
    if (argc != 3) {
        fprintf(stderr,
                "Usage: %s <ert_input.dat> <output.tsv>\n"
                "  Extracts max bandwidth per working-set size.\n",
                argv[0]);
        return 1;
    }

    FILE *fin = fopen(argv[1], "r");
    if (!fin) {
        perror(argv[1]);
        return 1;
    }

    WSBucket buckets[MAX_WS];
    int nbk = 0;
    double global_peak_gflops = 0.0;

    long elements, trials, total_bytes, total_flops;
    double time_us;

    while (fscanf(fin, "%ld %ld %lf %ld %ld",
                  &elements, &trials, &time_us,
                  &total_bytes, &total_flops) == 5) {
        if (time_us <= 0.0)
            continue;

        double time_s  = time_us * 1e-6;
        double bw_gbps = (double)total_bytes / time_s / 1e9;
        double gflops  = (double)total_flops / time_s / 1e9;
        long   ws      = elements * 8;   /* sizeof(double) */

        if (gflops > global_peak_gflops)
            global_peak_gflops = gflops;

        int idx = find_bucket(buckets, nbk, ws);
        if (idx < 0) {
            if (nbk >= MAX_WS) {
                fprintf(stderr, "warning: too many unique working sets\n");
                continue;
            }
            idx = nbk++;
            buckets[idx].ws_bytes   = ws;
            buckets[idx].max_bw_gbps = 0.0;
            buckets[idx].max_gflops  = 0.0;
            buckets[idx].count       = 0;
        }
        if (bw_gbps > buckets[idx].max_bw_gbps)
            buckets[idx].max_bw_gbps = bw_gbps;
        if (gflops > buckets[idx].max_gflops)
            buckets[idx].max_gflops = gflops;
        buckets[idx].count++;
    }
    fclose(fin);

    qsort(buckets, nbk, sizeof(WSBucket), cmp_bucket);

    FILE *fout = fopen(argv[2], "w");
    if (!fout) {
        perror(argv[2]);
        return 1;
    }

    fprintf(fout, "# ERT Bandwidth Profile\n");
    fprintf(fout, "# peak_gflops=%.4f\n", global_peak_gflops);
    fprintf(fout, "# Columns: ws_bytes  log2_ws  bandwidth_gbps  gflops\n");

    for (int i = 0; i < nbk; i++) {
        double log2_ws = log2((double)buckets[i].ws_bytes);
        fprintf(fout, "%ld\t%.4f\t%.4f\t%.4f\n",
                buckets[i].ws_bytes,
                log2_ws,
                buckets[i].max_bw_gbps,
                buckets[i].max_gflops);
    }

    fclose(fout);
    fprintf(stderr, "Extracted %d working-set sizes (peak %.2f GFLOP/s)\n",
            nbk, global_peak_gflops);
    return 0;
}
