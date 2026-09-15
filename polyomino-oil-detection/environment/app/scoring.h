#ifndef SCORING_H
#define SCORING_H

/*
 * Gaussian log-likelihood scoring for oil field detection beam search.
 *
 * Given observed row/column aggregate averages and a candidate polyomino
 * placement combination's row/column contribution counts, compute how well
 * the candidate explains the observations under the noise model.
 *
 * The noise model:
 *   mu_row[i] = N * eps + combo_rc[i] * (1 - 2*eps)
 *   mu_col[j] = N * eps + combo_cc[j] * (1 - 2*eps)
 *   sigma^2   = max(N * eps * (1-eps) / num_rounds, 1e-12)
 *
 * Score = -sum_i (row_avg[i] - mu_row[i])^2 / (2*sigma^2)
 *         -sum_j (col_avg[j] - mu_col[j])^2 / (2*sigma^2)
 *
 * Higher scores indicate better fit.
 */

/*
 * Score a single candidate combo against observed averages.
 *
 * Parameters:
 *   N          - grid size (NxN)
 *   eps        - noise parameter (epsilon)
 *   num_rounds - number of averaging rounds for sigma calculation
 *   row_avg    - array of N doubles: averaged row aggregate observations
 *   col_avg    - array of N doubles: averaged column aggregate observations
 *   combo_rc   - array of N ints: candidate's row contribution counts
 *   combo_cc   - array of N ints: candidate's column contribution counts
 *
 * Returns: log-likelihood score (double, higher = better fit)
 */
double score_combo(int N, double eps, int num_rounds,
                   const double *row_avg, const double *col_avg,
                   const int *combo_rc, const int *combo_cc);

/*
 * Find the best-scoring combo from a batch.
 *
 * Parameters:
 *   N, eps, num_rounds, row_avg, col_avg - same as score_combo
 *   combo_rcs  - flattened [num_combos x N] array of row counts
 *   combo_ccs  - flattened [num_combos x N] array of column counts
 *   num_combos - number of candidate combos
 *
 * Returns: index (0-based) of the highest-scoring combo
 */
int find_best_combo(int N, double eps, int num_rounds,
                    const double *row_avg, const double *col_avg,
                    const int *combo_rcs, const int *combo_ccs,
                    int num_combos);

#endif /* SCORING_H */
