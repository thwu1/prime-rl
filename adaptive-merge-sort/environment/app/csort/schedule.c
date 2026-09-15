/*
 * Merge schedule computation for adjacent runs.
 *
 */

#include "schedule.h"
#include <stdlib.h>
#include <limits.h>

long long compute_merge_schedule(const int *run_lengths, int n, int *out_splits) {
    if (n <= 1) return 0;

    /* Prefix sums for range sum queries */
    long long *prefix = (long long *)calloc(n + 1, sizeof(long long));
    for (int i = 0; i < n; i++) {
        prefix[i + 1] = prefix[i] + run_lengths[i];
    }

    /* DP table: dp[i*n+j] = min cost to merge runs i..j */
    long long *dp = (long long *)calloc((size_t)n * n, sizeof(long long));

    /* Initialize split points */
    for (int i = 0; i < n; i++) {
        out_splits[i * n + i] = i;
    }

    /* Fill DP by increasing chain length */
    for (int len = 2; len <= n; len++) {
        for (int i = 0; i <= n - len; i++) {
            int j = i + len - 1;
            long long total = prefix[j] - prefix[i];

            long long best = LLONG_MAX;
            int best_k = i;

            for (int k = i; k < j; k++) {
                long long cost = dp[i * n + k] + dp[(k + 1) * n + j] + total;
                if (cost < best) {
                    best = cost;
                    best_k = k;
                }
            }

            dp[i * n + j] = best;
            out_splits[i * n + j] = best_k;
        }
    }

    long long result = dp[0 * n + (n - 1)];
    free(prefix);
    free(dp);

    return result;
}
