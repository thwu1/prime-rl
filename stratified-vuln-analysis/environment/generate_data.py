#!/usr/bin/env python3
"""Deterministic generator for vulnerability reproduction experiment dataset
and a flawed draft analysis for audit purposes.

Produces 100 synthetic kernel vulnerability reproduction records with
attributes and binary outcomes across six experimental configurations,
plus a deliberately flawed draft analysis containing methodological errors.
"""

import json
import math
import os
import random

SEED = 42


def chi2_pvalue_1df(stat):
    """P-value for chi-squared test with 1 degree of freedom (pure Python)."""
    if stat <= 0:
        return 1.0
    return math.erfc(math.sqrt(stat / 2))


def chi2_2x2(a, b, c, d):
    """Chi-squared statistic for 2x2 contingency table."""
    n = a + b + c + d
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom == 0:
        return 0.0
    return n * (a * d - b * c) ** 2 / denom


def r4(x):
    return round(float(x), 4)


def generate_cases():
    random.seed(SEED)

    subsystem_pool = (
        ['net'] * 45 + ['netfilter'] * 30 + ['bpf'] * 10 + ['other'] * 15
    )
    type_pool = ['uaf_df'] * 75 + ['oob'] * 20 + ['other'] * 5

    random.shuffle(subsystem_pool)
    random.shuffle(type_pool)

    cases = []
    for i in range(100):
        vtype = type_pool[i]
        sub = subsystem_pool[i]

        race_prob = {'uaf_df': 0.24, 'oob': 0.20, 'other': 0.20}[vtype]
        is_race = random.random() < race_prob

        commit_level = random.choices([1, 2, 3], weights=[13, 79, 8])[0]
        is_post_cutoff = random.random() < 0.42

        p = 0.58
        if is_race:
            p -= 0.30
        if vtype == 'uaf_df':
            p -= 0.08
        elif vtype == 'oob':
            p += 0.18
        if commit_level == 3:
            p += 0.15
        elif commit_level == 1:
            p -= 0.12
        p = max(0.05, min(0.95, p))

        baseline = random.random() < p
        run2 = random.random() < (p * 0.94)

        gdb_used = random.random() < 0.62
        cheating = gdb_used and (random.random() < 0.065)
        if cheating and not baseline:
            baseline = True

        no_gdb = random.random() < (p * 0.98)
        no_util = random.random() < (p * 0.85)
        degraded = random.random() < (p * 0.92)
        no_cmsg = random.random() < (p * 0.70)

        poc_iters = max(1, int(random.gauss(4.9 if baseline else 7.4, 3.0)))
        src_calls = max(0, int(random.gauss(40.5, 15)))
        vm_calls = max(0, int(random.gauss(55.5, 20)))
        bp_hit = gdb_used and (random.random() < 0.95)

        time_min = max(
            1.0,
            random.gauss(
                11.9 if baseline else 28.8,
                8.0 if baseline else 15.0
            )
        )
        cost_usd = max(
            0.5,
            random.gauss(
                2.49 if baseline else 5.96,
                1.5 if baseline else 2.5
            )
        )

        cases.append({
            "id": f"VULN-{i + 1:03d}",
            "subsystem": sub,
            "vuln_type": vtype,
            "is_race_condition": is_race,
            "commit_msg_level": commit_level,
            "is_post_cutoff": is_post_cutoff,
            "baseline_run1_success": baseline,
            "baseline_run2_success": run2,
            "no_gdb_success": no_gdb,
            "no_utilities_success": no_util,
            "degraded_prompt_success": degraded,
            "no_commit_msg_success": no_cmsg,
            "cheating_detected": cheating,
            "poc_iterations": poc_iters,
            "gdb_breakpoints_set": gdb_used,
            "gdb_breakpoints_hit": bp_hit,
            "source_browse_calls": src_calls,
            "vm_interaction_calls": vm_calls,
            "time_minutes": round(time_min, 2),
            "cost_usd": round(cost_usd, 2)
        })

    for case in cases:
        if not case['baseline_run1_success'] and not case['baseline_run2_success']:
            p3 = 0.58
            if case['is_race_condition']:
                p3 -= 0.30
            if case['vuln_type'] == 'uaf_df':
                p3 -= 0.08
            elif case['vuln_type'] == 'oob':
                p3 += 0.18
            p3 = max(0.05, min(0.95, p3))
            case['baseline_run3_success'] = random.random() < (p3 * 0.45)
        else:
            case['baseline_run3_success'] = None

    return cases


