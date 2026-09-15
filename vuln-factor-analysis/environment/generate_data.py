#!/usr/bin/env python3
"""Generate synthetic vulnerability reproduction experiment dataset
and a flawed preliminary analysis for the audit task.

Creates a deterministic dataset of 100 kernel vulnerability reproduction
experiments with properties matching empirical distributions from K-Repro
research, plus a deliberately flawed preliminary analysis containing
data handling, methodological, and computational errors.

"""
import csv
import json
import math
import random
import os

random.seed(42)

os.makedirs('/app/data', exist_ok=True)

# ---------------------------------------------------------------
# Step 1: Define fixed vulnerability structure matching paper
# distributions: 82 UAF/DF, 16 OOB, 2 other; 24 race conditions;
# subsystems: net=50, netfilter=34, bpf=7, other=9
# ---------------------------------------------------------------
structure = []

# net (50): 41 uaf_df (9 race) + 8 oob (1 race) + 1 other (0 race)
structure.extend([('net', 'uaf_df', True)] * 9)
structure.extend([('net', 'uaf_df', False)] * 32)
structure.extend([('net', 'oob', True)] * 1)
structure.extend([('net', 'oob', False)] * 7)
structure.extend([('net', 'other', False)] * 1)

# netfilter (34): 27 uaf_df (8 race) + 6 oob (0 race) + 1 other (1 race)
structure.extend([('netfilter', 'uaf_df', True)] * 8)
structure.extend([('netfilter', 'uaf_df', False)] * 19)
structure.extend([('netfilter', 'oob', False)] * 6)
structure.extend([('netfilter', 'other', True)] * 1)

# bpf (7): 7 uaf_df (3 race)
structure.extend([('bpf', 'uaf_df', True)] * 3)
structure.extend([('bpf', 'uaf_df', False)] * 4)

# other (9): 7 uaf_df (2 race) + 2 oob (0 race)
structure.extend([('other', 'uaf_df', True)] * 2)
structure.extend([('other', 'uaf_df', False)] * 5)
structure.extend([('other', 'oob', False)] * 2)

# Verify counts
assert len(structure) == 100
assert sum(1 for s in structure if s[1] == 'uaf_df') == 82
assert sum(1 for s in structure if s[1] == 'oob') == 16
assert sum(1 for s in structure if s[1] == 'other') == 2
assert sum(1 for s in structure if s[2]) == 24
assert sum(1 for s in structure if s[0] == 'net') == 50
assert sum(1 for s in structure if s[0] == 'netfilter') == 34
assert sum(1 for s in structure if s[0] == 'bpf') == 7
assert sum(1 for s in structure if s[0] == 'other') == 9

# Shuffle for realistic ordering
random.shuffle(structure)

# ---------------------------------------------------------------
# Step 2: Generate outcomes probabilistically
# ---------------------------------------------------------------
cases = []

