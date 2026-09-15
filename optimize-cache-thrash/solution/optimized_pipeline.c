#include <math.h>
#include <string.h>
#include <float.h>
#include "pipeline.h"

/*
 * CACHE FIX: row-major traversal (stride-8 instead of stride-4096).
 * Original iterated columns in the outer loop, causing every row
 * access to map to the same L1 set (4096 / 64 = 64 = number of
 * L1 sets), producing near-100% conflict misses.
 */
void analyze_sensors(double data[][COLS], SensorStats stats[]) {
    for (int c = 0; c < COLS; c++) {
        stats[c].min_val = DBL_MAX;
        stats[c].max_val = -DBL_MAX;
        stats[c].sum = 0.0;
        stats[c].sum_sq = 0.0;
        stats[c].count = 0;
        stats[c].sensor_id = c;
        memset(stats[c].label, 0, 16);
    }

    for (int r = 0; r < ROWS; r++) {
        for (int c = 0; c < COLS; c++) {
            double val = data[r][c];
            stats[c].sum += val;
            stats[c].sum_sq += val * val;
            stats[c].count++;
            if (val < stats[c].min_val) stats[c].min_val = val;
            if (val > stats[c].max_val) stats[c].max_val = val;
        }
    }

    for (int c = 0; c < COLS; c++) {
        stats[c].mean = stats[c].sum / stats[c].count;
        double var = stats[c].sum_sq / stats[c].count
                     - stats[c].mean * stats[c].mean;
        stats[c].stddev = sqrt(var > 0 ? var : 0);
    }
}

/*
 * CACHE FIX: row-major traversal with preloaded per-column stats
 * in contiguous double arrays (4KB each, fit in L1).
 */
void normalize_data(double data[][COLS], const SensorStats stats[]) {
    double means[COLS], sds[COLS];
    for (int c = 0; c < COLS; c++) {
        means[c] = stats[c].mean;
        sds[c] = stats[c].stddev;
        if (sds[c] < 1e-15) sds[c] = 1.0;
    }

    for (int r = 0; r < ROWS; r++) {
        for (int c = 0; c < COLS; c++) {
            data[r][c] = (data[r][c] - means[c]) / sds[c];
        }
    }
}

/*
 * CACHE FIX: row-outer / pair-inner loop nest. Each row's first
 * PAIR_COLS elements (384 bytes = 6 cache lines) are loaded once
 * and reused across all 1128 pairs. The accumulator array
 * (48x48 doubles = 18KB) fits entirely in L1.
 */
void compute_distances(double data[][COLS], double result[][PAIR_COLS]) {
    double accum[PAIR_COLS][PAIR_COLS];
    memset(accum, 0, sizeof(accum));

    for (int r = 0; r < ROWS; r++) {
        for (int i = 0; i < PAIR_COLS; i++) {
            double vi = data[r][i];
            for (int j = i + 1; j < PAIR_COLS; j++) {
                double diff = vi - data[r][j];
                accum[i][j] += diff * diff;
            }
        }
    }

    for (int i = 0; i < PAIR_COLS; i++) {
        for (int j = i + 1; j < PAIR_COLS; j++) {
            result[i][j] = sqrt(accum[i][j]);
            result[j][i] = result[i][j];
        }
    }
}

/*
 * ALGORITHMIC FIX (not cache — this kernel is already row-major).
 * Original recomputes the window sum from scratch for each position:
 * O(ROWS * COLS * WINDOW_SIZE). Sliding window reduces to
 * O(ROWS * COLS) — one add and one subtract per position.
 */
void smooth_data(double data[][COLS], double result[][COLS]) {
    for (int r = 0; r < ROWS; r++) {
        double sum = 0.0;
        int init_count = (WINDOW_SIZE < COLS) ? WINDOW_SIZE : COLS;
        for (int w = 0; w < init_count; w++) {
            sum += data[r][w];
        }
        result[r][0] = sum / init_count;

        for (int c = 1; c < COLS; c++) {
            int right = c + WINDOW_SIZE - 1;
            if (right < COLS) {
                sum += data[r][right];
            }
            sum -= data[r][c - 1];
            int count = (c + WINDOW_SIZE <= COLS) ? WINDOW_SIZE : (COLS - c);
            result[r][c] = sum / count;
        }
    }
}
