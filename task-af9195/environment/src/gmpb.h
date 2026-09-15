/*
 * gmpb.h — Generalized Moving Peaks Benchmark (C library API)
 *
 * Opaque context-based interface for dynamic fitness landscape evaluation.
 * Build with: make -C /app
 */

#ifndef GMPB_H
#define GMPB_H

#include <stdint.h>

/* Opaque benchmark context. */
typedef struct GMPBContext GMPBContext;

/* Create a new benchmark context.
 *   num_peaks        — number of peaks in the landscape
 *   dimension        — number of decision variables
 *   change_frequency — evaluations between environment changes
 *   shift_severity   — magnitude of peak position shift per change
 *   num_environments — total number of environments (including initial)
 *   seed             — PRNG seed for reproducibility
 * Returns NULL on failure.  Must be freed with gmpb_destroy(). */
GMPBContext *gmpb_create(int num_peaks, int dimension, int change_frequency,
                         double shift_severity, int num_environments,
                         uint64_t seed);

/* Free all resources associated with a benchmark context. */
void gmpb_destroy(GMPBContext *ctx);

/* Evaluate the landscape at point x.
 * x must point to `dimension` doubles.
 * Returns fitness value (higher is better). */
double gmpb_evaluate(GMPBContext *ctx, const double *x);

/* Get current global optimum.
 * If pos is non-NULL, writes the optimum position (dimension doubles).
 * Returns the optimum fitness value. */
double gmpb_get_optimum(GMPBContext *ctx, double *pos);

/* Trigger one environment change: shift all peaks. */
void gmpb_trigger_change(GMPBContext *ctx);

/* Query context parameters. */
int gmpb_total_evaluations(GMPBContext *ctx);
int gmpb_change_frequency(GMPBContext *ctx);
int gmpb_dimension(GMPBContext *ctx);
int gmpb_num_environments(GMPBContext *ctx);
int gmpb_num_peaks(GMPBContext *ctx);

#endif /* GMPB_H */
