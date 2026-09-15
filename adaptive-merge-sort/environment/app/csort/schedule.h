#ifndef SCHEDULE_H
#define SCHEDULE_H

/*
 * Compute minimum-cost merge schedule for adjacent runs.
 *
 * Only adjacent runs may be merged. The cost of merging two runs
 * with combined length L is L.
 *
 * run_lengths: array of n positive integers (length of each run)
 * n:           number of runs
 * out_splits:  pre-allocated n*n int array; on return,
 *              out_splits[i*n+j] = optimal split point k for runs i..j
 *              (merge runs i..k with runs k+1..j)
 *
 * Returns: minimum total merge cost
 */
long long compute_merge_schedule(const int *run_lengths, int n, int *out_splits);

#endif
