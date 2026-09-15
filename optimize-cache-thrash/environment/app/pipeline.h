#ifndef PIPELINE_H
#define PIPELINE_H

#define ROWS 16384
#define COLS 512
#define PAIR_COLS 48
#define WINDOW_SIZE 7

typedef struct {
    double min_val;
    double max_val;
    double sum;
    double sum_sq;
    double mean;
    double stddev;
    int count;
    int sensor_id;
    char label[16];
} SensorStats;

void analyze_sensors(double data[][COLS], SensorStats stats[]);
void normalize_data(double data[][COLS], const SensorStats stats[]);
void compute_distances(double data[][COLS], double result[][PAIR_COLS]);
void smooth_data(double data[][COLS], double result[][COLS]);

#endif /* PIPELINE_H */
