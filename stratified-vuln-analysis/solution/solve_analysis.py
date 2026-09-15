#!/usr/bin/env python3
"""Reference solution: audit and correct the flawed draft analysis of
vulnerability reproduction experiments.

Identifies methodological errors in the draft and produces corrected
results using appropriate statistical methods.

"""

import json
import os

import numpy as np
from scipy.stats import binomtest, chi2, fisher_exact
from statsmodels.stats.contingency_tables import StratifiedTable


def load_data():
    with open('/app/data/experiments.json') as f:
        return json.load(f)


def r4(x):
    """Round to 4 decimal places, handling None."""
    if x is None:
        return None
    return round(float(x), 4)


def eff_baseline(d):
    """Effective baseline run1 success: cheating cases are failures."""
    return d['baseline_run1_success'] and not d['cheating_detected']


def paired_binary_test(b, c):
    """Paired test for matched binary outcomes using discordant pairs.

    Parameters
    ----------
    b : int
        Discordant pairs where baseline=success, config=failure.
    c : int
        Discordant pairs where baseline=failure, config=success.

    Returns
    -------
    dict with 'statistic' (None if exact) and 'p_value'.
    """
    if b + c == 0:
        return {'statistic': None, 'p_value': 1.0}
    if b + c < 25:
        result = binomtest(min(b, c), b + c, 0.5)
        return {'statistic': None, 'p_value': r4(result.pvalue)}
    else:
        stat = (b - c) ** 2 / (b + c)
        p = 1.0 - chi2.cdf(stat, 1)
        return {'statistic': r4(stat), 'p_value': r4(p)}


