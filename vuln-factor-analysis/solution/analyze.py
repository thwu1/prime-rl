#!/usr/bin/env python3
"""Corrected vulnerability reproduction factor analysis.

Audits and corrects the flawed preliminary analysis by:
1. Excluding cheating-flagged cases (data integrity)
2. Using Fisher's exact test for small-sample comparisons
3. Using Mantel-Haenszel stratified analysis for confound-adjusted
   vulnerability type comparison (controlling for race conditions)
4. Fixing convergence set operations
5. Correcting cutoff odds ratio table orientation

"""
import csv
import json
import os
import numpy as np
from scipy.stats import fisher_exact
from statsmodels.stats.contingency_tables import StratifiedTable


def load_data(path):
    """Load CSV dataset and convert types."""
    cases = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k in ['is_race', 'pre_cutoff', 'xhigh_run1_success',
                       'medium_run1_success', 'xhigh_run2_success',
                       'commit_msg_level', 'cheating_flag',
                       'xhigh_run1_tool_calls', 'xhigh_run1_poc_iterations']:
                row[k] = int(row[k])
            for k in ['xhigh_run1_time_min', 'xhigh_run1_cost_usd',
                       'medium_run1_time_min', 'medium_run1_cost_usd',
                       'xhigh_run2_time_min', 'xhigh_run2_cost_usd']:
                row[k] = float(row[k])
            cases.append(row)
    return cases


def fisher_subsystem(cases, subsystem, success_key):
    """Fisher's exact test: one subsystem vs all others."""
    sub = [c for c in cases if c['subsystem'] == subsystem]
    rest = [c for c in cases if c['subsystem'] != subsystem]

    a = sum(1 for c in sub if c[success_key] == 1)
    b = len(sub) - a
    c_val = sum(1 for c in rest if c[success_key] == 1)
    d = len(rest) - c_val

    odds_ratio, p_value = fisher_exact([[a, b], [c_val, d]],
                                        alternative='two-sided')
    return float(odds_ratio), float(p_value)


def stratified_analysis(cases, success_key):
    """Stratified analysis comparing UAF_DF vs OOB, controlling for race."""
    filtered = [c for c in cases if c['vuln_type'] in ('uaf_df', 'oob')]

    tables = []
    strat_data = {}

    for race_val, race_name in [(1, 'race'), (0, 'non_race')]:
        stratum = [c for c in filtered if c['is_race'] == race_val]

        a = sum(1 for c in stratum
                if c['vuln_type'] == 'uaf_df' and c[success_key] == 1)
        b = sum(1 for c in stratum
                if c['vuln_type'] == 'uaf_df' and c[success_key] == 0)
        c_v = sum(1 for c in stratum
                  if c['vuln_type'] == 'oob' and c[success_key] == 1)
        d = sum(1 for c in stratum
                if c['vuln_type'] == 'oob' and c[success_key] == 0)

        strat_data[race_name] = {
            'uaf_df_success': a, 'uaf_df_failure': b,
            'oob_success': c_v, 'oob_failure': d
        }
        tables.append(np.array([[a, b], [c_v, d]]))

    st = StratifiedTable(tables)
    result = st.test_null_odds()
    mh_or = st.oddsratio_pooled

    return {
        'pooled_odds_ratio': round(float(mh_or), 4),
        'test_statistic': round(float(result.statistic), 4),
        'pvalue': round(float(result.pvalue), 6),
        'stratified_tables': strat_data
    }


