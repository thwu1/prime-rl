/*
 * qec_engine.c - Surface code QEC computation library
 *
 * Provides error rate computations for fault-tolerant quantum resource
 * estimation using the rotated planar surface code.
 *
 * Supports two distillation protocols:
 *   - 15-to-1 standard magic state distillation
 *   - 20-to-4 Golay-code-based distillation
 */

#include "qec_engine.h"
#include <math.h>
#include <stdlib.h>

/* Empirically fitted prefactor for surface code logical error rate */
#define A_CONSTANT 0.1

double logical_error_rate(double p, double p_th, int d) {
    /*
     * Logical error probability per surface code cycle per logical qubit.
     * p_L(d) = A * (p / p_th)^(floor(d/2) + 1)
     */
    double ratio = p / p_th;
    int exponent = (d - 1) / 2;
    return A_CONSTANT * pow(ratio, exponent);
}

double distillation_error_15to1(double p, int k) {
    /*
     * Output error rate of the 15-to-1 magic state distillation protocol
     * at cascade level k.
     *
     * p_T(1) = 35 * p^3
     * p_T(k) = 35 * p_T(k-1)^3   for k >= 2
     */
    double p_T = 35.0 * p * p;
    for (int i = 2; i <= k; i++) {
        p_T = 35.0 * p_T * p_T * p_T;
    }
    return p_T;
}

double distillation_error_20to4(double p, int k) {
    /*
     * Output error rate of the 20-to-4 Golay-code distillation protocol
     * at cascade level k.
     *
     * p_T(1) = 56 * p^4
     * p_T(k) = 56 * p_T(k-1)^4   for k >= 2
     */
    double p_T = 56.0 * pow(p, 4);
    for (int i = 2; i <= k; i++) {
        p_T = 56.0 * pow(p_T, 4);
    }
    return p_T;
}

int find_code_distance(double p, double p_th, int n, int D, double eps_mem) {
    /*
     * Find minimum odd code distance d >= 3 satisfying
     *   p_L(d) * n * D <= eps_mem
     */
    for (int d = 3; d <= 201; d += 2) {
        double p_L = logical_error_rate(p, p_th, d);
        if (p_L * n * D <= eps_mem) {
            return d;
        }
    }
    return -1;
}

int find_distillation_level_15to1(double p, long long T_total, double eps_dist) {
    for (int k = 1; k <= 20; k++) {
        double p_T = distillation_error_15to1(p, k);
        if (p_T * (double)T_total <= eps_dist) {
            return k;
        }
    }
    return -1;
}

int find_distillation_level_20to4(double p, long long T_total, double eps_dist) {
    for (int k = 1; k <= 20; k++) {
        double p_T = distillation_error_20to4(p, k);
        if (p_T * (double)T_total <= eps_dist) {
            return k;
        }
    }
    return -1;
}
