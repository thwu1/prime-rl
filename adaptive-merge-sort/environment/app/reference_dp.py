"""
Reference O(n^2) DP for optimal merge cost using Knuth's optimization.

Correct and exact, but too slow for large n. Use for ground-truth comparison
on small/medium inputs.

"""


def optimal_merge_cost(run_lengths):
    """Compute exact minimum merge cost using O(n^2) DP with Knuth's optimization.

    Returns the minimum total merge cost. Each merge of two adjacent segments
    with combined length L costs L.
    """
    n = len(run_lengths)
    if n <= 1:
        return 0

    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + run_lengths[i]

    INF = float("inf")
    dp = [[INF] * n for _ in range(n)]
    opt = [[0] * n for _ in range(n)]

    for i in range(n):
        dp[i][i] = 0
        opt[i][i] = i

    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            total = prefix[j + 1] - prefix[i]

            lo_k = opt[i][j - 1]
            hi_k = opt[i + 1][j] if i + 1 <= j else j - 1
            hi_k = min(hi_k, j - 1)

            for k in range(lo_k, hi_k + 1):
                cost = dp[i][k] + dp[k + 1][j] + total
                if cost < dp[i][j]:
                    dp[i][j] = cost
                    opt[i][j] = k

    return dp[0][n - 1]


def optimal_merge_cost_with_tree(run_lengths):
    """Like optimal_merge_cost but also returns the optimal merge tree."""
    n = len(run_lengths)
    if n == 0:
        return 0, None
    if n == 1:
        return 0, 0

    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + run_lengths[i]

    INF = float("inf")
    dp = [[INF] * n for _ in range(n)]
    opt = [[0] * n for _ in range(n)]

    for i in range(n):
        dp[i][i] = 0
        opt[i][i] = i

    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            total = prefix[j + 1] - prefix[i]

            lo_k = opt[i][j - 1]
            hi_k = opt[i + 1][j] if i + 1 <= j else j - 1
            hi_k = min(hi_k, j - 1)

            for k in range(lo_k, hi_k + 1):
                cost = dp[i][k] + dp[k + 1][j] + total
                if cost < dp[i][j]:
                    dp[i][j] = cost
                    opt[i][j] = k

    def build_tree(i, j):
        if i == j:
            return i
        k = opt[i][j]
        return (build_tree(i, k), build_tree(k + 1, j))

    return dp[0][n - 1], build_tree(0, n - 1)
