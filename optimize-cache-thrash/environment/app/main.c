#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "pipeline.h"

static double matrix[ROWS][COLS];
static double smooth_result[ROWS][COLS];

static void generate_data(unsigned int seed) {
    srand(seed);
    for (int r = 0; r < ROWS; r++)
        for (int c = 0; c < COLS; c++)
            matrix[r][c] = (double)(rand() % 10000) / 10000.0;
}

static void write_results(const char *filename, SensorStats stats[],
                          double distances[][PAIR_COLS]) {
    FILE *f = fopen(filename, "w");
    if (!f) { perror("fopen"); exit(1); }

    for (int c = 0; c < COLS; c++) {
        fprintf(f, "STAT %d %.10f %.10f %.10f %.10f\n", c,
                stats[c].min_val, stats[c].max_val,
                stats[c].mean, stats[c].stddev);
    }

    for (int i = 0; i < PAIR_COLS; i++)
        for (int j = i + 1; j < PAIR_COLS; j++)
            fprintf(f, "DIST %d %d %.10f\n", i, j, distances[i][j]);

    double checksum = 0.0;
    for (int r = 0; r < ROWS; r++)
        for (int c = 0; c < COLS; c++)
            checksum += matrix[r][c] * (r + 1) * (c + 1);
    fprintf(f, "CHECKSUM %.10f\n", checksum);

    double smooth_cksum = 0.0;
    for (int r = 0; r < ROWS; r++)
        for (int c = 0; c < COLS; c++)
            smooth_cksum += smooth_result[r][c] * (r + 1);
    fprintf(f, "SMOOTH_CHECKSUM %.10f\n", smooth_cksum);

    fclose(f);
}

int main(int argc, char *argv[]) {
    unsigned int seed = 42;
    const char *outfile = "/app/output.txt";

    if (argc > 1) seed = (unsigned int)atoi(argv[1]);
    if (argc > 2) outfile = argv[2];

    generate_data(seed);

    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);

    SensorStats stats[COLS];
    analyze_sensors(matrix, stats);
    normalize_data(matrix, stats);
    smooth_data(matrix, smooth_result);

    double distances[PAIR_COLS][PAIR_COLS];
    compute_distances(matrix, distances);

    clock_gettime(CLOCK_MONOTONIC, &end);

    double elapsed = (end.tv_sec - start.tv_sec) +
                     (end.tv_nsec - start.tv_nsec) / 1e9;
    fprintf(stderr, "TIME=%.6f\n", elapsed);

    write_results(outfile, stats, distances);
    return 0;
}