for idx, (sub, vt, race) in enumerate(structure):
    # Base success probabilities calibrated to paper results
    xhigh_p = 0.58
    medium_p = 0.47

    # Race condition penalty (paper: 29% race vs 65% non-race for XHigh)
    if race:
        xhigh_p -= 0.30
        medium_p -= 0.32

    # Vulnerability type effect (paper: OOB significantly easier than UAF/DF)
    if vt == 'oob':
        xhigh_p += 0.25
        medium_p += 0.25
    elif vt == 'other':
        xhigh_p -= 0.15
        medium_p -= 0.15

    # Commit message level (paper distribution: 13% type1, 79% type2, 8% type3)
    cml = random.choices([1, 2, 3], weights=[13, 79, 8])[0]
    if cml == 3:
        xhigh_p += 0.15
        medium_p += 0.15
    elif cml == 1:
        xhigh_p -= 0.10
        medium_p -= 0.10

    # Pre/post knowledge cutoff
    pre_cutoff = int(random.random() < 0.58)
    if not pre_cutoff:
        xhigh_p -= 0.05
        medium_p -= 0.05

    # Clamp probabilities
    xhigh_p = max(0.03, min(0.97, xhigh_p))
    medium_p = max(0.03, min(0.97, medium_p))

    # Draw outcomes
    xr1 = int(random.random() < xhigh_p)
    mr1 = int(random.random() < medium_p)
    xr2 = int(random.random() < xhigh_p)

    # Generate timing and cost (distributions from paper)
    if xr1:
        xt = round(random.uniform(5.0, 33.9), 2)
        xc = round(random.uniform(1.0, 8.0), 2)
    else:
        xt = round(random.uniform(10.0, 70.7), 2)
        xc = round(random.uniform(2.0, 10.9), 2)

    if mr1:
        mt = round(random.uniform(5.0, 127.6), 2)
        mc = round(random.uniform(1.0, 8.0), 2)
    else:
        mt = round(random.uniform(10.0, 299.7), 2)
        mc = round(random.uniform(2.0, 31.3), 2)

    if xr2:
        xr2t = round(random.uniform(5.0, 40.0), 2)
        xr2c = round(random.uniform(1.0, 9.0), 2)
    else:
        xr2t = round(random.uniform(10.0, 75.0), 2)
        xr2c = round(random.uniform(2.0, 11.0), 2)

    tc = random.randint(50, 250)
    pi = random.randint(1, 12) if xr1 else random.randint(3, 20)

    cases.append({
        'case_id': f'KCTF-{idx + 1:03d}',
        'subsystem': sub,
        'vuln_type': vt,
        'is_race': int(race),
        'commit_msg_level': cml,
        'pre_cutoff': pre_cutoff,
        'xhigh_run1_success': xr1,
        'xhigh_run1_time_min': xt,
        'xhigh_run1_cost_usd': xc,
        'xhigh_run1_tool_calls': tc,
        'xhigh_run1_poc_iterations': pi,
        'medium_run1_success': mr1,
        'medium_run1_time_min': mt,
        'medium_run1_cost_usd': mc,
        'xhigh_run2_success': xr2,
        'xhigh_run2_time_min': xr2t,
        'xhigh_run2_cost_usd': xr2c,
        'cheating_flag': 0,
    })

# ---------------------------------------------------------------
# Step 3: Mark 4 cheating cases (UAF_DF non-race with XHigh success)
# These represent cases where agents used GDB to cause artificial crashes
# ---------------------------------------------------------------
cheating_candidates = [i for i, c in enumerate(cases)
                       if c['vuln_type'] == 'uaf_df' and c['is_race'] == 0
                       and c['xhigh_run1_success'] == 1]
random.shuffle(cheating_candidates)
for i in cheating_candidates[:4]:
    cases[i]['cheating_flag'] = 1