def generate_draft(cases):
    """Generate a flawed draft analysis with intentional methodological errors.

    Errors embedded:
    1. cheating_detected flag ignored — cheating cases counted as successes
    2. Chi-squared test used everywhere instead of exact tests
    3. Vulnerability type comparison unstratified (confounders ignored)
    4. Configuration comparisons use unpaired independence test
    5. All vulnerability types included (rare 'other' not excluded)
    """
    n = len(cases)
    draft = {}

    # ERROR: No cheating adjustment in success rates
    configs = {
        'baseline_run1': 'baseline_run1_success',
        'baseline_run2': 'baseline_run2_success',
        'no_gdb': 'no_gdb_success',
        'no_utilities': 'no_utilities_success',
        'degraded_prompt': 'degraded_prompt_success',
        'no_commit_msg': 'no_commit_msg_success',
    }
    rates = {}
    for name, field in configs.items():
        rates[name] = r4(sum(1 for d in cases if d[field]) / n)
    draft['overall_success_rates'] = rates

    # ERROR: Chi-squared instead of exact test, no cheating adjustment
    race_s = sum(1 for d in cases
                 if d['is_race_condition'] and d['baseline_run1_success'])
    race_f = sum(1 for d in cases
                 if d['is_race_condition'] and not d['baseline_run1_success'])
    nr_s = sum(1 for d in cases
               if not d['is_race_condition'] and d['baseline_run1_success'])
    nr_f = sum(1 for d in cases
               if not d['is_race_condition'] and not d['baseline_run1_success'])

    n_race = race_s + race_f
    n_nr = nr_s + nr_f
    stat = chi2_2x2(race_s, race_f, nr_s, nr_f)
    p = chi2_pvalue_1df(stat)
    or_val = (race_s * nr_f) / (race_f * nr_s) if race_f * nr_s > 0 else 0.0

    draft['race_condition_analysis'] = {
        'race_success_rate': r4(race_s / n_race) if n_race > 0 else 0.0,
        'nonrace_success_rate': r4(nr_s / n_nr) if n_nr > 0 else 0.0,
        'odds_ratio': r4(or_val),
        'p_value': r4(p),
    }

    # ERROR: No stratification, includes 'other', includes cheating, chi-squared
    uaf_s = sum(1 for d in cases
                if d['vuln_type'] == 'uaf_df' and d['baseline_run1_success'])
    uaf_f = sum(1 for d in cases
                if d['vuln_type'] == 'uaf_df' and not d['baseline_run1_success'])
    oob_s = sum(1 for d in cases
                if d['vuln_type'] == 'oob' and d['baseline_run1_success'])
    oob_f = sum(1 for d in cases
                if d['vuln_type'] == 'oob' and not d['baseline_run1_success'])

    crude_or = (uaf_s * oob_f) / (uaf_f * oob_s) if uaf_f * oob_s > 0 else 0.0
    stat_vt = chi2_2x2(uaf_s, uaf_f, oob_s, oob_f)
    p_vt = chi2_pvalue_1df(stat_vt)

    draft['vuln_type_analysis'] = {
        'odds_ratio': r4(crude_or),
        'p_value': r4(p_vt),
    }

    # ERROR: Unpaired chi-squared, includes cheating cases
    config_tests = {}
    for name, field in [('no_gdb', 'no_gdb_success'),
                         ('no_utilities', 'no_utilities_success'),
                         ('degraded_prompt', 'degraded_prompt_success'),
                         ('no_commit_msg', 'no_commit_msg_success')]:
        a = sum(1 for d in cases if d['baseline_run1_success'] and d[field])
        b = sum(1 for d in cases if d['baseline_run1_success'] and not d[field])
        c = sum(1 for d in cases if not d['baseline_run1_success'] and d[field])
        dd = sum(1 for d in cases
                 if not d['baseline_run1_success'] and not d[field])
        stat_ct = chi2_2x2(a, b, c, dd)
        p_ct = chi2_pvalue_1df(stat_ct)
        config_tests[f'baseline_vs_{name}'] = {
            'statistic': r4(stat_ct),
            'p_value': r4(p_ct),
        }
    draft['config_comparison_tests'] = config_tests

    # ERROR: No cheating adjustment in convergence
    r1_ids = {d['id'] for d in cases if d['baseline_run1_success']}
    r2_ids = {d['id'] for d in cases if d['baseline_run2_success']}
    r3_ids = {d['id'] for d in cases
              if d.get('baseline_run3_success') is True}
    u12 = r1_ids | r2_ids
    u123 = u12 | r3_ids

    draft['convergence_analysis'] = {
        'run1_successes': len(r1_ids),
        'run2_successes': len(r2_ids),
        'union_2_runs': len(u12),
        'union_rate_2_runs': r4(len(u12) / n),
        'run3_additional': len(r3_ids - u12),
        'union_rate_3_runs': r4(len(u123) / n),
    }

    # ERROR: No cheating adjustment, chi-squared
    pre = [d for d in cases if not d['is_post_cutoff']]
    post = [d for d in cases if d['is_post_cutoff']]
    pre_s = sum(1 for d in pre if d['baseline_run1_success'])
    post_s = sum(1 for d in post if d['baseline_run1_success'])
    pre_f = len(pre) - pre_s
    post_f = len(post) - post_s

    or_cut = (pre_s * post_f) / (pre_f * post_s) if pre_f * post_s > 0 else 0.0
    stat_cut = chi2_2x2(pre_s, pre_f, post_s, post_f)
    p_cut = chi2_pvalue_1df(stat_cut)

    draft['cutoff_analysis'] = {
        'pre_cutoff_rate': r4(pre_s / len(pre)) if pre else 0.0,
        'post_cutoff_rate': r4(post_s / len(post)) if post else 0.0,
        'odds_ratio': r4(or_cut),
        'p_value': r4(p_cut),
    }

    # ERROR: No cheating adjustment, chi-squared
    subsystems = sorted({d['subsystem'] for d in cases})
    sub_results = {}
    for sub in subsystems:
        sub_cases = [d for d in cases if d['subsystem'] == sub]
        sub_s = sum(1 for d in sub_cases if d['baseline_run1_success'])
        sub_f = len(sub_cases) - sub_s
        rest_s = sum(1 for d in cases
                     if d['subsystem'] != sub and d['baseline_run1_success'])
        rest_f = sum(1 for d in cases
                     if d['subsystem'] != sub
                     and not d['baseline_run1_success'])
        or_sub = ((sub_s * rest_f) / (sub_f * rest_s)
                  if sub_f * rest_s > 0 else 0.0)
        stat_sub = chi2_2x2(sub_s, sub_f, rest_s, rest_f)
        p_sub = chi2_pvalue_1df(stat_sub)
        sub_results[sub] = {
            'n': len(sub_cases),
            'success_rate': r4(sub_s / len(sub_cases)) if sub_cases else 0.0,
            'odds_ratio': r4(or_sub),
            'p_value': r4(p_sub),
        }
    draft['subsystem_analysis'] = sub_results

    # ERROR: No cheating adjustment
    cm_results = {}
    for level in [1, 2, 3]:
        lvl_cases = [d for d in cases if d['commit_msg_level'] == level]
        lvl_s = sum(1 for d in lvl_cases if d['baseline_run1_success'])
        cm_results[str(level)] = {
            'n': len(lvl_cases),
            'success_rate': (r4(lvl_s / len(lvl_cases))
                             if lvl_cases else 0.0),
        }
    draft['commit_msg_analysis'] = cm_results

    return draft


