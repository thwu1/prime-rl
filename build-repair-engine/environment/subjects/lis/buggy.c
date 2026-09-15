#include <stdlib.h>

int array_max(const int *arr, int n) {
    if (n == 0) return 0;
    int m = arr[0];
    for (int i = 1; i < n; i++) {
        if (arr[i] > m) m = arr[i];
    }
    return m;
}

int array_min(const int *arr, int n) {
    if (n == 0) return 0;
    int m = arr[0];
    for (int i = 1; i < n; i++) {
        if (arr[i] < m) m = arr[i];
    }
    return m;
}

int is_sorted(const int *arr, int n) {
    for (int i = 1; i < n; i++) {
        if (arr[i] < arr[i - 1]) return 0;
    }
    return 1;
}

int lis_length(const int *arr, int n) {
    if (n == 0) return 0;
    int *dp = (int *)malloc(n * sizeof(int));
    for (int i = 0; i < n; i++) dp[i] = 1;

    for (int i = 1; i < n; i++) {
        for (int j = 0; j < i; j++) {
            if (arr[j] >= arr[i] && dp[j] + 1 > dp[i]) {
                dp[i] = dp[j] + 1;
            }
        }
    }

    int max_len = 0;
    for (int i = 0; i < n; i++) {
        if (dp[i] > max_len) max_len = dp[i];
    }
    free(dp);
    return max_len;
}
