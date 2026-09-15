#!/usr/bin/env python3

"""
ProUCL 5.2-compatible environmental UCL analysis engine.
Processes CSV datasets with detected and non-detect (left-censored) observations,
applies hierarchical goodness-of-fit testing, computes UCLs, and writes structured
JSON output following the methodology specification.
"""

import csv
import json
import math
import os
import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# Configuration: ProUCL 5.2 significance levels
# ---------------------------------------------------------------------------
GOF_ALPHA_NORMAL = 0.01
GOF_ALPHA_GAMMA = 0.05
GOF_ALPHA_LOGNORMAL = 0.10
UCL_ALPHA = 0.05  # for 95% UCL


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dataset(path):
    """Load CSV dataset, return arrays of values, censored flags, and DLs."""
    values = []
    censored_flags = []
    detection_limits = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            values.append(float(row["value"]))
            censored_flags.append(int(row["censored"]))
            dl_str = row["detection_limit"].strip()
            detection_limits.append(float(dl_str) if dl_str else None)
    return (
        np.array(values, dtype=float),
        np.array(censored_flags, dtype=int),
        detection_limits,
    )


# ---------------------------------------------------------------------------
# Basic statistics
# ---------------------------------------------------------------------------

def compute_skewness(data):
    """Adjusted Fisher-Pearson skewness coefficient."""
    n = len(data)
    if n < 3:
        return 0.0
    return float(stats.skew(data, bias=False))


# ---------------------------------------------------------------------------
# Kaplan-Meier for left-censored data
# ---------------------------------------------------------------------------

def km_left_censored(values, censored_flags, detection_limits):
    """
    Kaplan-Meier product-limit estimator for left-censored data.

    Algorithm:
    1. Sort observations descending (detects before censored at ties)
    2. Process from largest to smallest, updating survival probability
    3. Compute KM mean and variance from probability masses
    """
    n = len(values)
    obs = []
    for i in range(n):
        if censored_flags[i]:
            obs.append((float(detection_limits[i]), False))
        else:
            obs.append((float(values[i]), True))

    # Sort descending; for ties, detected before censored
    obs.sort(key=lambda x: (-x[0], not x[1]))

    n_risk = n
    S = 1.0
    km_mean = 0.0
    km_mean_sq = 0.0

    i = 0
    while i < len(obs):
        v = obs[i][0]
        d = 0  # detected count at this value
        c = 0  # censored count at this value
        while i < len(obs) and obs[i][0] == v:
            if obs[i][1]:
                d += 1
            else:
                c += 1
            i += 1

        if n_risk > 0:
            S_new = S * (1 - d / n_risk)
        else:
            S_new = S
        mass = S - S_new
        if d > 0:
            km_mean += v * mass
            km_mean_sq += v ** 2 * mass
        n_risk -= d + c
        S = S_new

    km_var = km_mean_sq - km_mean ** 2
    km_sd = math.sqrt(max(km_var, 0))
    km_se = km_sd / math.sqrt(n)

    return {
        "km_mean": km_mean,
        "km_sd": km_sd,
        "km_se": km_se,
        "S_final": S,
    }


# ---------------------------------------------------------------------------
# Goodness-of-fit tests
# ---------------------------------------------------------------------------

def gof_tests(data):
    """
    Hierarchical GOF tests following ProUCL 5.2 methodology.
    Returns dict with test results for normal, gamma, and lognormal.
    """
    results = {}
    arr = np.array(data, dtype=float)
    n = len(arr)

    # Normal: Shapiro-Wilk at alpha = 0.01
    if n >= 3:
        stat_val, p = stats.shapiro(arr)
        results["normal"] = {
            "statistic": float(stat_val),
            "p_value": float(p),
            "pass": bool(p > GOF_ALPHA_NORMAL),
        }
    else:
        results["normal"] = {"statistic": None, "p_value": None, "pass": False}

    # Gamma: K-S test with MLE params (loc=0) at alpha = 0.05
    if np.all(arr > 0) and n >= 3:
        try:
            a, loc, scale = stats.gamma.fit(arr, floc=0)
            stat_val, p = stats.kstest(arr, "gamma", args=(a, 0, scale))
            results["gamma"] = {
                "statistic": float(stat_val),
                "p_value": float(p),
                "pass": bool(p > GOF_ALPHA_GAMMA),
            }
        except Exception:
            results["gamma"] = {"statistic": None, "p_value": None, "pass": False}
    else:
        results["gamma"] = {"statistic": None, "p_value": None, "pass": False}

    # Lognormal: Shapiro-Wilk on log-transformed at alpha = 0.10
    if np.all(arr > 0) and n >= 3:
        log_arr = np.log(arr)
        stat_val, p = stats.shapiro(log_arr)
        results["lognormal"] = {
            "statistic": float(stat_val),
            "p_value": float(p),
            "pass": bool(p > GOF_ALPHA_LOGNORMAL),
        }
    else:
        results["lognormal"] = {"statistic": None, "p_value": None, "pass": False}

    return results


