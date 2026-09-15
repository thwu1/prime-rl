#!/usr/bin/env python3
"""
Radiotherapy Clinical Analytics Engine — Reference Solution

Computes BED/EQD2, Kaplan-Meier survival with Greenwood CI,
two-sample log-rank test, and sarcopenia transition analysis
from the HNSCC clinical dataset.

"""

import json
import math
import csv
import sys


def load_data(filepath):
    """Load CSV, handling UTF-8 BOM and returning list of dicts."""
    with open(filepath, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def safe_float(val):
    """Convert value to float, returning None on failure."""
    if val is None:
        return None
    val = str(val).strip()
    if val == '' or val.lower() in ('n/a', 'na', 'nan', 'none'):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def compute_bed_eqd2(total_dose, dose_per_fraction, alpha_beta):
    """Compute BED and EQD2 using linear-quadratic model."""
    bed = total_dose * (1.0 + dose_per_fraction / alpha_beta)
    eqd2 = bed / (1.0 + 2.0 / alpha_beta)
    return bed, eqd2


def kaplan_meier(times, events):
    """
    Kaplan-Meier survival estimator with Greenwood's formula.

    Parameters:
        times: list of observation times
        events: list of event indicators (1=event/death, 0=censored)

    Returns:
        km_times: list of event times where S changes
        km_survival: list of survival probabilities
        km_se: list of standard errors (Greenwood)
    """
    n = len(times)
    if n == 0:
        return [], [], []

    # Sort by time (stable sort)
    pairs = sorted(zip(times, events), key=lambda p: p[0])
    sorted_times = [p[0] for p in pairs]
    sorted_events = [p[1] for p in pairs]

    km_times = []
    km_survival = []
    km_greenwood = []

    n_at_risk = n
    s = 1.0
    greenwood_sum = 0.0

    i = 0
    while i < n:
        t_cur = sorted_times[i]
        d = 0  # deaths at this time
        c = 0  # censorings at this time
        while i < n and sorted_times[i] == t_cur:
            if sorted_events[i] == 1:
                d += 1
            else:
                c += 1
            i += 1

        if d > 0 and n_at_risk > 0:
            s *= (1.0 - d / n_at_risk)
            if n_at_risk > d:
                greenwood_sum += d / (n_at_risk * (n_at_risk - d))

            km_times.append(t_cur)
            km_survival.append(s)
            km_greenwood.append(greenwood_sum)

        n_at_risk -= (d + c)

    # Compute SE from Greenwood
    km_se = [s_val * math.sqrt(g_val) for s_val, g_val in zip(km_survival, km_greenwood)]

    return km_times, km_survival, km_se


def km_at_time(km_times, km_survival, t):
    """Evaluate KM survival function at a given time point."""
    result = 1.0
    for kt, ks in zip(km_times, km_survival):
        if kt <= t:
            result = ks
        else:
            break
    return result


def km_se_at_time(km_times, km_se, t):
    """Evaluate KM standard error at a given time point."""
    result = 0.0
    for kt, se in zip(km_times, km_se):
        if kt <= t:
            result = se
        else:
            break
    return result


def median_survival(km_times, km_survival):
    """Find median survival time (first time S(t) <= 0.5)."""
    for t, s in zip(km_times, km_survival):
        if s <= 0.5:
            return t
    return None


def log_rank_test(times_1, events_1, times_2, events_2):
    """
    Two-sample log-rank (Mantel-Haenszel) test.

    Returns (chi_square, p_value).
    """
    # Collect all unique event times from both groups
    event_times_set = set()
    for t, e in zip(times_1, events_1):
        if e == 1:
            event_times_set.add(t)
    for t, e in zip(times_2, events_2):
        if e == 1:
            event_times_set.add(t)

    unique_event_times = sorted(event_times_set)

    U = 0.0  # sum of (observed - expected) for group 1
    V = 0.0  # variance

    for t in unique_event_times:
        # At-risk in each group at time t
        n1 = sum(1 for x in times_1 if x >= t)
        n2 = sum(1 for x in times_2 if x >= t)
        n_total = n1 + n2

        if n_total <= 1:
            continue

        # Events at time t
        d1 = sum(1 for x, e in zip(times_1, events_1) if x == t and e == 1)
        d2 = sum(1 for x, e in zip(times_2, events_2) if x == t and e == 1)
        d_total = d1 + d2

        if d_total == 0:
            continue

        # Expected under null
        e1 = n1 * d_total / n_total

        # Hypergeometric variance
        v = (n1 * n2 * d_total * (n_total - d_total)) / (n_total ** 2 * (n_total - 1))

        U += (d1 - e1)
        V += v

    if V <= 0:
        return 0.0, 1.0

    chi_sq = U ** 2 / V

    # p-value from chi-square(1) using complementary error function
    # For chi2(1): P(X > x) = erfc(sqrt(x/2))
    p_value = math.erfc(math.sqrt(chi_sq / 2.0))

    return chi_sq, p_value


def main():
    rows = load_data('/app/data/hnscc.csv')
    results = {}

    n_patients = len(rows)
    results['n_patients'] = n_patients

    # ---- RADIOBIOLOGY ----
    bed_tumor_vals = []
    eqd2_tumor_vals = []
    eqd2_late_vals = []
    n_inconsistent = 0
    n_extended = 0

    for row in rows:
        total_dose = safe_float(row.get('RT Total Dose (Gy)'))
        dpf = safe_float(row.get('Dose/Fraction (Gy/fx)'))
        n_fractions = safe_float(row.get('Number of Fractions'))
        treatment_time = safe_float(row.get('Total RT treatment time (days)'))

        if total_dose is not None and dpf is not None and n_fractions is not None:
            bed_t, eqd2_t = compute_bed_eqd2(total_dose, dpf, 10.0)
            _, eqd2_l = compute_bed_eqd2(total_dose, dpf, 3.0)

            bed_tumor_vals.append(bed_t)
            eqd2_tumor_vals.append(eqd2_t)
            eqd2_late_vals.append(eqd2_l)

            if abs(total_dose - dpf * n_fractions) > 1.0:
                n_inconsistent += 1

        if treatment_time is not None and treatment_time > 50:
            n_extended += 1

    n_dose = len(bed_tumor_vals)
    mean_bed = sum(bed_tumor_vals) / n_dose
    mean_eqd2_t = sum(eqd2_tumor_vals) / n_dose
    mean_eqd2_l = sum(eqd2_late_vals) / n_dose
    std_bed = math.sqrt(sum((x - mean_bed) ** 2 for x in bed_tumor_vals) / (n_dose - 1))

    results['radiobiology'] = {
        'bed_tumor_mean': round(mean_bed, 4),
        'bed_tumor_std': round(std_bed, 4),
        'eqd2_tumor_mean': round(mean_eqd2_t, 4),
        'eqd2_late_mean': round(mean_eqd2_l, 4),
        'n_inconsistent_dose': n_inconsistent,
        'n_extended_treatment': n_extended,
    }

    # ---- OVERALL SURVIVAL ----
    # Find the survival column (handles double-space)
    surv_col = None
    censor_col = None
    sample_keys = list(rows[0].keys())
    for k in sample_keys:
        if 'survival' in k.lower() and 'month' in k.lower():
            surv_col = k
        if k.strip().lower() == 'overall survival censor':
            censor_col = k

    times_all = []
    events_all = []
    stage_data = {}  # stage -> [(time, event), ...]

    for row in rows:
        t = safe_float(row.get(surv_col))
        e = safe_float(row.get(censor_col))
        if t is not None and e is not None:
            times_all.append(t)
            events_all.append(int(e))

            stage = row.get('Stage', '').strip()
            if stage in ('III', 'IVA', 'IVB'):
                if stage not in stage_data:
                    stage_data[stage] = ([], [])
                stage_data[stage][0].append(t)
                stage_data[stage][1].append(int(e))

    km_t, km_s, km_se = kaplan_meier(times_all, events_all)

    s_12 = km_at_time(km_t, km_s, 12.0)
    se_12 = km_se_at_time(km_t, km_se, 12.0)

    results['overall_survival'] = {
        'km_12m': round(s_12, 6),
        'km_24m': round(km_at_time(km_t, km_s, 24.0), 6),
        'km_36m': round(km_at_time(km_t, km_s, 36.0), 6),
        'km_60m': round(km_at_time(km_t, km_s, 60.0), 6),
        'median_os_months': None,
        'ci_95_lower_12m': round(max(0.0, s_12 - 1.96 * se_12), 6),
        'ci_95_upper_12m': round(min(1.0, s_12 + 1.96 * se_12), 6),
    }

    med = median_survival(km_t, km_s)
    if med is not None:
        results['overall_survival']['median_os_months'] = round(med, 6)

    # ---- STAGE-STRATIFIED ----
    stage_results = {}
    for stage in ('III', 'IVA', 'IVB'):
        if stage in stage_data:
            st, se_arr = stage_data[stage]
            km_ts, km_ss, _ = kaplan_meier(st, se_arr)
            stage_results[stage] = {
                'km_24m': round(km_at_time(km_ts, km_ss, 24.0), 6),
                'n_patients': len(st),
            }
        else:
            stage_results[stage] = {'km_24m': None, 'n_patients': 0}

    results['stage_stratified'] = stage_results

    # ---- LOG-RANK TEST: Stage III vs Stage IV (IVA+IVB) ----
    t_iii = stage_data.get('III', ([], []))
    t_iva = stage_data.get('IVA', ([], []))
    t_ivb = stage_data.get('IVB', ([], []))

    times_iv = t_iva[0] + t_ivb[0]
    events_iv = t_iva[1] + t_ivb[1]

    chi_sq, p_val = log_rank_test(t_iii[0], t_iii[1], times_iv, events_iv)

    results['log_rank'] = {
        'chi_square': round(chi_sq, 4),
        'p_value': round(p_val, 6),
    }

    # ---- SARCOPENIA ----
    pre_col = 'PreRT Skeletal Muscle status'
    post_col = 'PostRT Skeletal Muscle status'
    smi_pre_col = 'Pre-RT L3 Skeletal Muscle Index (cm2/m2)'
    smi_post_col = 'Post-RT L3 Skeletal Muscle Index (cm2/m2)'

    pre_depleted = 0
    post_depleted = 0
    pre_valid = 0
    post_valid = 0
    dd = 0; dn = 0; nd = 0; nn = 0
    smi_pre_vals = []
    smi_post_vals = []

    for row in rows:
        pre_status = row.get(pre_col, '').strip()
        post_status = row.get(post_col, '').strip()

        if pre_status:
            pre_valid += 1
            if pre_status == 'SM depleted':
                pre_depleted += 1

        if post_status:
            post_valid += 1
            if post_status == 'SM depleted':
                post_depleted += 1

        # Transitions (need both valid)
        if pre_status and post_status:
            p_d = pre_status == 'SM depleted'
            q_d = post_status == 'SM depleted'
            if p_d and q_d:
                dd += 1
            elif p_d and not q_d:
                dn += 1
            elif not p_d and q_d:
                nd += 1
            else:
                nn += 1

        # SMI values
        smi_pre = safe_float(row.get(smi_pre_col))
        smi_post = safe_float(row.get(smi_post_col))
        if smi_pre is not None and smi_post is not None:
            smi_pre_vals.append(smi_pre)
            smi_post_vals.append(smi_post)

    n_smi = len(smi_pre_vals)
    mean_smi_pre = sum(smi_pre_vals) / n_smi if n_smi > 0 else 0.0
    mean_smi_post = sum(smi_post_vals) / n_smi if n_smi > 0 else 0.0
    mean_smi_change = sum(b - a for a, b in zip(smi_pre_vals, smi_post_vals)) / n_smi if n_smi > 0 else 0.0

    results['sarcopenia'] = {
        'pre_rt_depleted_count': pre_depleted,
        'post_rt_depleted_count': post_depleted,
        'pre_rt_prevalence': round(pre_depleted / pre_valid, 6) if pre_valid > 0 else 0.0,
        'post_rt_prevalence': round(post_depleted / post_valid, 6) if post_valid > 0 else 0.0,
        'mean_smi_pre_rt': round(mean_smi_pre, 4),
        'mean_smi_post_rt': round(mean_smi_post, 4),
        'mean_smi_change': round(mean_smi_change, 4),
        'transition_dd': dd,
        'transition_dn': dn,
        'transition_nd': nd,
        'transition_nn': nn,
    }

    # Write output
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == '__main__':
    main()
