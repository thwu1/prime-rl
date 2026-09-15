#include <math.h>
#include <string.h>
#include <float.h>
#include "pipeline.h"

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

    for (int c = 0; c < COLS; c++) {
        for (int r = 0; r < ROWS; r++) {
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

void normalize_data(double data[][COLS], const SensorStats stats[]) {
    for (int c = 0; c < COLS; c++) {
        double mean = stats[c].mean;
        double sd = stats[c].stddev;
        if (sd < 1e-15) sd = 1.0;
        for (int r = 0; r < ROWS; r++) {
            data[r][c] = (data[r][c] - mean) / sd;
        }
    }
}

void compute_distances(double data[][COLS], double result[][PAIR_COLS]) {
    memset(result, 0, PAIR_COLS * PAIR_COLS * sizeof(double));

    for (int i = 0; i < PAIR_COLS; i++) {
        for (int j = i + 1; j < PAIR_COLS; j++) {
            double dist = 0.0;
            for (int r = 0; r < ROWS; r++) {
                double diff = data[r][i] - data[r][j];
                dist += diff * diff;
            }
            result[i][j] = sqrt(dist);
            result[j][i] = result[i][j];
        }
    }
}

void smooth_data(double data[][COLS], double result[][COLS]) {
    for (int r = 0; r < ROWS; r++) {
        for (int c = 0; c < COLS; c++) {
            double sum = 0.0;
            int count = 0;
            for (int w = 0; w < WINDOW_SIZE; w++) {
                int cc = c + w;
                if (cc < COLS) {
                    sum += data[r][cc];
                    count++;
                }
            }
            result[r][c] = sum / count;
        }
    }
}
