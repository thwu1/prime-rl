#ifndef QEC_ENGINE_H
#define QEC_ENGINE_H

/*
 * Surface code logical error rate per cycle per logical qubit at distance d.
 * p: physical gate error rate
 * p_th: error correction threshold
 * d: code distance (odd integer >= 3)
 */
double logical_error_rate(double p, double p_th, int d);

/*
 * 15-to-1 distillation protocol output error at level k.
 */
double distillation_error_15to1(double p, int k);

/*
 * 20-to-4 Golay-code distillation protocol output error at level k.
 */
double distillation_error_20to4(double p, int k);

/*
 * Find minimum odd code distance d >= 3 satisfying the memory error constraint.
 * Returns -1 if no suitable distance found within d <= 201.
 */
int find_code_distance(double p, double p_th, int n, int D, double eps_mem);

/*
 * Find minimum distillation level k >= 1 for 15-to-1 protocol.
 * Returns -1 if no level up to 20 is sufficient.
 */
int find_distillation_level_15to1(double p, long long T_total, double eps_dist);

/*
 * Find minimum distillation level k >= 1 for 20-to-4 protocol.
 * Returns -1 if no level up to 20 is sufficient.
 */
int find_distillation_level_20to4(double p, long long T_total, double eps_dist);

#endif
