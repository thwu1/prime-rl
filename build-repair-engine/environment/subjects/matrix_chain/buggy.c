#include <stdlib.h>

#define MAXN 64
#define INF 999999999

int can_multiply(int cols_a, int rows_b) {
    return cols_a == rows_b;
}

int mult_cost(int r1, int c1, int c2) {
    return r1 * c1 * c2;
}

int matrix_chain_order(const int *dims, int n) {
    if (n <= 1) return 0;

    int dp[MAXN][MAXN];

    for (int i = 1; i <= n; i++)
        dp[i][i] = 0;

    for (int len = 2; len <= n; len++) {
        for (int i = 1; i <= n - len + 1; i++) {
            int j = i + len - 1;
            dp[i][j] = INF;
            for (int k = i; k < j; k++) {
                int cost = dp[i][k] + dp[k + 1][j]
                         + dims[i] * dims[k] * dims[j];
                if (cost < dp[i][j])
                    dp[i][j] = cost;
            }
        }
    }

    return dp[1][n];
}

int total_elements(const int *dims, int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += dims[i] * dims[i + 1];
    }
    return total;
}
