/*
 * Antenna Performance Metrics
 * Computes derived antenna parameters from parsed NEC2 simulation data.
 */


#include "antenna_metrics.h"

double compute_vswr(double z_real, double z_imag) {
    double dr = z_real + Z0_REF;
    double di = z_imag;
    double nr = z_real - Z0_REF;
    double ni = z_imag;

    double num_sq = nr * nr + ni * ni;
    double den_sq = dr * dr + di * di;

    if (den_sq < 1e-30) return 999.0;

    double gamma_sq = num_sq / den_sq;
    if (gamma_sq >= 1.0) return 999.0;
    double vswr = (1.0 + gamma_sq) / (1.0 - gamma_sq);
    return vswr;
}

void find_max_gain(const PatternEntry *pat, int n,
                   double *max_db, double *max_theta) {
    *max_db = -9999.0;
    *max_theta = 0.0;

    for (int i = 0; i < n; i++) {
        double g = pat[i].gain_hor_db;
        if (g > *max_db) {
            *max_db = g;
            *max_theta = pat[i].theta;
        }
    }
}

double compute_hpbw(const PatternEntry *pat, int n) {
    (void)pat; (void)n;
    /* Not yet implemented */
    return -1.0;
}

ValidationResult validate_deck_vs_output(const DeckData *deck, const SimRun *run) {
    ValidationResult v;
    memset(&v, 0, sizeof(v));
    (void)deck; (void)run;
    /* Not yet implemented */
    return v;
}
