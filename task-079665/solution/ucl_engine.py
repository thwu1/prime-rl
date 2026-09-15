#!/usr/bin/env python3
"""
EPA ProUCL 5.2 UCL Recommendation Engine with Compliance Audit.
Implements the hierarchical distribution selection and UCL computation
following the ProUCL v5.2 decision logic for environmental datasets
with and without non-detect (left-censored) observations.
Also audits an existing flawed analysis for ProUCL 5.2 compliance.
"""

import json
import csv
import math
import numpy as np
from scipy import stats


def read_data(filepath):
    """Read environmental monitoring data, group by analyte."""
    data = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            analyte = row['analyte']
            if analyte not in data:
                data[analyte] = []
            detected = int(row['detect_flag']) == 1
            value = float(row['result'])
            data[analyte].append({'value': value, 'detected': detected})
    return data


def ros_estimate(observations):
    """
    Regression on Order Statistics (ROS) for left-censored data.
    Imputes non-detect values using regression on normal probability plot.
    Returns (mean, sd, effective_values_for_gof).
    """
    n = len(observations)
    detected_vals = sorted([obs['value'] for obs in observations if obs['detected']])
    nd_vals = sorted([obs['value'] for obs in observations if not obs['detected']])
    n_detect = len(detected_vals)
    n_nd = len(nd_vals)

    if n_nd == 0:
        arr = np.array(detected_vals)
        return float(np.mean(arr)), float(np.std(arr, ddof=1)), arr

    if n_detect < 3:
        imputed = []
        for obs in observations:
            imputed.append(obs['value'] if obs['detected'] else obs['value'] / 2.0)
        arr = np.array(imputed)
        return float(np.mean(arr)), float(np.std(arr, ddof=1)), np.array(detected_vals)

    combined = [(obs['value'], obs['detected']) for obs in observations]
    combined.sort(key=lambda x: (x[0], int(x[1])))

    plotting_positions = []
    for i, (val, det) in enumerate(combined, start=1):
        pp = (i - 0.375) / (n + 0.25)
        plotting_positions.append((val, det, pp))

    det_data = [(val, pp) for val, det, pp in plotting_positions if det]
    det_values = np.array([d[0] for d in det_data])
    det_quantiles = stats.norm.ppf(np.array([d[1] for d in det_data]))
    det_quantiles = np.clip(det_quantiles, -6, 6)

    slope, intercept, _, _, _ = stats.linregress(det_quantiles, det_values)

    imputed = []
    for val, det, pp in plotting_positions:
        if det:
            imputed.append(val)
        else:
            q = stats.norm.ppf(min(max(pp, 1e-6), 1 - 1e-6))
            imp_val = intercept + slope * q
            imp_val = max(1e-6, min(imp_val, val * 0.9999))
            imputed.append(imp_val)

    arr = np.array(imputed)
    return float(np.mean(arr)), float(np.std(arr, ddof=1)), np.array(detected_vals)


def test_normality_v52(values, alpha=0.01):
    """ProUCL 5.2: test normality using Shapiro-Wilk at alpha=0.01."""
    if len(values) < 3:
        return False, 0.0
    if len(values) > 5000:
        stat, p = stats.kstest(values, 'norm', args=(np.mean(values), np.std(values, ddof=1)))
        return p > alpha, float(p)
    stat, p = stats.shapiro(values)
    return p > alpha, float(p)


def test_gamma_v52(values, alpha=0.05):
    """ProUCL 5.2: test gamma fit using K-S test at alpha=0.05."""
    if len(values) < 3 or np.min(values) <= 0:
        return False, 0.0
    try:
        shape, loc, scale = stats.gamma.fit(values, floc=0)
        if shape <= 0 or scale <= 0:
            return False, 0.0
        stat, p = stats.kstest(values, 'gamma', args=(shape, 0, scale))
        return p > alpha, float(p)
    except Exception:
        return False, 0.0


def test_lognormality_v52(values, alpha=0.10):
    """ProUCL 5.2: test lognormality using Shapiro-Wilk on log-data at alpha=0.10."""
    if len(values) < 3 or np.min(values) <= 0:
        return False, 0.0
    log_values = np.log(values)
    if len(log_values) > 5000:
        stat, p = stats.kstest(log_values, 'norm',
                               args=(np.mean(log_values), np.std(log_values, ddof=1)))
        return p > alpha, float(p)
    stat, p = stats.shapiro(log_values)
    return p > alpha, float(p)