def classify_distribution(gof):
    """Hierarchical classification: normal -> gamma -> lognormal -> nonparametric."""
    if gof["normal"]["pass"]:
        return "Normal"
    elif gof["gamma"]["pass"]:
        return "Gamma"
    elif gof["lognormal"]["pass"]:
        return "Lognormal"
    else:
        return "Nonparametric"


# ---------------------------------------------------------------------------
# UCL computations
# ---------------------------------------------------------------------------

def compute_ucls_uncensored(data, distribution):
    """Compute UCLs for uncensored data."""
    n = len(data)
    mean = float(np.mean(data))
    sd = float(np.std(data, ddof=1))
    se = sd / math.sqrt(n)
    skew = compute_skewness(data)

    ucls = {}

    # Student's t UCL
    t_crit = float(stats.t.ppf(1 - UCL_ALPHA, n - 1))
    ucls["t_ucl"] = mean + t_crit * se

    # Adjusted-CLT Gamma UCL
    z_crit = float(stats.norm.ppf(1 - UCL_ALPHA))
    gamma_adj = 1 + skew / (3 * math.sqrt(n))
    ucls["gamma_adj_ucl"] = mean + z_crit * se * gamma_adj

    # Chebyshev UCL (computed but never recommended in ProUCL 5.2)
    ucls["chebyshev_ucl"] = mean + math.sqrt((1 / UCL_ALPHA - 1) / n) * sd

    # Decision logic
    if distribution == "Normal":
        rec_method = "Student's-t UCL"
        rec_ucl = ucls["t_ucl"]
    elif distribution == "Gamma":
        rec_method = "Adjusted-CLT Gamma UCL"
        rec_ucl = ucls["gamma_adj_ucl"]
    elif distribution == "Lognormal":
        if n >= 20:
            rec_method = "Adjusted-CLT Gamma UCL"
            rec_ucl = ucls["gamma_adj_ucl"]
        else:
            rec_method = "Student's-t UCL"
            rec_ucl = ucls["t_ucl"]
    else:  # Nonparametric
        rec_method = "Student's-t UCL"
        rec_ucl = ucls["t_ucl"]

    return ucls, rec_method, rec_ucl


