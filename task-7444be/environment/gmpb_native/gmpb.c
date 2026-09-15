/*
 * Generalized Moving Peaks Benchmark (GMPB) — C implementation.
 *
 * Based on: D. Yazdani et al., "Benchmarking continuous dynamic optimization:
 * Survey and generalized test suite," IEEE Trans. Cybernetics, 2020.
 *
 */

#include "gmpb.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ------------------------------------------------------------------ */
/*  xorshift64* PRNG — simple, fast, deterministic                    */
/* ------------------------------------------------------------------ */
typedef struct { uint64_t s; } rng_t;

static void rng_init(rng_t *r, uint64_t seed) {
    r->s = seed ? seed : 1ULL;
    for (int i = 0; i < 20; i++) {          /* warm-up */
        r->s ^= r->s >> 12;
        r->s ^= r->s << 25;
        r->s ^= r->s >> 27;
    }
}

static uint64_t rng_next(rng_t *r) {
    uint64_t x = r->s;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    r->s = x;
    return x * UINT64_C(0x2545F4914F6CDD1D);
}

static double rng_uniform(rng_t *r) {
    return (rng_next(r) >> 11) / 9007199254740992.0;   /* [0, 1) */
}

static double rng_uniform_range(rng_t *r, double lo, double hi) {
    return lo + (hi - lo) * rng_uniform(r);
}

/* Box-Muller transform */
static double rng_normal(rng_t *r) {
    double u1, u2;
    do { u1 = rng_uniform(r); } while (u1 < 1e-300);
    u2 = rng_uniform(r);
    return sqrt(-2.0 * log(u1)) * cos(2.0 * M_PI * u2);
}

/* ------------------------------------------------------------------ */
/*  Helper math                                                       */
/* ------------------------------------------------------------------ */
static double vec_norm(const double *v, int n) {
    double s = 0.0;
    for (int i = 0; i < n; i++) s += v[i] * v[i];
    return sqrt(s);
}