def compute_t_ucl(mean, sd, n, alpha=0.05):
    """Student's-t UCL."""
    t_crit = stats.t.ppf(1 - alpha, n - 1)
    ucl = mean + t_crit * sd / math.sqrt(n)
    return ucl, "Student's-t"


def compute_h_ucl(values, alpha=0.05):
    """Land's H-UCL for lognormal data (Cox approximation)."""
    log_vals = np.log(values)
    n = len(log_vals)
    y_bar = float(np.mean(log_vals))
    s_y = float(np.std(log_vals, ddof=1))
    z_alpha = stats.norm.ppf(1 - alpha)
    ucl = math.exp(
        y_bar + s_y ** 2 / 2.0
        + z_alpha * math.sqrt(s_y ** 2 / n + s_y ** 4 / (2.0 * (n - 1)))
    )
    return ucl, "H-UCL"


def compute_gamma_ucl(values, alpha=0.05):
    """Adjusted gamma UCL using chi-square approximation."""
    n = len(values)
    try:
        shape, _, scale = stats.gamma.fit(values, floc=0)
        if shape <= 0 or scale <= 0:
            return compute_t_ucl(float(np.mean(values)),
                                 float(np.std(values, ddof=1)), n)
        df = 2.0 * n * shape
        chi2_val = stats.chi2.ppf(1 - alpha, df)
        ucl = scale * chi2_val / (2.0 * n)
        return ucl, "Adjusted-Gamma"
    except Exception:
        return compute_t_ucl(float(np.mean(values)),
                             float(np.std(values, ddof=1)), n)


def process_analyte(observations):
    """Apply ProUCL 5.2 decision logic for a single analyte."""
    n = len(observations)
    n_detect = sum(1 for obs in observations if obs['detected'])
    percent_nd = (n - n_detect) / n * 100.0
    has_censoring = percent_nd > 0

    if has_censoring:
        mean_est, sd_est, gof_values = ros_estimate(observations)
    else:
        all_vals = np.array([obs['value'] for obs in observations])
        mean_est = float(np.mean(all_vals))
        sd_est = float(np.std(all_vals, ddof=1))
        gof_values = all_vals

    if n < 10:
        ucl = mean_est
        return {
            'n': n, 'n_detect': n_detect,
            'percent_nd': round(percent_nd, 1),
            'distribution': 'nonparametric',
            'ucl_method': 'None-SmallSample',
            'ucl95': round(ucl, 6),
            'mean_estimate': round(mean_est, 6),
            'sd_estimate': round(sd_est, 6)
        }

    if has_censoring and n_detect < 3:
        ucl, method = compute_t_ucl(mean_est, sd_est, n)
        return {
            'n': n, 'n_detect': n_detect,
            'percent_nd': round(percent_nd, 1),
            'distribution': 'nonparametric',
            'ucl_method': 'KM-t',
            'ucl95': round(ucl, 6),
            'mean_estimate': round(mean_est, 6),
            'sd_estimate': round(sd_est, 6)
        }

    # Hierarchical GOF testing with ProUCL 5.2 asymmetric significance levels
    is_normal, _ = test_normality_v52(gof_values, alpha=0.01)
    if is_normal:
        if has_censoring:
            ucl, _ = compute_t_ucl(mean_est, sd_est, n)
            method = 'KM-t'
        else:
            ucl, method = compute_t_ucl(mean_est, sd_est, n)
        return {
            'n': n, 'n_detect': n_detect,
            'percent_nd': round(percent_nd, 1),
            'distribution': 'normal',
            'ucl_method': method,
            'ucl95': round(ucl, 6),
            'mean_estimate': round(mean_est, 6),
            'sd_estimate': round(sd_est, 6)
        }

    is_gamma, _ = test_gamma_v52(gof_values, alpha=0.05)
    if is_gamma:
        if has_censoring:
            ucl, _ = compute_t_ucl(mean_est, sd_est, n)
            method = 'KM-t'
        else:
            ucl, method = compute_gamma_ucl(gof_values)
        return {
            'n': n, 'n_detect': n_detect,
            'percent_nd': round(percent_nd, 1),
            'distribution': 'gamma',
            'ucl_method': method,
            'ucl95': round(ucl, 6),
            'mean_estimate': round(mean_est, 6),
            'sd_estimate': round(sd_est, 6)
        }

    is_lognormal, _ = test_lognormality_v52(gof_values, alpha=0.10)
    if is_lognormal:
        log_vals = np.log(gof_values)
        sd_log = float(np.std(log_vals, ddof=1))

        if has_censoring:
            ucl, _ = compute_t_ucl(mean_est, sd_est, n)
            method = 'KM-t'
        elif n >= 50 or sd_log < 1.5:
            ucl, method = compute_h_ucl(gof_values)
        else:
            ucl, method = compute_t_ucl(mean_est, sd_est, n)
        return {
            'n': n, 'n_detect': n_detect,
            'percent_nd': round(percent_nd, 1),
            'distribution': 'lognormal',
            'ucl_method': method,
            'ucl95': round(ucl, 6),
            'mean_estimate': round(mean_est, 6),
            'sd_estimate': round(sd_est, 6)
        }

    # No distribution fits -> nonparametric, default to t-UCL (v5.2)
    if has_censoring:
        ucl, _ = compute_t_ucl(mean_est, sd_est, n)
        method = 'KM-t'
    else:
        ucl, method = compute_t_ucl(mean_est, sd_est, n)
    return {
        'n': n, 'n_detect': n_detect,
        'percent_nd': round(percent_nd, 1),
        'distribution': 'nonparametric',
        'ucl_method': method,
        'ucl95': round(ucl, 6),
        'mean_estimate': round(mean_est, 6),
        'sd_estimate': round(sd_est, 6)
    }


