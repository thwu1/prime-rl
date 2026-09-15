/*
 * Generalized Moving Peaks Benchmark (GMPB) - C shared library interface.
 *
 * Generates dynamic fitness landscapes composed of cone-shaped peaks.
 * The fitness function is:
 *     f(x) = max_{i=1..m} { h_i - w_i * ||x - c_i|| }
 *
 * Peaks shift, grow, and reshape after every change_frequency evaluations.
 *
 */
#ifndef GMPB_H
#define GMPB_H

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handle for a GMPB benchmark instance. */
typedef struct gmpb_t gmpb_t;

/*
 * Create a new GMPB benchmark instance.
 *
 * Parameters:
 *   num_peaks        - Number of peaks in the landscape (>= 1)
 *   dimension        - Search space dimensionality (>= 1)
 *   change_frequency - Number of evaluations between environment changes
 *   shift_severity   - Magnitude of peak position shifts per change (>= 0)
 *   num_environments - Total number of environments to traverse (>= 1)
 *   seed             - Random seed for reproducibility
 *
 * Returns: Pointer to new instance (caller must free with gmpb_free),
 *          or NULL on allocation failure.
 */
gmpb_t* gmpb_new(int num_peaks, int dimension, int change_frequency,
                  double shift_severity, int num_environments,
                  unsigned int seed);

/* Free a GMPB instance and all associated memory. Safe to call with NULL. */
void gmpb_free(gmpb_t* g);

/*
 * Evaluate the fitness of candidate solution x.
 *
 * x must point to an array of `dimension` doubles, each in
 * [min_coord, max_coord]. The function computes:
 *     f(x) = max_i { h_i - w_i * ||x - c_i|| }
 *
 * Side effects: updates internal tracking (best-found, current error,
 * eval count) and triggers an environment change when the eval count
 * reaches a multiple of change_frequency.
 *
 * Returns: Fitness value (double), or NAN if the evaluation budget is
 *          exhausted or inputs are invalid.
 */
double gmpb_evaluate(gmpb_t* g, const double* x);

/* Returns 1 if the evaluation budget is exhausted, 0 otherwise. */
int gmpb_is_finished(const gmpb_t* g);

/* Current environment index (0-based). */
int gmpb_get_environment(const gmpb_t* g);

/* Offline error: mean of all current-error values recorded so far. */
double gmpb_get_offline_error(const gmpb_t* g);

/* Total evaluations performed so far. */
int gmpb_get_eval_count(const gmpb_t* g);

/* Remaining evaluation budget. */
int gmpb_get_remaining_evals(const gmpb_t* g);

/* Search space dimensionality. */
int gmpb_get_dimension(const gmpb_t* g);

/* Number of peaks in the landscape. */
int gmpb_get_num_peaks(const gmpb_t* g);

/* Evaluations between environment changes. */
int gmpb_get_change_frequency(const gmpb_t* g);

/* Lower bound of coordinate range (default -25.0). */
double gmpb_get_min_coord(const gmpb_t* g);

/* Upper bound of coordinate range (default 25.0). */
double gmpb_get_max_coord(const gmpb_t* g);

/* Current global optimum fitness value (max peak height). */
double gmpb_get_optimum(const gmpb_t* g);

/*
 * Copy the position of the current global optimum peak into pos_out.
 * pos_out must have space for at least `dimension` doubles.
 * Returns 0 on success, -1 on error.
 */
int gmpb_get_optimum_position(const gmpb_t* g, double* pos_out);

#ifdef __cplusplus
}
#endif

#endif /* GMPB_H */