static double dclamp(double x, double lo, double hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

/* ------------------------------------------------------------------ */
/*  GMPB internal structure                                           */
/* ------------------------------------------------------------------ */
struct gmpb_t {
    int    num_peaks;
    int    dimension;
    int    change_frequency;
    double shift_severity;
    int    num_environments;
    double height_severity;   /* 7.0 */
    double width_severity;    /* 1.0 */
    double min_coord;         /* -25.0 */
    double max_coord;         /*  25.0 */

    int    total_evals;
    int    eval_count;
    int    current_env;
    double best_found;

    double *positions;        /* num_peaks * dimension, row-major */
    double *heights;          /* num_peaks */
    double *widths;           /* num_peaks */
    double *prev_shifts;      /* num_peaks * dimension */

    double error_sum;         /* running sum for offline-error mean */
    rng_t  rng;
};

/* ------------------------------------------------------------------ */
/*  Environment change                                                */
/* ------------------------------------------------------------------ */
static void change_environment(gmpb_t *g) {
    g->current_env++;
    g->best_found = -1e300;

    int dim = g->dimension;
    int np  = g->num_peaks;

    double *rand_vec = (double *)malloc(dim * sizeof(double));
    double *combined = (double *)malloc(dim * sizeof(double));
    if (!rand_vec || !combined) { free(rand_vec); free(combined); return; }

    for (int i = 0; i < np; i++) {
        /* Random unit direction */
        for (int d = 0; d < dim; d++)
            rand_vec[d] = rng_normal(&g->rng);
        double rn = vec_norm(rand_vec, dim);
        if (rn > 1e-15)
            for (int d = 0; d < dim; d++) rand_vec[d] /= rn;

        /* Combine with previous shift (correlation) */
        double *prev = g->prev_shifts + i * dim;
        for (int d = 0; d < dim; d++)
            combined[d] = prev[d] + rand_vec[d];

        double cn = vec_norm(combined, dim);
        if (cn > 1e-15) {
            for (int d = 0; d < dim; d++)
                prev[d] = combined[d] / cn * g->shift_severity;
        } else {
            for (int d = 0; d < dim; d++)
                prev[d] = rand_vec[d] * g->shift_severity;
        }

        /* Update position with boundary clamping */
        double *pos = g->positions + i * dim;
        for (int d = 0; d < dim; d++) {
            pos[d] += prev[d];
            pos[d] = dclamp(pos[d], g->min_coord, g->max_coord);
        }

        /* Perturb height within [10, 100] */
        g->heights[i] += g->height_severity * rng_normal(&g->rng);
        g->heights[i] = dclamp(g->heights[i], 10.0, 100.0);

        /* Perturb width within [0.5, 15] */
        g->widths[i] += g->width_severity * rng_normal(&g->rng);
        g->widths[i] = dclamp(g->widths[i], 0.5, 15.0);
    }

    free(rand_vec);
    free(combined);
}

/* ------------------------------------------------------------------ */
/*  Public API                                                        */
/* ------------------------------------------------------------------ */
gmpb_t *gmpb_new(int num_peaks, int dimension, int change_frequency,
                  double shift_severity, int num_environments,
                  unsigned int seed) {
    gmpb_t *g = (gmpb_t *)calloc(1, sizeof(gmpb_t));
    if (!g) return NULL;

    g->num_peaks        = num_peaks;
    g->dimension        = dimension;
    g->change_frequency = change_frequency;
    g->shift_severity   = shift_severity;
    g->num_environments = num_environments;
    g->height_severity  = 7.0;
    g->width_severity   = 1.0;
    g->min_coord        = -25.0;
    g->max_coord        =  25.0;

    g->total_evals = change_frequency * num_environments;
    g->eval_count  = 0;
    g->current_env = 0;
    g->best_found  = -1e300;
    g->error_sum   = 0.0;

    rng_init(&g->rng, (uint64_t)seed);

    int np  = num_peaks;
    int dim = dimension;

    g->positions   = (double *)malloc(np * dim * sizeof(double));
    g->heights     = (double *)malloc(np * sizeof(double));
    g->widths      = (double *)malloc(np * sizeof(double));
    g->prev_shifts = (double *)calloc(np * dim, sizeof(double));

    if (!g->positions || !g->heights || !g->widths || !g->prev_shifts) {
        gmpb_free(g);
        return NULL;
    }

    /* Initialize peak parameters */
    for (int i = 0; i < np; i++) {
        for (int d = 0; d < dim; d++)
            g->positions[i * dim + d] =
                rng_uniform_range(&g->rng, g->min_coord, g->max_coord);
        g->heights[i] = rng_uniform_range(&g->rng, 30.0, 70.0);
        g->widths[i]  = rng_uniform_range(&g->rng, 1.0, 12.0);
    }

    return g;
}

void gmpb_free(gmpb_t *g) {
    if (!g) return;
    free(g->positions);
    free(g->heights);
    free(g->widths);
    free(g->prev_shifts);
    free(g);
}

double gmpb_evaluate(gmpb_t *g, const double *x) {
    if (!g || !x) return NAN;
    if (g->eval_count >= g->total_evals) return NAN;

    int dim = g->dimension;
    int np  = g->num_peaks;

    /* f(x) = max_i { h_i - w_i * ||x - c_i|| } */
    double best_fit = -1e300;
    for (int i = 0; i < np; i++) {
        double dist2 = 0.0;
        const double *ci = g->positions + i * dim;
        for (int d = 0; d < dim; d++) {
            double diff = x[d] - ci[d];
            dist2 += diff * diff;
        }
        double val = g->heights[i] - g->widths[i] * sqrt(dist2);
        if (val > best_fit) best_fit = val;
    }

    /* Update best-found */
    if (best_fit > g->best_found) g->best_found = best_fit;

    /* Current optimum = max peak height */
    double optimum = -1e300;
    for (int i = 0; i < np; i++)
        if (g->heights[i] > optimum) optimum = g->heights[i];

    /* Record current error */
    double error = optimum - g->best_found;
    if (error < 0.0) error = 0.0;
    g->error_sum += error;

    g->eval_count++;

    /* Trigger environment change at boundary */
    if (g->eval_count % g->change_frequency == 0 &&
        g->eval_count < g->total_evals) {
        change_environment(g);
    }

    return best_fit;
}

int gmpb_is_finished(const gmpb_t *g) {
    return g ? (g->eval_count >= g->total_evals) : 1;
}

int gmpb_get_environment(const gmpb_t *g) {
    return g ? g->current_env : -1;
}

double gmpb_get_offline_error(const gmpb_t *g) {
    if (!g || g->eval_count == 0) return INFINITY;
    return g->error_sum / g->eval_count;
}

int gmpb_get_eval_count(const gmpb_t *g) {
    return g ? g->eval_count : 0;
}

int gmpb_get_remaining_evals(const gmpb_t *g) {
    return g ? (g->total_evals - g->eval_count) : 0;
}

int gmpb_get_dimension(const gmpb_t *g) {
    return g ? g->dimension : 0;
}

int gmpb_get_num_peaks(const gmpb_t *g) {
    return g ? g->num_peaks : 0;
}

int gmpb_get_change_frequency(const gmpb_t *g) {
    return g ? g->change_frequency : 0;
}

double gmpb_get_min_coord(const gmpb_t *g) {
    return g ? g->min_coord : 0.0;
}

double gmpb_get_max_coord(const gmpb_t *g) {
    return g ? g->max_coord : 0.0;
}

double gmpb_get_optimum(const gmpb_t *g) {
    if (!g) return NAN;
    double opt = -1e300;
    for (int i = 0; i < g->num_peaks; i++)
        if (g->heights[i] > opt) opt = g->heights[i];
    return opt;
}

int gmpb_get_optimum_position(const gmpb_t *g, double *pos_out) {
    if (!g || !pos_out) return -1;
    int best_idx = 0;
    for (int i = 1; i < g->num_peaks; i++)
        if (g->heights[i] > g->heights[best_idx]) best_idx = i;
    memcpy(pos_out, g->positions + best_idx * g->dimension,
           g->dimension * sizeof(double));
    return 0;
}