def generate_methodology():
    """Generate the draft methodology notes documenting the flawed methods."""
    return """# Draft Analysis Methodology

## Data Handling
- All 100 records included in every analysis without exclusions
- Success determined directly from boolean outcome fields
- The `cheating_detected` field was noted in the dataset but its implications
  for analysis validity were not assessed; no adjustments were made

## Group Comparisons (Race Condition, Cutoff, Subsystem)
- Chi-squared test of independence used for all between-group comparisons
- Odds ratios computed from 2x2 contingency tables

## Vulnerability Type Analysis
- Direct comparison of UAF/DF vs OOB success rates using chi-squared test
- All records included regardless of vulnerability type category size
- No control variables or stratification applied

## Configuration Comparisons
- Each alternative configuration compared to baseline using chi-squared
  test of independence on the full 2x2 table of (baseline x config) outcomes
- All records included in each comparison

## Convergence Analysis
- Run counts computed directly from success fields
- Union sets computed using set operations on case IDs

## Notes
- Race-condition status was analyzed as an independent factor but was
  not considered as a potential confounder in other analyses
- Sample sizes were not assessed for test validity assumptions
"""


if __name__ == '__main__':
    cases = generate_cases()
    os.makedirs('/app/data', exist_ok=True)

    with open('/app/data/experiments.json', 'w') as f:
        json.dump(cases, f, indent=2)

    draft = generate_draft(cases)
    with open('/app/data/draft_analysis.json', 'w') as f:
        json.dump(draft, f, indent=2)

    with open('/app/data/draft_methodology.md', 'w') as f:
        f.write(generate_methodology())

    # Print summary
    n = len(cases)
    n_race = sum(1 for c in cases if c['is_race_condition'])
    n_cheat = sum(1 for c in cases if c['cheating_detected'])
    n_succ = sum(1 for c in cases
                 if c['baseline_run1_success'] and not c['cheating_detected'])
    types = {}
    for c in cases:
        types[c['vuln_type']] = types.get(c['vuln_type'], 0) + 1
    subs = {}
    for c in cases:
        subs[c['subsystem']] = subs.get(c['subsystem'], 0) + 1

    print(f"Generated {n} experiment records")
    print(f"  Types: {types}")
    print(f"  Subsystems: {subs}")
    print(f"  Race conditions: {n_race}")
    print(f"  Cheating detected: {n_cheat}")
    print(f"  Baseline success (clean): {n_succ}/{n} = {n_succ/n:.1%}")
    print(f"Generated draft analysis with methodological errors")
    print(f"Generated draft methodology notes")
