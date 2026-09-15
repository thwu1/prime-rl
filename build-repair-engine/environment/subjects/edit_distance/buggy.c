#include <string.h>
#include <stdlib.h>

static int min3(int a, int b, int c) {
    int m = a < b ? a : b;
    return m < c ? m : c;
}

int char_diff_count(const char *s1, const char *s2) {
    int m = strlen(s1);
    int n = strlen(s2);
    int len = m < n ? m : n;
    int diff = 0;
    for (int i = 0; i < len; i++) {
        if (s1[i] != s2[i]) diff++;
    }
    diff += (m > n ? m - n : n - m);
    return diff;
}

int common_prefix_len(const char *s1, const char *s2) {
    int i = 0;
    while (s1[i] && s2[i] && s1[i] == s2[i]) i++;
    return i;
}

int edit_distance(const char *s1, const char *s2) {
    int m = strlen(s1);
    int n = strlen(s2);

    int *dp = (int *)malloc((m + 1) * (n + 1) * sizeof(int));
    #define DP(i, j) dp[(i) * (n + 1) + (j)]

    for (int i = 0; i <= m; i++) DP(i, 0) = i;
    for (int j = 0; j <= n; j++) DP(0, j) = j;

    for (int i = 1; i <= m; i++) {
        for (int j = 1; j <= n; j++) {
            if (s1[i - 1] == s2[j - 1]) {
                DP(i, j) = DP(i - 1, j - 1);
            } else {
                int cost = 0;
                DP(i, j) = min3(
                    DP(i - 1, j) + 1,
                    DP(i, j - 1) + 1,
                    DP(i - 1, j - 1) + cost
                );
            }
        }
    }

    int result = DP(m, n);
    #undef DP
    free(dp);
    return result;
}
