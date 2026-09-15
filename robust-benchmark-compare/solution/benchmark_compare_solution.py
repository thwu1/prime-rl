"""
Benchmark Statistical Comparison Engine — Reference Solution

Extends the poop benchmarking tool's statistical approach into a rigorous
multi-metric comparison system with SQLite persistence.

All statistical computations implemented from scratch using only
Python's standard library.
"""


import json
import math
import random
import sqlite3
import sys
import os


# ============================================================
# Mathematical Primitives
# ============================================================

def log_gamma(x):
    if x <= 0:
        raise ValueError("log_gamma requires x > 0")
    g = 7
    coef = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7,
    ]
    if x < 0.5:
        return math.log(math.pi / math.sin(math.pi * x)) - log_gamma(1 - x)
    x -= 1
    a = coef[0]
    t = x + g + 0.5
    for i in range(1, len(coef)):
        a += coef[i] / (x + i)
    return 0.5 * math.log(2 * math.pi) + (x + 0.5) * math.log(t) - t + math.log(a)


def regularized_incomplete_beta(x, a, b):
    if x < 0 or x > 1:
        raise ValueError("x must be in [0, 1]")
    if x == 0:
        return 0.0
    if x == 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1.0 - regularized_incomplete_beta(1 - x, b, a)
    lbeta = log_gamma(a) + log_gamma(b) - log_gamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1 - x) - lbeta) / a
    TINY = 1e-30
    MAX_ITER = 200
    EPS = 1e-14
    f = 1.0
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < TINY:
        d = TINY
    d = 1.0 / d
    f = d
    for m in range(1, MAX_ITER + 1):
        numerator = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1.0 + numerator * d
        if abs(d) < TINY:
            d = TINY
        c = 1.0 + numerator / c
        if abs(c) < TINY:
            c = TINY
        d = 1.0 / d
        f *= c * d
        numerator = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        if abs(d) < TINY:
            d = TINY
        c = 1.0 + numerator / c
        if abs(c) < TINY:
            c = TINY
        d = 1.0 / d
        delta = c * d
        f *= delta
        if abs(delta - 1.0) < EPS:
            break
    return front * f


def t_cdf(t_val, df):
    if df <= 0:
        raise ValueError("df must be positive")
    if t_val == 0:
        return 0.5
    x = df / (df + t_val * t_val)
    ib = regularized_incomplete_beta(x, df / 2.0, 0.5)
    if t_val > 0:
        return 1.0 - 0.5 * ib
    else:
        return 0.5 * ib


def normal_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def inverse_normal_cdf(p):
    if p <= 0 or p >= 1:
        raise ValueError("p must be in (0, 1)")
    a = [
        -3.969683028665376e+01, 2.209460984245205e+02,
        -2.759285104469687e+02, 1.383577518672690e+02,
        -3.066479806614716e+01, 2.506628277459239e+00,
    ]
    b = [
        -5.447609879822406e+01, 1.615858368580409e+02,
        -1.556989798598866e+02, 6.680131188771972e+01,
        -1.328068155288572e+01,
    ]
    c = [
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
        4.374664141464968e+00, 2.938163982698783e+00,
    ]
    d = [
        7.784695709041462e-03, 3.224671290700398e-01,
        2.445134137142996e+00, 3.754408661907416e+00,
    ]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


# ============================================================
# Statistical Tests
# ============================================================

def welch_ttest(sample1, sample2):
    n1, n2 = len(sample1), len(sample2)
    mean1 = sum(sample1) / n1
    mean2 = sum(sample2) / n2
    var1 = sum((x - mean1) ** 2 for x in sample1) / (n1 - 1) if n1 > 1 else 0.0
    var2 = sum((x - mean2) ** 2 for x in sample2) / (n2 - 1) if n2 > 1 else 0.0
    if var1 == 0 and var2 == 0:
        if mean1 == mean2:
            return (0.0, 1.0, 1.0)
        else:
            sign = 1.0 if mean1 > mean2 else -1.0
            return (sign * float('inf'), 0.0, 1.0)
    se = math.sqrt(var1 / n1 + var2 / n2)
    t_stat = (mean1 - mean2) / se
    num = (var1 / n1 + var2 / n2) ** 2
    denom = 0.0
    if var1 > 0:
        denom += (var1 / n1) ** 2 / (n1 - 1)
    if var2 > 0:
        denom += (var2 / n2) ** 2 / (n2 - 1)
    df = num / denom if denom > 0 else 1.0
    p_value = 2.0 * (1.0 - t_cdf(abs(t_stat), df))
    p_value = max(0.0, min(1.0, p_value))
    return (t_stat, p_value, df)