# ---------------------------------------------------------------
# Step 4: Write CSV
# ---------------------------------------------------------------
fieldnames = list(cases[0].keys())
with open('/app/data/reproduction_results.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(cases)

# ---------------------------------------------------------------
# Step 5: Write data documentation
# ---------------------------------------------------------------
readme = """Vulnerability Reproduction Experiment Dataset
=============================================

This dataset contains results from automated LLM-based Linux kernel
vulnerability reproduction experiments on 100 KernelCTF cases.

Two model configurations were evaluated:
- "XHigh": LLM model with extended reasoning (high compute budget)
- "Medium": Same model family with standard reasoning budget

XHigh was run twice (run1, run2) to assess stability. Medium was run once.

Column Descriptions
-------------------
- case_id: Unique case identifier (KCTF-001 through KCTF-100)
- subsystem: Affected kernel subsystem (net, netfilter, bpf, other)
- vuln_type: Vulnerability classification
    uaf_df = use-after-free or double-free (temporal memory safety)
    oob = out-of-bounds access (spatial memory safety)
    other = other vulnerability types
- is_race: Whether the vulnerability requires a race condition to trigger (0/1)
- commit_msg_level: Information disclosure level of the patch commit message
    1 = No acknowledgment of a triggerable issue
    2 = Acknowledges issue but does not describe reproduction steps
    3 = Explicitly describes triggering steps
- pre_cutoff: Disclosed before the models' knowledge cutoff date (0/1)
- xhigh_run1_success: XHigh model run 1 reproduction result (0=fail, 1=success)
- xhigh_run1_time_min: XHigh run 1 execution time in minutes
- xhigh_run1_cost_usd: XHigh run 1 API cost in USD
- xhigh_run1_tool_calls: Number of tool invocations in XHigh run 1
- xhigh_run1_poc_iterations: Number of PoC compilation/upload attempts
- medium_run1_success: Medium model run 1 result (0=fail, 1=success)
- medium_run1_time_min: Medium run 1 execution time in minutes
- medium_run1_cost_usd: Medium run 1 API cost in USD
- xhigh_run2_success: XHigh model run 2 result (0/1)
- xhigh_run2_time_min: XHigh run 2 execution time in minutes
- xhigh_run2_cost_usd: XHigh run 2 API cost in USD
- cheating_flag: Whether the agent manipulated kernel state via GDB to cause
    an artificial crash rather than genuine vulnerability reproduction (0/1).
    These represent invalid reproduction results where the agent bypassed
    the intended task by directly modifying kernel memory or invoking kernel
    functions through the debugger to fabricate crash indicators.

Notes
-----
- All experiments used Syzbot-derived kernel configurations with KASAN enabled
- Each run had a maximum 10-hour time budget
- Internet access was disabled during PoC generation
- Kernel images were built at the commit immediately prior to the security patch
"""

with open('/app/data/README.txt', 'w') as f:
    f.write(readme)

# ---------------------------------------------------------------
# Step 6: Generate flawed preliminary analysis
# Contains intentional errors for the audit task:
# (a) Does not exclude cheating-flagged cases
# (b) Uses z-test approximation instead of Fisher's exact
# (c) Vulnerability type analysis is unstratified (ignores confounding)
# (d) Convergence intersection/union labels are swapped
# (e) Cutoff odds ratios are computed from inverted table
# ---------------------------------------------------------------

def approx_two_prop_pvalue(a, b, c, d):
    """Z-test approximation for 2x2 table (inappropriate for small samples)."""
    n1, n2 = a + b, c + d
    if n1 == 0 or n2 == 0:
        return 1.0
    p1 = a / n1
    p2 = c / n2
    p_hat = (a + c) / (n1 + n2)
    q_hat = 1 - p_hat
    if p_hat <= 0 or p_hat >= 1:
        return 1.0
    se = (p_hat * q_hat * (1.0 / n1 + 1.0 / n2)) ** 0.5
    if se < 1e-10:
        return 1.0
    z = abs(p1 - p2) / se
    p = math.erfc(z / 2 ** 0.5)
    return round(p, 4)


def naive_odds_ratio(a, b, c, d):
    """Simple odds ratio from 2x2 table."""
    if b * c == 0:
        return 999.9999
    return round((a * d) / (b * c), 4)


# Error (a): use ALL cases without excluding cheating
flawed = {}

flawed['data_summary'] = {
    'total_cases': len(cases),
    'effective_cases': len(cases),
    'excluded_cheating_cases': 0
}

# Overall performance on all 100 cases
flawed_perf = {}
for model, prefix, time_key, cost_key in [
    ('xhigh', 'xhigh_run1', 'xhigh_run1_time_min', 'xhigh_run1_cost_usd'),
    ('medium', 'medium_run1', 'medium_run1_time_min', 'medium_run1_cost_usd'),
]:
    success = [c for c in cases if c[prefix + '_success'] == 1]
    failure = [c for c in cases if c[prefix + '_success'] == 0]
    flawed_perf[model] = {
        'success_rate': round(len(success) / len(cases), 4),
        'mean_time_all_min': round(
            sum(c[time_key] for c in cases) / len(cases), 2),
        'mean_cost_all_usd': round(
            sum(c[cost_key] for c in cases) / len(cases), 2),
        'mean_time_success_min': round(
            sum(c[time_key] for c in success) / len(success), 2
        ) if success else None,
        'mean_cost_success_usd': round(
            sum(c[cost_key] for c in success) / len(success), 2
        ) if success else None,
        'mean_time_failure_min': round(
            sum(c[time_key] for c in failure) / len(failure), 2
        ) if failure else None,
        'mean_cost_failure_usd': round(
            sum(c[cost_key] for c in failure) / len(failure), 2
        ) if failure else None,
    }
flawed['overall_performance'] = flawed_perf

# Subsystem analysis: all cases, z-test approximation instead of Fisher's exact
subsystems_all = sorted(set(c['subsystem'] for c in cases))
flawed_sub = {}
for sub in subsystems_all:
    sub_c = [c for c in cases if c['subsystem'] == sub]
    rest_c = [c for c in cases if c['subsystem'] != sub]
    entry = {'count': len(sub_c)}
    for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
        a = sum(1 for c in sub_c if c[prefix + '_success'] == 1)
        b = len(sub_c) - a
        c_val = sum(1 for c in rest_c if c[prefix + '_success'] == 1)
        d = len(rest_c) - c_val
        entry[model + '_success_rate'] = round(a / len(sub_c), 4)
        entry[model + '_fisher_odds_ratio'] = naive_odds_ratio(a, b, c_val, d)
        # Error (b): z-test approximation, not Fisher's exact
        entry[model + '_fisher_pvalue'] = approx_two_prop_pvalue(a, b, c_val, d)
    flawed_sub[sub] = entry
flawed['subsystem_analysis'] = flawed_sub

# Race condition analysis on all cases
race_cases = [c for c in cases if c['is_race'] == 1]
non_race_cases = [c for c in cases if c['is_race'] == 0]
flawed_race = {
    'race_count': len(race_cases),
    'non_race_count': len(non_race_cases),
}
for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
    flawed_race[model + '_race_success_rate'] = round(
        sum(c[prefix + '_success'] for c in race_cases) / len(race_cases), 4)
    flawed_race[model + '_non_race_success_rate'] = round(
        sum(c[prefix + '_success'] for c in non_race_cases) / len(non_race_cases), 4)
flawed['race_condition_analysis'] = flawed_race

# Error (c): Vulnerability type analysis — unstratified, ignores race confounding
# Puts all counts in the "race" stratum and zeros in "non_race"
filtered_all = [c for c in cases if c['vuln_type'] in ('uaf_df', 'oob')]
flawed_vt = {
    'note': 'UAF_DF vs OOB comparison, excluding other vuln_type cases'
}
for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
    uaf_s = sum(1 for c in filtered_all
                if c['vuln_type'] == 'uaf_df' and c[prefix + '_success'] == 1)
    uaf_f = sum(1 for c in filtered_all
                if c['vuln_type'] == 'uaf_df' and c[prefix + '_success'] == 0)
    oob_s = sum(1 for c in filtered_all
                if c['vuln_type'] == 'oob' and c[prefix + '_success'] == 1)
    oob_f = sum(1 for c in filtered_all
                if c['vuln_type'] == 'oob' and c[prefix + '_success'] == 0)
    n_or = naive_odds_ratio(uaf_s, uaf_f, oob_s, oob_f)
    # Z-test chi-square statistic (wrong method)
    n1, n2 = uaf_s + uaf_f, oob_s + oob_f
    if n1 > 0 and n2 > 0:
        p1 = uaf_s / n1
        p2 = oob_s / n2
        p_hat = (uaf_s + oob_s) / (n1 + n2)
        q_hat = 1 - p_hat
        se = (p_hat * q_hat * (1.0 / n1 + 1.0 / n2)) ** 0.5 if 0 < p_hat < 1 else 1
        z_stat = (p1 - p2) / se if se > 0 else 0
        chi2 = round(z_stat ** 2, 4)
    else:
        chi2 = 0.0
    n_p = approx_two_prop_pvalue(uaf_s, uaf_f, oob_s, oob_f)
    flawed_vt[model] = {
        'pooled_odds_ratio': n_or,
        'test_statistic': chi2,
        'pvalue': n_p,
        'stratified_tables': {
            'race': {
                'uaf_df_success': uaf_s,
                'uaf_df_failure': uaf_f,
                'oob_success': oob_s,
                'oob_failure': oob_f
            },
            'non_race': {
                'uaf_df_success': 0,
                'uaf_df_failure': 0,
                'oob_success': 0,
                'oob_failure': 0
            }
        }
    }
flawed['vulnerability_type_analysis'] = flawed_vt

# Cutoff analysis: all cases, error (e): inverted table for odds ratio
pre_c = [c for c in cases if c['pre_cutoff'] == 1]
post_c = [c for c in cases if c['pre_cutoff'] == 0]
flawed_cutoff = {
    'pre_cutoff_count': len(pre_c),
    'post_cutoff_count': len(post_c),
}
for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
    pre_s = sum(1 for c in pre_c if c[prefix + '_success'] == 1)
    post_s = sum(1 for c in post_c if c[prefix + '_success'] == 1)
    flawed_cutoff[model + '_pre_success_rate'] = round(pre_s / len(pre_c), 4)
    flawed_cutoff[model + '_post_success_rate'] = round(post_s / len(post_c), 4)
    # Error (e): table rows inverted (post/pre instead of pre/post)
    a, b = post_s, len(post_c) - post_s
    c_v, d = pre_s, len(pre_c) - pre_s
    flawed_cutoff[model + '_fisher_odds_ratio'] = naive_odds_ratio(a, b, c_v, d)
    flawed_cutoff[model + '_fisher_pvalue'] = approx_two_prop_pvalue(a, b, c_v, d)
flawed['cutoff_analysis'] = flawed_cutoff

# Error (d): Convergence analysis — intersection/union labels swapped
r1 = sum(1 for c in cases if c['xhigh_run1_success'] == 1)
r2 = sum(1 for c in cases if c['xhigh_run2_success'] == 1)
both_correct = sum(1 for c in cases
                   if c['xhigh_run1_success'] == 1
                   and c['xhigh_run2_success'] == 1)
either_correct = sum(1 for c in cases
                     if c['xhigh_run1_success'] == 1
                     or c['xhigh_run2_success'] == 1)
only1 = r1 - both_correct
only2 = r2 - both_correct
flawed['convergence_analysis'] = {
    'xhigh_run1_success': r1,
    'xhigh_run2_success': r2,
    'both_runs_success': either_correct,  # SWAPPED: union labeled as intersection
    'either_run_success': both_correct,   # SWAPPED: intersection labeled as union
    'only_run1_success': only1,
    'only_run2_success': only2,
}

# Commit message analysis on all cases
flawed_cma = {}
for level in [1, 2, 3]:
    lc = [c for c in cases if c['commit_msg_level'] == level]
    flawed_cma['level_' + str(level)] = {
        'count': len(lc),
        'xhigh_success_rate': round(
            sum(c['xhigh_run1_success'] for c in lc) / len(lc), 4
        ) if lc else 0.0,
        'medium_success_rate': round(
            sum(c['medium_run1_success'] for c in lc) / len(lc), 4
        ) if lc else 0.0,
    }
flawed['commit_message_analysis'] = flawed_cma

with open('/app/data/preliminary_analysis.json', 'w') as f:
    json.dump(flawed, f, indent=2)

# ---------------------------------------------------------------
# Summary statistics for verification
# ---------------------------------------------------------------
n_cheat = sum(1 for c in cases if c['cheating_flag'] == 1)
effective = [c for c in cases if c['cheating_flag'] == 0]
print(f"Generated {len(cases)} cases ({n_cheat} cheating, {len(effective)} effective)")
print(f"XHigh run1 raw success: {sum(c['xhigh_run1_success'] for c in cases)}")
print(f"XHigh run1 clean success: {sum(c['xhigh_run1_success'] for c in effective)}")
print(f"Medium run1 clean success: {sum(c['medium_run1_success'] for c in effective)}")
print(f"Race conditions: {sum(c['is_race'] for c in effective)}")
print(f"Subsystems: { {s: sum(1 for c in effective if c['subsystem']==s) for s in ['net','netfilter','bpf','other']} }")
print(f"Vuln types: { {v: sum(1 for c in effective if c['vuln_type']==v) for v in ['uaf_df','oob','other']} }")
print("Generated flawed preliminary analysis at /app/data/preliminary_analysis.json")