def main():
    data_path = '/app/data/reproduction_results.csv'
    output_path = '/app/results/analysis.json'

    all_cases = load_data(data_path)

    # --- Data Cleaning: exclude cheating-flagged cases ---
    cheating_count = sum(1 for c in all_cases if c['cheating_flag'] == 1)
    cases = [c for c in all_cases if c['cheating_flag'] == 0]

    result = {
        'data_summary': {
            'total_cases': len(all_cases),
            'effective_cases': len(cases),
            'excluded_cheating_cases': cheating_count
        }
    }

    # --- Overall Performance ---
    perf = {}
    for model, prefix, time_key, cost_key in [
        ('xhigh', 'xhigh_run1', 'xhigh_run1_time_min', 'xhigh_run1_cost_usd'),
        ('medium', 'medium_run1', 'medium_run1_time_min', 'medium_run1_cost_usd'),
    ]:
        success = [c for c in cases if c[f'{prefix}_success'] == 1]
        failure = [c for c in cases if c[f'{prefix}_success'] == 0]

        perf[model] = {
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
    result['overall_performance'] = perf

    # --- Subsystem Analysis with Fisher's exact test ---
    subsystems = sorted(set(c['subsystem'] for c in cases))
    sub_analysis = {}
    for sub in subsystems:
        sub_cases = [c for c in cases if c['subsystem'] == sub]
        entry = {'count': len(sub_cases)}

        for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
            n_success = sum(1 for c in sub_cases if c[f'{prefix}_success'] == 1)
            entry[f'{model}_success_rate'] = round(n_success / len(sub_cases), 4)

            or_val, p_val = fisher_subsystem(cases, sub, f'{prefix}_success')
            entry[f'{model}_fisher_odds_ratio'] = round(or_val, 4)
            entry[f'{model}_fisher_pvalue'] = round(p_val, 4)

        sub_analysis[sub] = entry
    result['subsystem_analysis'] = sub_analysis

    # --- Race Condition Analysis ---
    race = [c for c in cases if c['is_race'] == 1]
    non_race = [c for c in cases if c['is_race'] == 0]

    race_analysis = {
        'race_count': len(race),
        'non_race_count': len(non_race),
    }
    for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
        race_analysis[f'{model}_race_success_rate'] = round(
            sum(c[f'{prefix}_success'] for c in race) / len(race), 4
        ) if race else 0.0
        race_analysis[f'{model}_non_race_success_rate'] = round(
            sum(c[f'{prefix}_success'] for c in non_race) / len(non_race), 4
        ) if non_race else 0.0
    result['race_condition_analysis'] = race_analysis

    # --- Vulnerability Type: Stratified Analysis controlling for race ---
    result['vulnerability_type_analysis'] = {
        'note': ('UAF_DF vs OOB comparison, stratified by race condition, '
                 'excluding other vuln_type cases'),
        'xhigh': stratified_analysis(cases, 'xhigh_run1_success'),
        'medium': stratified_analysis(cases, 'medium_run1_success'),
    }

    # --- Cutoff Analysis ---
    pre = [c for c in cases if c['pre_cutoff'] == 1]
    post = [c for c in cases if c['pre_cutoff'] == 0]

    cutoff = {
        'pre_cutoff_count': len(pre),
        'post_cutoff_count': len(post),
    }
    for model, prefix in [('xhigh', 'xhigh_run1'), ('medium', 'medium_run1')]:
        pre_s = sum(1 for c in pre if c[f'{prefix}_success'] == 1)
        post_s = sum(1 for c in post if c[f'{prefix}_success'] == 1)

        cutoff[f'{model}_pre_success_rate'] = round(
            pre_s / len(pre), 4) if pre else 0.0
        cutoff[f'{model}_post_success_rate'] = round(
            post_s / len(post), 4) if post else 0.0

        table = [[pre_s, len(pre) - pre_s],
                 [post_s, len(post) - post_s]]
        or_val, p_val = fisher_exact(table, alternative='two-sided')
        cutoff[f'{model}_fisher_odds_ratio'] = round(float(or_val), 4)
        cutoff[f'{model}_fisher_pvalue'] = round(float(p_val), 4)
    result['cutoff_analysis'] = cutoff

    # --- Convergence Analysis ---
    r1 = sum(1 for c in cases if c['xhigh_run1_success'] == 1)
    r2 = sum(1 for c in cases if c['xhigh_run2_success'] == 1)
    both = sum(1 for c in cases
               if c['xhigh_run1_success'] == 1 and c['xhigh_run2_success'] == 1)
    either = sum(1 for c in cases
                 if c['xhigh_run1_success'] == 1 or c['xhigh_run2_success'] == 1)
    only1 = sum(1 for c in cases
                if c['xhigh_run1_success'] == 1 and c['xhigh_run2_success'] == 0)
    only2 = sum(1 for c in cases
                if c['xhigh_run1_success'] == 0 and c['xhigh_run2_success'] == 1)

    result['convergence_analysis'] = {
        'xhigh_run1_success': r1,
        'xhigh_run2_success': r2,
        'both_runs_success': both,
        'either_run_success': either,
        'only_run1_success': only1,
        'only_run2_success': only2,
    }

    # --- Commit Message Analysis ---
    cma = {}
    for level in [1, 2, 3]:
        level_cases = [c for c in cases if c['commit_msg_level'] == level]
        cma[f'level_{level}'] = {
            'count': len(level_cases),
            'xhigh_success_rate': round(
                sum(c['xhigh_run1_success'] for c in level_cases)
                / len(level_cases), 4
            ) if level_cases else 0.0,
            'medium_success_rate': round(
                sum(c['medium_run1_success'] for c in level_cases)
                / len(level_cases), 4
            ) if level_cases else 0.0,
        }
    result['commit_message_analysis'] = cma

    # --- Write Output ---
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Corrected analysis written to {output_path}")


if __name__ == '__main__':
    main()