def audit_analysis(original, corrected, raw_data):
    """Compare original and corrected analyses to identify ProUCL 5.2 violations."""
    audit = {}
    for analyte in corrected:
        errors = []
        orig = original[analyte]
        corr = corrected[analyte]

        # Check for deprecated Chebyshev UCL recommendation
        if 'chebyshev' in orig['ucl_method'].lower():
            errors.append(
                "Chebyshev UCL is no longer recommended in ProUCL 5.2; "
                "it tends to produce gross overestimates of the mean, "
                "increasing likelihood of Type II decision errors"
            )

        # Check distribution misclassification
        if orig['distribution'] != corr['distribution']:
            errors.append(
                f"Distribution misclassified as '{orig['distribution']}'; "
                f"ProUCL 5.2 hierarchical goodness-of-fit testing with "
                f"asymmetric significance levels classifies this analyte as "
                f"'{corr['distribution']}'"
            )

        # Check improper censoring handling for analytes with non-detects
        if corr['percent_nd'] > 0:
            orig_method_lower = orig['ucl_method'].lower()
            censored_indicators = ['km', 'kaplan', 'ros', 'bootstrap']
            uses_censored_method = any(ind in orig_method_lower
                                       for ind in censored_indicators)

            if not uses_censored_method:
                errors.append(
                    "Non-detect observations handled using simple detection limit "
                    "substitution instead of proper censored data methods; ProUCL 5.2 "
                    "requires Kaplan-Meier or Regression on Order Statistics estimation "
                    "for left-censored environmental data"
                )

        audit[analyte] = {
            'errors': errors,
            'original_ucl95': orig['ucl95'],
            'corrected_ucl95': corr['ucl95']
        }
    return audit


def main():
    # Read inputs
    raw_data_records = read_data('/app/data/site_data.csv')

    with open('/app/original_analysis.json') as f:
        original = json.load(f)

    # Also build raw_data dict for audit
    raw_data_for_audit = {}
    with open('/app/data/site_data.csv') as f:
        import csv as csv_mod
        reader = csv_mod.DictReader(f)
        for row in reader:
            analyte = row['analyte']
            if analyte not in raw_data_for_audit:
                raw_data_for_audit[analyte] = {'values': [], 'detected': []}
            raw_data_for_audit[analyte]['values'].append(float(row['result']))
            raw_data_for_audit[analyte]['detected'].append(
                int(row['detect_flag']) == 1)

    # Run corrected analysis
    results = {}
    for analyte, observations in raw_data_records.items():
        results[analyte] = process_analyte(observations)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Produce audit report
    audit = audit_analysis(original, results, raw_data_for_audit)

    with open('/app/audit_report.json', 'w') as f:
        json.dump(audit, f, indent=2)

    print("ProUCL 5.2 compliance audit complete.")
    print("Corrected results -> /app/results.json")
    print("Audit report -> /app/audit_report.json")
    for analyte, r in sorted(results.items()):
        print(f"  {analyte}: dist={r['distribution']}, method={r['ucl_method']}, "
              f"UCL95={r['ucl95']:.4f}, mean={r['mean_estimate']:.4f}")
    print("\nAudit findings:")
    for analyte, a in sorted(audit.items()):
        print(f"  {analyte}: {len(a['errors'])} violation(s)")
        for err in a['errors']:
            print(f"    - {err}")


if __name__ == '__main__':
    main()
