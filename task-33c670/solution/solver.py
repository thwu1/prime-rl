#!/usr/bin/env python3
"""
Reference solution for the Environmental Site UCL Audit task.

Audits and corrects a flawed preliminary UCL analysis following
EPA ProUCL 5.2 methodology.

"""

import csv
import json
import math
import os
import re
import sqlite3
import sys

import numpy as np
from scipy import stats


# ──────────────────────────────────────────────────────────────
# Data loading — heterogeneous formats
# ──────────────────────────────────────────────────────────────

def load_mw1_arsenic(path):
    """Load MW-1 arsenic CSV: sample_id,collection_date,arsenic_ug_l,qualifier"""
    values, detects = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            values.append(float(row["arsenic_ug_l"]))
            qual = row.get("qualifier", "").strip()
            detects.append(qual == "" or qual.upper() not in ("U", "ND"))
    return np.array(values), np.array(detects, dtype=bool)


def load_mw2_tce(path):
    """Load MW-2 TCE CSV: monitoring_well,parameter,result_value,result_unit"""
    values, detects = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            values.append(float(row["result_value"]))
            detects.append(True)  # all detected
    return np.array(values), np.array(detects, dtype=bool)


def load_mw3_lead(path):
    """Load MW-3 lead CSV with <DL notation: well_id,sample_date,lead_ug_l"""
    values, detects = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            val_str = row["lead_ug_l"].strip()
            if val_str.startswith("<"):
                values.append(float(val_str[1:]))
                detects.append(False)
            else:
                values.append(float(val_str))
                detects.append(True)
    return np.array(values), np.array(detects, dtype=bool)


