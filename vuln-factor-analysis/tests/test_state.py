#!/usr/bin/env python3
"""Tests for corrected vulnerability reproduction analysis.

Independently computes expected statistical results from the raw dataset
and verifies the agent's analysis.json matches within tolerance.

"""
import json
import csv
import os
import pytest
import numpy as np
from scipy.stats import fisher_exact
from statsmodels.stats.contingency_tables import StratifiedTable

DATA_PATH = '/app/data/reproduction_results.csv'
ANALYSIS_PATH = '/app/results/analysis.json'


def _load_raw():
    cases = []
    with open(DATA_PATH) as f:
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


@pytest.fixture(scope='module')
def raw_data():
    return _load_raw()


@pytest.fixture(scope='module')
def clean_data(raw_data):
    return [c for c in raw_data if c['cheating_flag'] == 0]


@pytest.fixture(scope='module')
def analysis():
    assert os.path.exists(ANALYSIS_PATH), \
        f"Output file not found at {ANALYSIS_PATH}"
    with open(ANALYSIS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "analysis.json must contain a JSON object"
    return data


# ======================================================================
# Structure Tests
# ======================================================================

class TestStructure:
    def test_required_sections(self, analysis):
        required = [
            'data_summary', 'overall_performance', 'subsystem_analysis',
            'race_condition_analysis', 'vulnerability_type_analysis',
            'cutoff_analysis', 'convergence_analysis',
            'commit_message_analysis'
        ]
        for section in required:
            assert section in analysis, f"Missing required section: {section}"


# ======================================================================
# Data Cleaning Tests
# ======================================================================

class TestDataCleaning:
    def test_total_cases(self, raw_data, analysis):
        expected = len(raw_data)
        actual = analysis['data_summary']['total_cases']
        assert actual == expected, \
            f"total_cases: expected {expected}, got {actual}"

    def test_cheating_excluded(self, raw_data, clean_data, analysis):
        expected = len(raw_data) - len(clean_data)
        actual = analysis['data_summary']['excluded_cheating_cases']
        assert actual == expected, \
            f"excluded_cheating_cases: expected {expected}, got {actual}"

    def test_effective_cases(self, clean_data, analysis):
        expected = len(clean_data)
        actual = analysis['data_summary']['effective_cases']
        assert actual == expected, \
            f"effective_cases: expected {expected}, got {actual}"


# ======================================================================
# Overall Performance Tests
# ======================================================================

class TestOverallPerformance:
    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_success_rate(self, clean_data, analysis, model, prefix):
        expected = sum(c[f'{prefix}_success'] for c in clean_data) / len(clean_data)
        actual = analysis['overall_performance'][model]['success_rate']
        assert abs(actual - expected) < 0.005, \
            f"{model} success_rate: expected {expected:.4f}, got {actual}"

    @pytest.mark.parametrize("model,time_key", [
        ("xhigh", "xhigh_run1_time_min"),
        ("medium", "medium_run1_time_min")
    ])
    def test_mean_time_all(self, clean_data, analysis, model, time_key):
        expected = sum(c[time_key] for c in clean_data) / len(clean_data)
        actual = analysis['overall_performance'][model]['mean_time_all_min']
        assert abs(actual - expected) < 1.0, \
            f"{model} mean_time_all: expected {expected:.2f}, got {actual}"

    @pytest.mark.parametrize("model,prefix,time_key", [
        ("xhigh", "xhigh_run1", "xhigh_run1_time_min"),
        ("medium", "medium_run1", "medium_run1_time_min")
    ])
    def test_mean_time_success(self, clean_data, analysis, model, prefix, time_key):
        success = [c for c in clean_data if c[f'{prefix}_success'] == 1]
        if not success:
            pytest.skip("No success cases")
        expected = sum(c[time_key] for c in success) / len(success)
        actual = analysis['overall_performance'][model]['mean_time_success_min']
        assert abs(actual - expected) < 1.0

    @pytest.mark.parametrize("model,prefix,cost_key", [
        ("xhigh", "xhigh_run1", "xhigh_run1_cost_usd"),
        ("medium", "medium_run1", "medium_run1_cost_usd")
    ])
    def test_mean_cost_all(self, clean_data, analysis, model, prefix, cost_key):
        expected = sum(c[cost_key] for c in clean_data) / len(clean_data)
        actual = analysis['overall_performance'][model]['mean_cost_all_usd']
        assert abs(actual - expected) < 0.5


# ======================================================================
# Subsystem Analysis Tests
# ======================================================================

class TestSubsystemAnalysis:
    def test_subsystem_counts(self, clean_data, analysis):
        for sub in set(c['subsystem'] for c in clean_data):
            expected = sum(1 for c in clean_data if c['subsystem'] == sub)
            actual = analysis['subsystem_analysis'][sub]['count']
            assert actual == expected, \
                f"Subsystem {sub} count: expected {expected}, got {actual}"

    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_subsystem_success_rates(self, clean_data, analysis, model, prefix):
        for sub in set(c['subsystem'] for c in clean_data):
            sub_cases = [c for c in clean_data if c['subsystem'] == sub]
            expected = sum(c[f'{prefix}_success'] for c in sub_cases) / len(sub_cases)
            actual = analysis['subsystem_analysis'][sub][f'{model}_success_rate']
            assert abs(actual - expected) < 0.005, \
                f"{sub} {model} rate: expected {expected:.4f}, got {actual}"

    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_subsystem_fisher_pvalues(self, clean_data, analysis, model, prefix):
        for sub in set(c['subsystem'] for c in clean_data):
            sub_c = [c for c in clean_data if c['subsystem'] == sub]
            rest_c = [c for c in clean_data if c['subsystem'] != sub]

            a = sum(1 for c in sub_c if c[f'{prefix}_success'] == 1)
            b = len(sub_c) - a
            c_v = sum(1 for c in rest_c if c[f'{prefix}_success'] == 1)
            d = len(rest_c) - c_v

            _, exp_p = fisher_exact([[a, b], [c_v, d]], alternative='two-sided')
            act_p = analysis['subsystem_analysis'][sub][f'{model}_fisher_pvalue']

            assert abs(act_p - exp_p) < 0.02, \
                f"{sub} {model} Fisher p: expected {exp_p:.4f}, got {act_p}"


# ======================================================================
# Race Condition Tests
# ======================================================================

class TestRaceCondition:
    def test_race_counts(self, clean_data, analysis):
        exp_race = sum(1 for c in clean_data if c['is_race'] == 1)
        exp_nr = sum(1 for c in clean_data if c['is_race'] == 0)
        assert analysis['race_condition_analysis']['race_count'] == exp_race
        assert analysis['race_condition_analysis']['non_race_count'] == exp_nr

    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_race_success_rates(self, clean_data, analysis, model, prefix):
        race = [c for c in clean_data if c['is_race'] == 1]
        non_race = [c for c in clean_data if c['is_race'] == 0]

        exp_race_r = sum(c[f'{prefix}_success'] for c in race) / len(race)
        exp_nr_r = sum(c[f'{prefix}_success'] for c in non_race) / len(non_race)

        rca = analysis['race_condition_analysis']
        assert abs(rca[f'{model}_race_success_rate'] - exp_race_r) < 0.005
        assert abs(rca[f'{model}_non_race_success_rate'] - exp_nr_r) < 0.005


# ======================================================================
# Vulnerability Type Stratified Analysis Tests
# ======================================================================

class TestVulnTypeAnalysis:
    def _compute_stratified(self, clean_data, success_key):
        filtered = [c for c in clean_data
                    if c['vuln_type'] in ('uaf_df', 'oob')]
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
        return float(mh_or), float(result.statistic), float(result.pvalue), strat_data

    @pytest.mark.parametrize("model,success_key", [
        ("xhigh", "xhigh_run1_success"),
        ("medium", "medium_run1_success")
    ])
    def test_stratified_table_counts(self, clean_data, analysis,
                                      model, success_key):
        _, _, _, exp_strat = self._compute_stratified(clean_data, success_key)
        act_strat = analysis['vulnerability_type_analysis'][model]['stratified_tables']

        for stratum in ['race', 'non_race']:
            for cell in ['uaf_df_success', 'uaf_df_failure',
                         'oob_success', 'oob_failure']:
                assert act_strat[stratum][cell] == exp_strat[stratum][cell], \
                    (f"{model} {stratum} {cell}: "
                     f"expected {exp_strat[stratum][cell]}, "
                     f"got {act_strat[stratum][cell]}")

    @pytest.mark.parametrize("model,success_key", [
        ("xhigh", "xhigh_run1_success"),
        ("medium", "medium_run1_success")
    ])
    def test_pooled_odds_ratio(self, clean_data, analysis, model, success_key):
        exp_or, _, _, _ = self._compute_stratified(clean_data, success_key)
        act_or = analysis['vulnerability_type_analysis'][model]['pooled_odds_ratio']

        if np.isinf(exp_or) or exp_or == 0:
            pytest.skip("Degenerate OR")

        rel_err = abs(act_or - exp_or) / max(abs(exp_or), 0.01)
        assert rel_err < 0.10, \
            f"{model} pooled OR: expected {exp_or:.4f}, got {act_or} (rel_err={rel_err:.3f})"

    @pytest.mark.parametrize("model,success_key", [
        ("xhigh", "xhigh_run1_success"),
        ("medium", "medium_run1_success")
    ])
    def test_pvalue(self, clean_data, analysis, model, success_key):
        _, _, exp_p, _ = self._compute_stratified(clean_data, success_key)
        act_p = analysis['vulnerability_type_analysis'][model]['pvalue']

        assert abs(act_p - exp_p) < 0.02, \
            f"{model} stratified p-value: expected {exp_p:.6f}, got {act_p}"

    @pytest.mark.parametrize("model,success_key", [
        ("xhigh", "xhigh_run1_success"),
        ("medium", "medium_run1_success")
    ])
    def test_statistic(self, clean_data, analysis, model, success_key):
        _, exp_stat, _, _ = self._compute_stratified(clean_data, success_key)
        act_stat = analysis['vulnerability_type_analysis'][model]['test_statistic']

        assert abs(act_stat - exp_stat) < 0.5, \
            f"{model} test stat: expected {exp_stat:.4f}, got {act_stat}"


# ======================================================================
# Cutoff Analysis Tests
# ======================================================================

class TestCutoffAnalysis:
    def test_cutoff_counts(self, clean_data, analysis):
        exp_pre = sum(1 for c in clean_data if c['pre_cutoff'] == 1)
        exp_post = sum(1 for c in clean_data if c['pre_cutoff'] == 0)
        assert analysis['cutoff_analysis']['pre_cutoff_count'] == exp_pre
        assert analysis['cutoff_analysis']['post_cutoff_count'] == exp_post

    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_cutoff_rates(self, clean_data, analysis, model, prefix):
        pre = [c for c in clean_data if c['pre_cutoff'] == 1]
        post = [c for c in clean_data if c['pre_cutoff'] == 0]

        exp_pre_r = sum(c[f'{prefix}_success'] for c in pre) / len(pre)
        exp_post_r = sum(c[f'{prefix}_success'] for c in post) / len(post)

        ca = analysis['cutoff_analysis']
        assert abs(ca[f'{model}_pre_success_rate'] - exp_pre_r) < 0.005
        assert abs(ca[f'{model}_post_success_rate'] - exp_post_r) < 0.005

    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_cutoff_fisher(self, clean_data, analysis, model, prefix):
        pre = [c for c in clean_data if c['pre_cutoff'] == 1]
        post = [c for c in clean_data if c['pre_cutoff'] == 0]

        pre_s = sum(1 for c in pre if c[f'{prefix}_success'] == 1)
        post_s = sum(1 for c in post if c[f'{prefix}_success'] == 1)

        _, exp_p = fisher_exact(
            [[pre_s, len(pre) - pre_s],
             [post_s, len(post) - post_s]],
            alternative='two-sided'
        )
        act_p = analysis['cutoff_analysis'][f'{model}_fisher_pvalue']
        assert abs(act_p - exp_p) < 0.02


# ======================================================================
# Convergence Analysis Tests
# ======================================================================

class TestConvergence:
    def test_convergence_counts(self, clean_data, analysis):
        r1 = sum(1 for c in clean_data if c['xhigh_run1_success'] == 1)
        r2 = sum(1 for c in clean_data if c['xhigh_run2_success'] == 1)
        both = sum(1 for c in clean_data
                   if c['xhigh_run1_success'] == 1
                   and c['xhigh_run2_success'] == 1)
        either = sum(1 for c in clean_data
                     if c['xhigh_run1_success'] == 1
                     or c['xhigh_run2_success'] == 1)
        only1 = sum(1 for c in clean_data
                    if c['xhigh_run1_success'] == 1
                    and c['xhigh_run2_success'] == 0)
        only2 = sum(1 for c in clean_data
                    if c['xhigh_run1_success'] == 0
                    and c['xhigh_run2_success'] == 1)

        conv = analysis['convergence_analysis']
        assert conv['xhigh_run1_success'] == r1, \
            f"run1: expected {r1}, got {conv['xhigh_run1_success']}"
        assert conv['xhigh_run2_success'] == r2
        assert conv['both_runs_success'] == both
        assert conv['either_run_success'] == either
        assert conv['only_run1_success'] == only1
        assert conv['only_run2_success'] == only2


# ======================================================================
# Commit Message Analysis Tests
# ======================================================================

class TestCommitMessage:
    def test_commit_message_counts(self, clean_data, analysis):
        for level in [1, 2, 3]:
            expected = sum(1 for c in clean_data
                          if c['commit_msg_level'] == level)
            actual = analysis['commit_message_analysis'][f'level_{level}']['count']
            assert actual == expected, \
                f"level_{level} count: expected {expected}, got {actual}"

    @pytest.mark.parametrize("model,prefix", [
        ("xhigh", "xhigh_run1"), ("medium", "medium_run1")
    ])
    def test_commit_message_rates(self, clean_data, analysis, model, prefix):
        for level in [1, 2, 3]:
            level_cases = [c for c in clean_data
                          if c['commit_msg_level'] == level]
            if not level_cases:
                continue
            expected = (sum(c[f'{prefix}_success'] for c in level_cases)
                        / len(level_cases))
            actual = analysis['commit_message_analysis'][f'level_{level}'][
                f'{model}_success_rate']
            assert abs(actual - expected) < 0.005, \
                (f"level_{level} {model} rate: "
                 f"expected {expected:.4f}, got {actual}")