def tukey_fences(data):
    n = len(data)
    if n < 4:
        return ([], list(data))
    sorted_vals = sorted(data)
    q1, _, q3 = compute_quartiles(sorted_vals)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    outlier_indices = []
    clean_data = []
    for idx, val in enumerate(data):
        if val < lower_fence or val > upper_fence:
            outlier_indices.append(idx)
        else:
            clean_data.append(val)
    return (outlier_indices, clean_data)


def bca_bootstrap_ci(sample1, sample2, alpha=0.05, n_bootstrap=10000, seed=42):
    rng = random.Random(seed)
    n1, n2 = len(sample1), len(sample2)
    obs_diff = sum(sample1) / n1 - sum(sample2) / n2
    boot_diffs = []
    for _ in range(n_bootstrap):
        bs1 = [sample1[rng.randint(0, n1 - 1)] for _ in range(n1)]
        bs2 = [sample2[rng.randint(0, n2 - 1)] for _ in range(n2)]
        boot_diffs.append(sum(bs1) / n1 - sum(bs2) / n2)
    boot_diffs.sort()
    count_below = sum(1 for d in boot_diffs if d < obs_diff)
    prop_below = count_below / n_bootstrap
    if prop_below <= 0:
        prop_below = 1 / (2 * n_bootstrap)
    elif prop_below >= 1:
        prop_below = 1 - 1 / (2 * n_bootstrap)
    z0 = inverse_normal_cdf(prop_below)
    mean1 = sum(sample1) / n1
    mean2 = sum(sample2) / n2
    jack_vals = []
    for i in range(n1):
        s1_without = sample1[:i] + sample1[i + 1:]
        jm1 = sum(s1_without) / (n1 - 1) if n1 > 1 else 0.0
        jack_vals.append(jm1 - mean2)
    for j in range(n2):
        s2_without = sample2[:j] + sample2[j + 1:]
        jm2 = sum(s2_without) / (n2 - 1) if n2 > 1 else 0.0
        jack_vals.append(mean1 - jm2)
    jack_mean = sum(jack_vals) / len(jack_vals)
    num_a = sum((jack_mean - jv) ** 3 for jv in jack_vals)
    denom_a = sum((jack_mean - jv) ** 2 for jv in jack_vals)
    if denom_a == 0:
        acc = 0.0
    else:
        acc = num_a / (6.0 * denom_a ** 1.5)
    z_alpha_low = inverse_normal_cdf(alpha / 2)
    z_alpha_high = inverse_normal_cdf(1 - alpha / 2)

    def adjusted_percentile(z_alpha):
        numer = z0 + z_alpha
        denom = 1 - acc * numer
        if abs(denom) < 1e-10:
            return normal_cdf(z_alpha)
        return normal_cdf(z0 + numer / denom)

    alpha1 = adjusted_percentile(z_alpha_low)
    alpha2 = adjusted_percentile(z_alpha_high)
    alpha1 = max(0.5 / n_bootstrap, min(1 - 0.5 / n_bootstrap, alpha1))
    alpha2 = max(0.5 / n_bootstrap, min(1 - 0.5 / n_bootstrap, alpha2))
    idx_low = max(0, min(n_bootstrap - 1, int(alpha1 * n_bootstrap)))
    idx_high = max(0, min(n_bootstrap - 1, int(alpha2 * n_bootstrap)))
    if idx_low >= idx_high:
        idx_high = min(n_bootstrap - 1, idx_low + 1)
    return (boot_diffs[idx_low], boot_diffs[idx_high])


def cliffs_delta(sample1, sample2):
    n1, n2 = len(sample1), len(sample2)
    more = 0
    less = 0
    for x in sample1:
        for y in sample2:
            if x > y:
                more += 1
            elif x < y:
                less += 1
    return (more - less) / (n1 * n2)


def holm_bonferroni(p_values):
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * m
    prev_adj = 0.0
    for rank, (orig_idx, p) in enumerate(indexed):
        adj = min(1.0, p * (m - rank))
        adj = max(adj, prev_adj)
        adjusted[orig_idx] = adj
        prev_adj = adj
    return adjusted


