#ifndef NODE_OPS_H
#define NODE_OPS_H

#include <stdint.h>
#include <stddef.h>

/* Binary search for target in sorted double array.
   Returns index of first element >= target, or n if all < target. */
int score_lower_bound(const double *arr, int n, double target);

/* Count doubles in [lo, hi] range within sorted double array. */
int score_count_in_range(const double *arr, int n, double lo, double hi);

/* Merge two sorted double arrays into dst (must have space for n1+n2). */
void score_merge_sorted(double *dst, const double *src1, int n1,
                        const double *src2, int n2);

/* Deterministic verification checksum. */
uint32_t node_ops_checksum(uint32_t seed);

#endif
