# Q-Error statistics (corrected)
# Input: pipe-separated lines (subplan|qerror)
# Output: single-line JSON with aggregate statistics
#

BEGIN {
    FS = "|"
    n = 0
}
{
    if (NF < 2) next
    vals[n++] = $2 + 0
}
END {
    if (n == 0) {
        print "{\"count\": 0, \"mean\": 0, \"median\": 0, \"p90\": 0, \"p95\": 0, \"p99\": 0}"
        exit
    }

    for (i = 0; i < n; i++)
        for (j = i + 1; j < n; j++)
            if (vals[i] > vals[j]) { t = vals[i]; vals[i] = vals[j]; vals[j] = t }

    sum = 0
    for (i = 0; i < n; i++) sum += vals[i]
    mean = sum / n

    printf "{\"count\": %d, \"mean\": %.6f, \"median\": %.6f, \"p90\": %.6f, \"p95\": %.6f, \"p99\": %.6f}\n", n, mean, pctile(50), pctile(90), pctile(95), pctile(99)
}

function pctile(p,    k, f, c) {
    k = (n - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if (c >= n) c = n - 1
    if (f == c) return vals[f]
    return vals[f] * (c - k) + vals[c] * (k - f)
}