def main():
    data = load_data()
    n = len(data)
    results = {}

    # ---------------------------------------------------------------
    # 1. Overall success rates — correcting for cheating
    # ---------------------------------------------------------------
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
        if name.startswith('baseline'):
            successes = sum(
                1 for d in data
                if d[field] and not d['cheating_detected']
            )
        else:
            successes = sum(1 for d in data if d[field])
        rates[name] = r4(successes / n)
    results['overall_success_rates'] = rates

    # ---------------------------------------------------------------
    # 2. Race condition analysis — exact test with cheating adjustment
    # ---------------------------------------------------------------
    race_s = sum(1 for d in data
                 if d['is_race_condition'] and eff_baseline(d))
    race_f = sum(1 for d in data
                 if d['is_race_condition'] and not eff_baseline(d))
    nr_s = sum(1 for d in data
               if not d['is_race_condition'] and eff_baseline(d))
    nr_f = sum(1 for d in data
               if not d['is_race_condition'] and not eff_baseline(d))

    n_race = race_s + race_f
    n_nr = nr_s + nr_f
    or_race, p_race = fisher_exact([[race_s, race_f], [nr_s, nr_f]])

    results['race_condition_analysis'] = {
        'race_success_rate': r4(race_s / n_race) if n_race > 0 else 0.0,
        'nonrace_success_rate': r4(nr_s / n_nr) if n_nr > 0 else 0.0,
        'odds_ratio': r4(or_race),
        'p_value': r4(p_race),
    }

    # ---------------------------------------------------------------
    # 3. Vulnerability type analysis — controlling for confounders
    # ---------------------------------------------------------------
    filt = [d for d in data
            if d['vuln_type'] in ('uaf_df', 'oob')
            and not d['cheating_detected']]

    # Build stratum-specific 2x2 tables (stratified by race condition)
    strata_tables = []
    for race_val in [True, False]:
        stratum = [d for d in filt if d['is_race_condition'] == race_val]
        a = sum(1 for d in stratum
                if d['vuln_type'] == 'uaf_df' and d['baseline_run1_success'])
        b = sum(1 for d in stratum
                if d['vuln_type'] == 'uaf_df' and not d['baseline_run1_success'])
        c = sum(1 for d in stratum
                if d['vuln_type'] == 'oob' and d['baseline_run1_success'])
        dd = sum(1 for d in stratum
                 if d['vuln_type'] == 'oob' and not d['baseline_run1_success'])
        strata_tables.append(np.array([[a, b], [c, dd]]))

    st = StratifiedTable(strata_tables)
    adj_or = st.oddsratio_pooled
    assoc_test = st.test_null_odds()

    try:
        homog = st.test_equal_odds()
        homog_stat = float(homog.statistic)
        homog_p = float(homog.pvalue)
    except Exception:
        homog_stat = 0.0
        homog_p = 1.0

    results['vuln_type_analysis'] = {
        'odds_ratio': r4(adj_or),
        'p_value': r4(assoc_test.pvalue),
        'test_statistic': r4(assoc_test.statistic),
        'consistency_statistic': r4(homog_stat),
        'consistency_p_value': r4(homog_p),
    }

    # ---------------------------------------------------------------
    # 4. Configuration comparison tests — using matched-pair analysis
    # ---------------------------------------------------------------
    clean = [d for d in data if not d['cheating_detected']]

    comparison_results = {}
    comparison_configs = {
        'baseline_run2': 'baseline_run2_success',
        'no_gdb': 'no_gdb_success',
        'no_utilities': 'no_utilities_success',
        'degraded_prompt': 'degraded_prompt_success',
        'no_commit_msg': 'no_commit_msg_success',
    }

    for name, field in comparison_configs.items():
        b = sum(1 for d in clean
                if d['baseline_run1_success'] and not d[field])
        c = sum(1 for d in clean
                if not d['baseline_run1_success'] and d[field])
        comparison_results[f'baseline_vs_{name}'] = paired_binary_test(b, c)

    results['config_comparison_tests'] = comparison_results

    # ---------------------------------------------------------------
    # 5. Convergence analysis — with cheating adjustment
    # ---------------------------------------------------------------
    r1_set = {d['id'] for d in data if eff_baseline(d)}
    r2_set = {d['id'] for d in data if d['baseline_run2_success']}
    r3_set = {d['id'] for d in data
              if d.get('baseline_run3_success') is True}

    union_12 = r1_set | r2_set
    union_123 = union_12 | r3_set

    results['convergence_analysis'] = {
        'run1_successes': len(r1_set),
        'run2_successes': len(r2_set),
        'union_2_runs': len(union_12),
        'union_rate_2_runs': r4(len(union_12) / n),
        'run3_additional': len(r3_set - union_12),
        'union_rate_3_runs': r4(len(union_123) / n),
    }

    # ---------------------------------------------------------------
    # 6. Knowledge cutoff analysis — exact test with cheating adj.
    # ---------------------------------------------------------------
    pre = [d for d in data if not d['is_post_cutoff']]
    post = [d for d in data if d['is_post_cutoff']]

    pre_s = sum(1 for d in pre if eff_baseline(d))
    pre_f = len(pre) - pre_s
    post_s = sum(1 for d in post if eff_baseline(d))
    post_f = len(post) - post_s

    or_cut, p_cut = fisher_exact([[pre_s, pre_f], [post_s, post_f]])

    results['cutoff_analysis'] = {
        'pre_cutoff_rate': r4(pre_s / len(pre)) if pre else 0.0,
        'post_cutoff_rate': r4(post_s / len(post)) if post else 0.0,
        'odds_ratio': r4(or_cut),
        'p_value': r4(p_cut),
    }

    # ---------------------------------------------------------------
    # 7. Subsystem analysis — exact test vs rest, cheating adj.
    # ---------------------------------------------------------------
    subsystems = sorted({d['subsystem'] for d in data})
    sub_results = {}
    for sub in subsystems:
        sub_cases = [d for d in data if d['subsystem'] == sub]
        sub_s = sum(1 for d in sub_cases if eff_baseline(d))
        sub_f = len(sub_cases) - sub_s
        rest_s = sum(1 for d in data
                     if d['subsystem'] != sub and eff_baseline(d))
        rest_f = sum(1 for d in data
                     if d['subsystem'] != sub and not eff_baseline(d))

        or_sub, p_sub = fisher_exact([[sub_s, sub_f], [rest_s, rest_f]])
        sub_results[sub] = {
            'n': len(sub_cases),
            'success_rate': r4(sub_s / len(sub_cases)) if sub_cases else 0.0,
            'odds_ratio': r4(or_sub),
            'p_value': r4(p_sub),
        }
    results['subsystem_analysis'] = sub_results

    # ---------------------------------------------------------------
    # 8. Commit message level analysis — cheating adjusted
    # ---------------------------------------------------------------
    cm_results = {}
    for level in [1, 2, 3]:
        lvl_cases = [d for d in data if d['commit_msg_level'] == level]
        lvl_s = sum(1 for d in lvl_cases if eff_baseline(d))
        cm_results[str(level)] = {
            'n': len(lvl_cases),
            'success_rate': r4(lvl_s / len(lvl_cases)) if lvl_cases else 0.0,
        }
    results['commit_msg_analysis'] = cm_results

    # ---------------------------------------------------------------
    # Write output
    # ---------------------------------------------------------------
    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/analysis.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Corrected analysis written to /app/results/analysis.json")


if __name__ == '__main__':
    main()
