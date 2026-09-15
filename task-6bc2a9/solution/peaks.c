double evaluate_peaks(const double *x, int dim,
                      const double *positions, const double *heights,
                      const double *widths, int num_peaks) {
    double max_val = -1e308;
    int k, d;
    for (k = 0; k < num_peaks; k++) {
        double dist_sq = 0.0;
        const double *pk = positions + k * dim;
        for (d = 0; d < dim; d++) {
            double diff = x[d] - pk[d];
            dist_sq += diff * diff;
        }
        double w = widths[k];
        double val = heights[k] / (1.0 + dist_sq / (w * w));
        if (val > max_val) {
            max_val = val;
        }
    }
    return max_val;
}
