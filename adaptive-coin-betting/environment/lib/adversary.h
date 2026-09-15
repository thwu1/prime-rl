#ifndef ADVERSARY_H
#define ADVERSARY_H


/*
 * Generate a deterministic adversarial gradient sequence.
 * Writes T*dim doubles into out_grads in row-major order:
 *   out_grads[t * dim + d] is the gradient for round t, dimension d.
 * Uses a phase-switching adversary that changes direction periodically.
 * Returns 0 on success, -1 on invalid arguments.
 */
int generate_adversary(int seed, int T, int dim, double *out_grads);

/*
 * Compute theoretical OLO regret upper bound for a parameter-free algorithm.
 * Returns: |competitor| * sqrt(T * log(|competitor| * sqrt(T) + e)) * lipschitz
 */
double olo_regret_bound(double competitor, int T, double lipschitz);

/*
 * Compute strongly adaptive regret bound for an interval of given length.
 * Returns: C * sqrt(interval_len) * log(T+1)^2
 */
double adaptive_regret_bound(int interval_len, int T);

/*
 * Compute wealth lower bound for balanced sequences of length T.
 * Returns: C / sqrt(T)
 */
double wealth_lower_bound(int T);

#endif /* ADVERSARY_H */