def load_mw4_benzene(db_path):
    """Load MW-4 benzene from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT result, detection_limit, detect_flag FROM benzene_monitoring"
    )
    values, detects = [], []
    for result, dl, flag in cursor.fetchall():
        values.append(result)
        detects.append(bool(flag))
    conn.close()
    return np.array(values), np.array(detects, dtype=bool)


def load_mw5_chromium(path):
    """Load MW-5 chromium CSV: sample_id,cr_concentration,data_qualifier"""
    values, detects = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            values.append(float(row["cr_concentration"]))
            qual = row.get("data_qualifier", "").strip()
            detects.append(qual.upper() != "U")
    return np.array(values), np.array(detects, dtype=bool)


# ──────────────────────────────────────────────────────────────
# Kaplan-Meier for left-censored data (reversed approach)
# ──────────────────────────────────────────────────────────────

def km_left_censored(values, detects):
    """
    Compute KM estimates for left-censored data.
    Transform Y = -X: left-censoring becomes right-censoring.
    Apply standard KM, compute restricted mean via area under survival curve.
    """
    n = len(values)
    y_vals = -values
    y_events = detects.copy()

    order = np.lexsort((-y_events.astype(int), y_vals))
    y_sorted = y_vals[order]
    ev_sorted = y_events[order]

    surv = 1.0
    at_risk = n
    km_steps = []

    i = 0
    while i < n:
        y_cur = y_sorted[i]
        d, c = 0, 0
        while i < n and y_sorted[i] == y_cur:
            if ev_sorted[i]:
                d += 1
            else:
                c += 1
            i += 1
        if d > 0:
            s_before = surv
            surv *= (1.0 - d / at_risk)
            km_steps.append((y_cur, s_before, surv))
        at_risk -= (d + c)

    max_x = float(np.max(values))
    all_x = sorted(set([0.0] + list(values) + [max_x]))
    all_x = [x for x in all_x if 0 <= x <= max_x]
    all_x = sorted(set(all_x))

    def f_x(x):
        y = -x
        s = 1.0
        for y_ev, s_bef, s_aft in km_steps:
            if y > y_ev:
                s = s_aft
            elif y == y_ev:
                return s_bef
            else:
                break
        return s

    km_mean = 0.0
    for j in range(len(all_x) - 1):
        x_lo = all_x[j]
        x_hi = all_x[j + 1]
        x_mid = (x_lo + x_hi) / 2.0
        f_val = f_x(x_mid)
        km_mean += (x_hi - x_lo) * (1.0 - f_val)

    prob_masses = []
    for y_ev, s_bef, s_aft in km_steps:
        prob_masses.append((-y_ev, s_bef - s_aft))

    total_mass = sum(p for _, p in prob_masses)
    if total_mass > 0:
        km_var = sum(p * (x - km_mean) ** 2 for x, p in prob_masses)
        km_var = km_var / total_mass
        km_var *= n / (n - 1)
        km_sd = math.sqrt(max(km_var, 0))
    else:
        km_sd = 0.0

    return km_mean, km_sd


# ──────────────────────────────────────────────────────────────
# Robust ROS (Regression on Order Statistics)
# ──────────────────────────────────────────────────────────────

def robust_ros(values, detects):
    """ROS: fit log-linear regression on detected values at Blom positions,
    impute non-detects."""
    n = len(values)
    n_detect = int(np.sum(detects))

    if n_detect < 2:
        return float(np.mean(values)), float(np.std(values, ddof=1))

    order = np.argsort(values)
    sorted_vals = values[order]
    sorted_det = detects[order]

    pp = np.array([(i + 1 - 0.375) / (n + 0.25) for i in range(n)])

    det_mask = sorted_det.astype(bool)
    det_vals = sorted_vals[det_mask]
    det_pp = pp[det_mask]
    det_z = stats.norm.ppf(det_pp)

    if np.any(det_vals <= 0):
        log_det = det_vals
        use_log = False
    else:
        log_det = np.log(det_vals)
        use_log = True

    slope, intercept, _, _, _ = stats.linregress(det_z, log_det)

    nd_mask = ~det_mask
    nd_pp = pp[nd_mask]
    nd_z = stats.norm.ppf(nd_pp)

    if use_log:
        imputed = np.exp(intercept + slope * nd_z)
    else:
        imputed = intercept + slope * nd_z

    nd_dls = sorted_vals[nd_mask]
    imputed = np.minimum(imputed, nd_dls)
    imputed = np.maximum(imputed, 0.001)

    combined = np.concatenate([det_vals, imputed])
    return float(np.mean(combined)), float(np.std(combined, ddof=1))


# ──────────────────────────────────────────────────────────────
# Goodness-of-fit tests
# ──────────────────────────────────────────────────────────────

def test_normality(values, alpha=0.05):
    if len(values) < 3:
        return False
    _, p = stats.shapiro(values)
    return p > alpha


def test_gamma_fit(values, alpha=0.05):
    if len(values) < 5 or np.any(values <= 0):
        return False
    try:
        a, loc, scale = stats.gamma.fit(values, floc=0)
        _, p = stats.kstest(values, 'gamma', args=(a, loc, scale))
        return p > alpha
    except Exception:
        return False


def test_lognormal_fit(values, alpha=0.05):
    if len(values) < 3 or np.any(values <= 0):
        return False
    _, p = stats.shapiro(np.log(values))
    return p > alpha


# ──────────────────────────────────────────────────────────────
# UCL computation methods
# ──────────────────────────────────────────────────────────────

def ucl_student_t(mean, sd, n, confidence=0.95):
    t_crit = stats.t.ppf(confidence, n - 1)
    return mean + t_crit * sd / math.sqrt(n)


def ucl_chebyshev(mean, sd, n, confidence=0.95):
    alpha = 1 - confidence
    return mean + math.sqrt((1.0 / alpha - 1.0) / n) * sd


def ucl_bootstrap_bca(values, confidence=0.95, n_boot=2000, seed=12345):
    rng = np.random.RandomState(seed)
    n = len(values)
    observed_mean = np.mean(values)

    boot_means = np.array([
        np.mean(rng.choice(values, size=n, replace=True))
        for _ in range(n_boot)
    ])

    prop_below = np.mean(boot_means < observed_mean)
    if prop_below == 0:
        prop_below = 1 / (2 * n_boot)
    elif prop_below == 1:
        prop_below = 1 - 1 / (2 * n_boot)
    z0 = stats.norm.ppf(prop_below)

    jackknife_means = np.array([
        np.mean(np.delete(values, i)) for i in range(n)
    ])
    jk_mean = np.mean(jackknife_means)
    num = np.sum((jk_mean - jackknife_means) ** 3)
    den = np.sum((jk_mean - jackknife_means) ** 2)
    a = num / (6.0 * den ** 1.5) if den != 0 else 0

    z_alpha = stats.norm.ppf(confidence)
    adjusted = z0 + (z0 + z_alpha) / (1 - a * (z0 + z_alpha))
    adjusted_percentile = stats.norm.cdf(adjusted)
    adjusted_percentile = max(0.5 / n_boot,
                              min(adjusted_percentile, 1 - 0.5 / n_boot))

    return float(np.percentile(boot_means, adjusted_percentile * 100))


def ucl_halls_bootstrap(values, confidence=0.95, n_boot=2000, seed=12345):
    rng = np.random.RandomState(seed)
    n = len(values)
    observed_mean = np.mean(values)
    observed_se = np.std(values, ddof=1) / math.sqrt(n)

    if observed_se == 0:
        return observed_mean

    t_stats = []
    for _ in range(n_boot):
        sample = rng.choice(values, size=n, replace=True)
        boot_mean = np.mean(sample)
        boot_se = np.std(sample, ddof=1) / math.sqrt(n)
        if boot_se > 0:
            t_stats.append((boot_mean - observed_mean) / boot_se)

    if not t_stats:
        return ucl_student_t(observed_mean, np.std(values, ddof=1), n, confidence)

    t_stats = np.array(t_stats)
    t_crit = np.percentile(t_stats, confidence * 100)
    return observed_mean + t_crit * observed_se


def ucl_h_ucl(values, confidence=0.95):
    log_vals = np.log(values)
    n = len(values)
    mu_y = np.mean(log_vals)
    sigma_y = np.std(log_vals, ddof=1)
    t_crit = stats.t.ppf(confidence, n - 1)
    h_val = t_crit * sigma_y / math.sqrt(n) + 0.5 * sigma_y ** 2
    return math.exp(mu_y + h_val)


def ucl_adjusted_gamma(values, confidence=0.95):
    try:
        n = len(values)
        mean = np.mean(values)
        sd = np.std(values, ddof=1)
        k_hat = (mean / sd) ** 2
        theta_hat = sd ** 2 / mean
        df = 2 * n * k_hat
        chi2_crit = stats.chi2.ppf(confidence, df)
        ucl = theta_hat * chi2_crit / (2 * n)
        if ucl < mean or math.isnan(ucl) or math.isinf(ucl):
            ucl = ucl_student_t(mean, sd, n, confidence)
        return ucl
    except Exception:
        return ucl_student_t(np.mean(values), np.std(values, ddof=1),
                             len(values), confidence)


def compute_skewness(values):
    n = len(values)
    if n < 3:
        return 0.0
    mean = np.mean(values)
    sd = np.std(values, ddof=1)
    if sd == 0:
        return 0.0
    return float(
        (n / ((n - 1) * (n - 2))) * np.sum(((values - mean) / sd) ** 3)
    )


# ──────────────────────────────────────────────────────────────
# Decision logic
# ──────────────────────────────────────────────────────────────

def decide_ucl_full(values, confidence=0.95):
    n = len(values)
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    skew = compute_skewness(values)

    ucls = {}
    ucls["student_t"] = ucl_student_t(mean, sd, n, confidence)
    ucls["chebyshev"] = ucl_chebyshev(mean, sd, n, confidence)
    ucls["bootstrap_bca"] = ucl_bootstrap_bca(values, confidence)

    if n >= 20:
        ucls["halls_bootstrap"] = ucl_halls_bootstrap(values, confidence)

    gof_normal = test_normality(values)
    gof_gamma = test_gamma_fit(values)
    gof_lognormal = test_lognormal_fit(values)

    if gof_gamma and np.all(values > 0):
        ucls["adjusted_gamma"] = ucl_adjusted_gamma(values, confidence)
    if gof_lognormal and np.all(values > 0):
        ucls["h_ucl"] = ucl_h_ucl(values, confidence)

    gof = {
        "gof_normal": bool(gof_normal),
        "gof_gamma": bool(gof_gamma),
        "gof_lognormal": bool(gof_lognormal),
    }

    if n < 10:
        rec_method = "student_t"
    elif gof_normal:
        rec_method = "student_t"
    elif gof_gamma:
        rec_method = "adjusted_gamma"
    elif gof_lognormal and n >= 70:
        rec_method = "h_ucl"
    elif gof_lognormal and abs(skew) <= 1.0:
        rec_method = "h_ucl"
    elif n >= 20:
        rec_method = "halls_bootstrap"
    else:
        rec_method = "bootstrap_bca"

    if rec_method == "chebyshev":
        rec_method = "bootstrap_bca"

    rec_ucl = ucls.get(rec_method, ucls["student_t"])
    return rec_method, rec_ucl, ucls, gof, skew


def decide_ucl_censored(values, detects, confidence=0.95):
    n = len(values)
    n_detect = int(np.sum(detects))
    pct_nd = 100.0 * (1 - n_detect / n)

    km_mean, km_sd = km_left_censored(values, detects)
    ros_mean, ros_sd = robust_ros(values, detects)

    ucls = {}
    if km_sd > 0 and n_detect > 1:
        ucls["km_t"] = ucl_student_t(km_mean, km_sd, n, confidence)
    det_vals = values[detects]
    if len(det_vals) >= 5:
        ucls["km_bootstrap_bca"] = ucl_bootstrap_bca(det_vals, confidence)
    if km_sd > 0:
        ucls["km_chebyshev"] = ucl_chebyshev(km_mean, km_sd, n, confidence)
    if ros_sd > 0:
        ucls["ros_t"] = ucl_student_t(ros_mean, ros_sd, n, confidence)

    if n < 10:
        rec_method = "km_t" if "km_t" in ucls else "ros_t"
    elif pct_nd > 50:
        if "km_t" in ucls:
            rec_method = "km_t"
        elif "km_bootstrap_bca" in ucls:
            rec_method = "km_bootstrap_bca"
        else:
            rec_method = "km_chebyshev"
    elif n_detect >= 10:
        gof_normal = test_normality(det_vals)
        if gof_normal:
            rec_method = "km_t"
        else:
            rec_method = "km_bootstrap_bca" if "km_bootstrap_bca" in ucls else "km_t"
    else:
        rec_method = "km_t" if "km_t" in ucls else "km_chebyshev"

    # Never recommend chebyshev
    if "chebyshev" in rec_method.lower():
        rec_method = "km_t" if "km_t" in ucls else list(ucls.keys())[0]

    rec_ucl = ucls.get(rec_method, list(ucls.values())[0] if ucls else km_mean)
    return rec_method, rec_ucl, ucls, km_mean, km_sd, ros_mean, ros_sd, pct_nd


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def process_full(values, detects):
    n = len(values)
    n_detect = int(np.sum(detects))
    rec_method, rec_ucl, ucls, gof, skew = decide_ucl_full(values)
    return {
        "n": n,
        "n_detect": n_detect,
        "pct_nd": 0.0,
        "mean": round(float(np.mean(values)), 6),
        "sd": round(float(np.std(values, ddof=1)), 6),
        "skewness": round(skew, 6),
        **gof,
        "ucl_values": {k: round(v, 6) for k, v in ucls.items()},
        "recommended_method": rec_method,
        "recommended_ucl": round(rec_ucl, 6),
    }


def process_censored(values, detects):
    n = len(values)
    n_detect = int(np.sum(detects))
    rec_method, rec_ucl, ucls, km_mean, km_sd, ros_mean, ros_sd, pct_nd = (
        decide_ucl_censored(values, detects)
    )
    return {
        "n": n,
        "n_detect": n_detect,
        "pct_nd": round(pct_nd, 1),
        "km_mean": round(km_mean, 6),
        "km_sd": round(km_sd, 6),
        "ros_mean": round(ros_mean, 6),
        "ros_sd": round(ros_sd, 6),
        "ucl_values": {k: round(v, 6) for k, v in ucls.items()},
        "recommended_method": rec_method,
        "recommended_ucl": round(rec_ucl, 6),
    }


def main():
    datasets = {
        "MW-1_Arsenic": lambda: load_mw1_arsenic("/app/site_data/mw1_arsenic.csv"),
        "MW-2_TCE": lambda: load_mw2_tce("/app/site_data/mw2_tce.csv"),
        "MW-3_Lead": lambda: load_mw3_lead("/app/site_data/mw3_lead.csv"),
        "MW-4_Benzene": lambda: load_mw4_benzene("/app/site_data/mw4_benzene.db"),
        "MW-5_Chromium": lambda: load_mw5_chromium("/app/site_data/mw5_chromium.csv"),
    }

    results = {}
    for name, loader in datasets.items():
        print(f"Processing {name}...")
        values, detects = loader()
        n_detect = int(np.sum(detects))

        if n_detect == len(values):
            results[name] = process_full(values, detects)
        else:
            results[name] = process_censored(values, detects)

        print(f"  n={len(values)}, n_detect={n_detect}, "
              f"recommended: {results[name]['recommended_method']} = "
              f"{results[name]['recommended_ucl']}")

    output_path = "/app/results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
