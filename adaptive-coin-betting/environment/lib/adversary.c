
#include "adversary.h"
#include <math.h>
#include <stdlib.h>

static unsigned int _lcg_state;

static void _lcg_seed(unsigned int s) {
    _lcg_state = s;
}

static double _lcg_next_uniform(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return ((double)(_lcg_state & 0x7fffffffu)) / (double)0x7fffffffu * 2.0 - 1.0;
}

int generate_adversary(int seed, int T, int dim, double *out_grads) {
    int t, d, phase_len;
    double *direction;

    if (!out_grads || T <= 0 || dim <= 0) return -1;
    _lcg_seed((unsigned int)seed);

    phase_len = (int)ceil(sqrt((double)T));
    if (phase_len < 1) phase_len = 1;

    direction = (double *)malloc((size_t)dim * sizeof(double));
    if (!direction) return -1;

    for (t = 0; t < T; t++) {
        if (t % phase_len == 0) {
            for (d = 0; d < dim; d++) {
                direction[d] = (_lcg_next_uniform() > 0.0) ? 1.0 : -1.0;
            }
        }
        for (d = 0; d < dim; d++) {
            double noise = _lcg_next_uniform() * 0.1;
            double val = direction[d] + noise;
            if (val > 1.0) val = 1.0;
            if (val < -1.0) val = -1.0;
            out_grads[t * dim + d] = val;
        }
    }
    free(direction);
    return 0;
}

double olo_regret_bound(double competitor, int T, double lipschitz) {
    double abs_u = fabs(competitor);
    return abs_u * sqrt((double)T * log(abs_u * sqrt((double)T) + M_E)) * lipschitz;
}

double adaptive_regret_bound(int interval_len, int T) {
    double log_T = log((double)T + 1.0);
    return 50.0 * sqrt((double)interval_len) * log_T * log_T;
}

double wealth_lower_bound(int T) {
    return 0.01 / sqrt((double)T);
}
