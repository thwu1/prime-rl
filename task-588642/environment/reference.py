#!/usr/bin/env python3
"""Naive Levenshtein distance implementation for reference.

Use this as a correctness oracle. It is correct but slow for large-scale lookups.
"""



def edit_distance(s1, s2):
    """Compute the Levenshtein edit distance between two strings using DP."""
    m, n = len(s1), len(s2)
    if m == 0:
        return n
    if n == 0:
        return m
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if s1[i - 1] == s2[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(dp[j], dp[j - 1], prev)
            prev = temp
    return dp[n]


def fuzzy_search(query, dictionary, max_distance):
    """Find all words in dictionary within max_distance of query.

    Returns list of (word, distance) sorted by (distance, word).
    """
    results = []
    for word in dictionary:
        d = edit_distance(query, word)
        if d <= max_distance:
            results.append((word, d))
    return sorted(results, key=lambda x: (x[1], x[0]))