# ============================================================
# Classification and Verdict
# ============================================================

def classify_effect_size(delta):
    ad = abs(delta)
    if ad < 0.147:
        return "negligible"
    elif ad < 0.33:
        return "small"
    elif ad < 0.474:
        return "medium"
    else:
        return "large"


def metric_verdict(pct_change, p_adjusted, alpha=0.05):
    if p_adjusted >= alpha:
        return "no_change"
    if pct_change > 0:
        return "regression"
    return "improvement"


# ============================================================
# Descriptive Statistics
# ============================================================

def compute_quartiles(data):
    n = len(data)
    sorted_data = sorted(data)

    def median_of(arr):
        m = len(arr)
        if m == 0:
            return 0.0
        if m % 2 == 1:
            return arr[m // 2]
        else:
            return (arr[m // 2 - 1] + arr[m // 2]) / 2.0

    med = median_of(sorted_data)
    lower = sorted_data[:n // 2]
    upper = sorted_data[(n + 1) // 2:]
    q1 = median_of(lower) if lower else med
    q3 = median_of(upper) if upper else med
    return (q1, med, q3)


def compute_descriptive_stats(data):
    n = len(data)
    mean = sum(data) / n
    q1, median, q3 = compute_quartiles(data)
    if n > 1:
        std_dev = math.sqrt(sum((x - mean) ** 2 for x in data) / (n - 1))
    else:
        std_dev = 0.0
    return {
        "mean": mean,
        "median": median,
        "std_dev": std_dev,
        "q1": q1,
        "q3": q3,
        "n": n,
    }


# ============================================================
# Data I/O
# ============================================================

def load_benchmark(filepath):
    with open(filepath) as f:
        return json.load(f)


def extract_metric(samples, metric_name):
    return [s[metric_name] for s in samples]


METRICS = ["wall_time_ns", "cpu_cycles", "cache_misses", "peak_rss_bytes"]


# ============================================================
# SQLite Integration
# ============================================================

DB_PATH = "/app/benchmark.db"


def init_database(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    schema_path = "/app/db_schema.sql"
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            conn.executescript(f.read())
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                command TEXT,
                filepath TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                sample_index INTEGER NOT NULL,
                wall_time_ns REAL NOT NULL,
                cpu_cycles REAL NOT NULL,
                cache_misses REAL NOT NULL,
                peak_rss_bytes REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metric_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                metric_name TEXT NOT NULL,
                mean REAL NOT NULL,
                median REAL NOT NULL,
                std_dev REAL NOT NULL,
                q1 REAL NOT NULL,
                q3 REAL NOT NULL,
                n INTEGER NOT NULL,
                outlier_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comparisons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                baseline_run_id INTEGER NOT NULL REFERENCES runs(id),
                candidate_run_id INTEGER NOT NULL REFERENCES runs(id),
                metric_name TEXT NOT NULL,
                mean_diff REAL NOT NULL,
                pct_change REAL NOT NULL,
                p_value_raw REAL NOT NULL,
                p_value_adjusted REAL NOT NULL,
                effect_size REAL NOT NULL,
                effect_size_class TEXT NOT NULL,
                ci_lower REAL NOT NULL,
                ci_upper REAL NOT NULL,
                verdict TEXT NOT NULL
            );
        """)
    return conn


def insert_run(conn, benchmark_data, filepath):
    cursor = conn.execute(
        "INSERT INTO runs (label, command, filepath) VALUES (?, ?, ?)",
        (benchmark_data["label"], benchmark_data.get("command", ""), filepath)
    )
    run_id = cursor.lastrowid
    for i, sample in enumerate(benchmark_data["samples"]):
        conn.execute(
            "INSERT INTO samples (run_id, sample_index, wall_time_ns, cpu_cycles, cache_misses, peak_rss_bytes) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, i, sample["wall_time_ns"], sample["cpu_cycles"],
             sample["cache_misses"], sample["peak_rss_bytes"])
        )
    conn.commit()
    return run_id


def insert_metric_stats(conn, run_id, metric_name, stats):
    conn.execute(
        "INSERT INTO metric_stats (run_id, metric_name, mean, median, std_dev, q1, q3, n, outlier_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, metric_name, stats["mean"], stats["median"], stats["std_dev"],
         stats["q1"], stats["q3"], stats["n"], len(stats.get("outlier_indices", [])))
    )
    conn.commit()


def insert_comparison(conn, baseline_id, candidate_id, metric_name, comp):
    conn.execute(
        "INSERT INTO comparisons (baseline_run_id, candidate_run_id, metric_name, mean_diff, pct_change, p_value_raw, p_value_adjusted, effect_size, effect_size_class, ci_lower, ci_upper, verdict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (baseline_id, candidate_id, metric_name, comp["mean_diff"], comp["pct_change"],
         comp["p_value_raw"], comp["p_value_adjusted"], comp["effect_size"],
         comp["effect_size_class"], comp["ci_lower"], comp["ci_upper"], comp["verdict"])
    )
    conn.commit()


# ============================================================
# Main Comparison
# ============================================================

def compare_benchmarks(baseline_path, candidate_path, output_path):
    baseline = load_benchmark(baseline_path)
    candidate = load_benchmark(candidate_path)

    # Initialize SQLite
    conn = init_database(DB_PATH)
    baseline_id = insert_run(conn, baseline, baseline_path)
    candidate_id = insert_run(conn, candidate, candidate_path)

    report = {
        "baseline_label": baseline["label"],
        "candidate_label": candidate["label"],
        "alpha": 0.05,
        "metrics": {},
        "overall_verdict": "no_change",
    }

    raw_p_values = []
    metric_names = []
    metric_results = {}

    for metric in METRICS:
        base_vals = extract_metric(baseline["samples"], metric)
        cand_vals = extract_metric(candidate["samples"], metric)

        base_stats = compute_descriptive_stats(base_vals)
        cand_stats = compute_descriptive_stats(cand_vals)

        base_outliers, base_clean = tukey_fences(base_vals)
        cand_outliers, cand_clean = tukey_fences(cand_vals)

        base_stats["outlier_indices"] = base_outliers
        cand_stats["outlier_indices"] = cand_outliers

        # Insert metric stats into SQLite
        insert_metric_stats(conn, baseline_id, metric, base_stats)
        insert_metric_stats(conn, candidate_id, metric, cand_stats)

        # Statistical tests on clean data
        t_stat, p_val, df = welch_ttest(base_clean, cand_clean)
        cd = cliffs_delta(base_clean, cand_clean)

        if base_stats["mean"] != 0:
            pct_change = (cand_stats["mean"] - base_stats["mean"]) / base_stats["mean"] * 100
        else:
            pct_change = 0.0 if cand_stats["mean"] == 0 else float('inf')

        ci_low, ci_high = bca_bootstrap_ci(base_clean, cand_clean, alpha=0.05, seed=42)

        raw_p_values.append(p_val)
        metric_names.append(metric)

        metric_results[metric] = {
            "baseline": base_stats,
            "candidate": cand_stats,
            "comparison": {
                "mean_diff": cand_stats["mean"] - base_stats["mean"],
                "pct_change": pct_change,
                "test_statistic": t_stat,
                "degrees_of_freedom": df,
                "p_value_raw": p_val,
                "effect_size": cd,
                "effect_size_class": classify_effect_size(cd),
                "ci_lower": ci_low,
                "ci_upper": ci_high,
            }
        }

    # Multiple comparison correction
    adjusted = holm_bonferroni(raw_p_values)

    has_regression = False
    has_improvement = False

    for i, metric in enumerate(metric_names):
        metric_results[metric]["comparison"]["p_value_adjusted"] = adjusted[i]
        v = metric_verdict(
            metric_results[metric]["comparison"]["pct_change"],
            adjusted[i]
        )
        metric_results[metric]["comparison"]["verdict"] = v

        # Insert comparison into SQLite
        insert_comparison(conn, baseline_id, candidate_id, metric,
                          metric_results[metric]["comparison"])

        if v == "regression":
            has_regression = True
        elif v == "improvement":
            has_improvement = True

    report["metrics"] = metric_results

    if has_regression:
        report["overall_verdict"] = "regression"
    elif has_improvement:
        report["overall_verdict"] = "improvement"
    else:
        report["overall_verdict"] = "no_change"

    conn.close()

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python3 benchmark_compare.py <baseline.json> <candidate.json> <output.json>")
        sys.exit(1)
    compare_benchmarks(sys.argv[1], sys.argv[2], sys.argv[3])