def compute_ucls_censored(km_stats, n_total):
    """Compute KM-based UCLs for censored data."""
    km_mean = km_stats["km_mean"]
    km_sd = km_stats["km_sd"]
    km_se = km_stats["km_se"]

    ucls = {}

    # KM (t) UCL
    t_crit = float(stats.t.ppf(1 - UCL_ALPHA, n_total - 1))
    ucls["km_t_ucl"] = km_mean + t_crit * km_se

    # KM Chebyshev UCL
    ucls["km_chebyshev_ucl"] = km_mean + math.sqrt((1 / UCL_ALPHA - 1) / n_total) * km_sd

    rec_method = "KM (t) UCL"
    rec_ucl = ucls["km_t_ucl"]

    return ucls, rec_method, rec_ucl


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_dataset(name, path):
    """Run full ProUCL 5.2 analysis on a single dataset."""
    values, censored_flags, detection_limits = load_dataset(path)
    n_total = len(values)
    n_detect = int(np.sum(censored_flags == 0))
    n_nondetect = n_total - n_detect
    percent_nd = round(100.0 * n_nondetect / n_total, 1)

    result = {
        "n_total": n_total,
        "n_detect": n_detect,
        "n_nondetect": n_nondetect,
        "percent_nd": percent_nd,
    }

    if n_nondetect == 0:
        # --- Uncensored analysis ---
        data = values
        mean = float(np.mean(data))
        sd = float(np.std(data, ddof=1))
        se = sd / math.sqrt(n_total)
        skew = compute_skewness(data)

        gof = gof_tests(data)
        distribution = classify_distribution(gof)
        ucls, rec_method, rec_ucl = compute_ucls_uncensored(data, distribution)

        result.update(
            {
                "mean": round(mean, 4),
                "sd": round(sd, 4),
                "se": round(se, 4),
                "skewness": round(skew, 4),
                "gof": {
                    "normal_pvalue": round(gof["normal"]["p_value"], 6)
                    if gof["normal"]["p_value"] is not None
                    else None,
                    "normal_pass": gof["normal"]["pass"],
                    "gamma_pvalue": round(gof["gamma"]["p_value"], 6)
                    if gof["gamma"]["p_value"] is not None
                    else None,
                    "gamma_pass": gof["gamma"]["pass"],
                    "lognormal_pvalue": round(gof["lognormal"]["p_value"], 6)
                    if gof["lognormal"]["p_value"] is not None
                    else None,
                    "lognormal_pass": gof["lognormal"]["pass"],
                },
                "distribution": distribution,
                "ucls": {k: round(v, 4) for k, v in ucls.items()},
                "recommended_method": rec_method,
                "recommended_ucl": round(rec_ucl, 4),
            }
        )
    else:
        # --- Censored analysis ---
        km_stats = km_left_censored(values, censored_flags, detection_limits)

        # UCLs
        ucls, rec_method, rec_ucl = compute_ucls_censored(km_stats, n_total)

        # Detected values statistics
        detected_data = values[censored_flags == 0]
        detected_mean = float(np.mean(detected_data))

        # DL/2 substitution mean
        sub_values = []
        for i in range(n_total):
            if censored_flags[i]:
                sub_values.append(float(detection_limits[i]) / 2.0)
            else:
                sub_values.append(float(values[i]))
        dl_half_mean = float(np.mean(sub_values))

        # KM inappropriate flag
        km_inappropriate = any(v < dl_half_mean for v in ucls.values())

        # GOF on detected values
        gof = gof_tests(detected_data)
        distribution = classify_distribution(gof)

        result.update(
            {
                "km_mean": round(km_stats["km_mean"], 4),
                "km_sd": round(km_stats["km_sd"], 4),
                "km_se": round(km_stats["km_se"], 4),
                "km_S_final": round(km_stats["S_final"], 4),
                "detected_mean": round(detected_mean, 4),
                "dl_half_mean": round(dl_half_mean, 4),
                "km_inappropriate": km_inappropriate,
                "gof_on_detects": {
                    "normal_pvalue": round(gof["normal"]["p_value"], 6)
                    if gof["normal"]["p_value"] is not None
                    else None,
                    "normal_pass": gof["normal"]["pass"],
                    "gamma_pvalue": round(gof["gamma"]["p_value"], 6)
                    if gof["gamma"]["p_value"] is not None
                    else None,
                    "gamma_pass": gof["gamma"]["pass"],
                    "lognormal_pvalue": round(gof["lognormal"]["p_value"], 6)
                    if gof["lognormal"]["p_value"] is not None
                    else None,
                    "lognormal_pass": gof["lognormal"]["pass"],
                },
                "distribution": distribution,
                "ucls": {k: round(v, 4) for k, v in ucls.items()},
                "recommended_method": rec_method,
                "recommended_ucl": round(rec_ucl, 4),
            }
        )

    return result


def main():
    data_dir = "/app/data"
    all_results = {}

    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".csv"):
            name = fname.replace(".csv", "")
            path = os.path.join(data_dir, fname)
            print(f"Analyzing {name}...")
            all_results[name] = analyze_dataset(name, path)

    os.makedirs("/app/results", exist_ok=True)
    output_path = "/app/results/analysis.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\nAnalysis complete. Results written to {output_path}")

    # Print summary
    for name, r in all_results.items():
        print(f"\n--- {name} ---")
        print(f"  n={r['n_total']}, detects={r['n_detect']}, NDs={r['n_nondetect']}")
        print(f"  Distribution: {r['distribution']}")
        print(f"  Recommended: {r['recommended_method']} = {r['recommended_ucl']}")
        if "km_inappropriate" in r:
            print(f"  KM inappropriate: {r['km_inappropriate']}")


if __name__ == "__main__":
    main()
