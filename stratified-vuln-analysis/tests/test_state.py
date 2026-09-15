"""Verification tests for vulnerability reproduction statistical analysis.

Independently recomputes key statistics from the raw dataset and compares
against the agent's output in /app/results/analysis.json.

"""

import json
import os

import numpy as np
import pytest
from scipy.stats import chi2, fisher_exact
from statsmodels.stats.contingency_tables import StratifiedTable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_data():
    with open('/app/data/experiments.json') as f:
        return json.load(f)


def load_results():
    assert os.path.exists('/app/results/analysis.json'), \
        "Results file not found at /app/results/analysis.json"
    with open('/app/results/analysis.json') as f:
        return json.load(f)


def eff_baseline(d):
    """Effective baseline run1 success (cheating = failure)."""
    return d['baseline_run1_success'] and not d['cheating_detected']


@pytest.fixture(scope='module')
def data():
    return load_data()


@pytest.fixture(scope='module')
def results():
    return load_results()


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_file_exists(self):
        assert os.path.exists('/app/results/analysis.json')

    def test_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_all_required_keys(self, results):
        required = [
            'overall_success_rates',
            'race_condition_analysis',
            'vuln_type_analysis',
            'config_comparison_tests',
            'convergence_analysis',
            'cutoff_analysis',
            'subsystem_analysis',
            'commit_msg_analysis',
        ]
        for key in required:
            assert key in results, f"Missing required top-level key: {key}"


# ---------------------------------------------------------------------------
# Overall success rates
# ---------------------------------------------------------------------------

class TestOverallRates:
    def test_all_configs_present(self, results):
        rates = results['overall_success_rates']
        for k in ['baseline_run1', 'baseline_run2', 'no_gdb',
                   'no_utilities', 'degraded_prompt', 'no_commit_msg']:
            assert k in rates, f"Missing config rate: {k}"
            assert 0.0 <= rates[k] <= 1.0, f"Rate out of range for {k}"

    def test_baseline_run1_rate(self, data, results):
        expected = sum(1 for d in data if eff_baseline(d)) / len(data)
        actual = results['overall_success_rates']['baseline_run1']
        assert abs(actual - round(expected, 4)) < 0.01, \
            f"Baseline run1 rate: got {actual}, expected {expected:.4f}"

    def test_no_gdb_rate(self, data, results):
        expected = sum(1 for d in data if d['no_gdb_success']) / len(data)
        actual = results['overall_success_rates']['no_gdb']
        assert abs(actual - round(expected, 4)) < 0.01

    def test_no_commit_msg_rate(self, data, results):
        expected = sum(1 for d in data if d['no_commit_msg_success']) / len(data)
        actual = results['overall_success_rates']['no_commit_msg']
        assert abs(actual - round(expected, 4)) < 0.01

    def test_cheating_reduces_baseline(self, data, results):
        """Baseline with cheating excluded should be <= raw baseline."""
        raw = sum(1 for d in data if d['baseline_run1_success']) / len(data)
        clean = results['overall_success_rates']['baseline_run1']
        assert clean <= raw + 0.001


# ---------------------------------------------------------------------------
# Race condition analysis
# ---------------------------------------------------------------------------

class TestRaceCondition:
    def test_keys_present(self, results):
        ra = results['race_condition_analysis']
        for k in ['race_success_rate', 'nonrace_success_rate',
                   'odds_ratio', 'p_value']:
            assert k in ra, f"Missing race analysis key: {k}"

    def test_fisher_exact_values(self, data, results):
        rs = sum(1 for d in data
                 if d['is_race_condition'] and eff_baseline(d))
        rf = sum(1 for d in data
                 if d['is_race_condition'] and not eff_baseline(d))
        ns = sum(1 for d in data
                 if not d['is_race_condition'] and eff_baseline(d))
        nf = sum(1 for d in data
                 if not d['is_race_condition'] and not eff_baseline(d))

        exp_or, exp_p = fisher_exact([[rs, rf], [ns, nf]])

        actual = results['race_condition_analysis']
        assert abs(actual['odds_ratio'] - exp_or) < 0.1, \
            f"Race OR: got {actual['odds_ratio']}, expected {exp_or:.4f}"
        assert abs(actual['p_value'] - exp_p) < 0.05, \
            f"Race p-value: got {actual['p_value']}, expected {exp_p:.4f}"

    def test_race_rate(self, data, results):
        race = [d for d in data if d['is_race_condition']]
        if len(race) > 0:
            expected = sum(1 for d in race if eff_baseline(d)) / len(race)
            actual = results['race_condition_analysis']['race_success_rate']
            assert abs(actual - expected) < 0.01

    def test_nonrace_rate(self, data, results):
        nr = [d for d in data if not d['is_race_condition']]
        if len(nr) > 0:
            expected = sum(1 for d in nr if eff_baseline(d)) / len(nr)
            actual = results['race_condition_analysis']['nonrace_success_rate']
            assert abs(actual - expected) < 0.01


# ---------------------------------------------------------------------------
# Vulnerability type analysis
# ---------------------------------------------------------------------------

class TestVulnTypeAnalysis:
    def _build_strata(self, data):
        """Build stratum tables independently."""
        filt = [d for d in data
                if d['vuln_type'] in ('uaf_df', 'oob')
                and not d['cheating_detected']]
        tables = []
        for rv in [True, False]:
            s = [d for d in filt if d['is_race_condition'] == rv]
            a = sum(1 for d in s
                    if d['vuln_type'] == 'uaf_df' and d['baseline_run1_success'])
            b = sum(1 for d in s
                    if d['vuln_type'] == 'uaf_df' and not d['baseline_run1_success'])
            c = sum(1 for d in s
                    if d['vuln_type'] == 'oob' and d['baseline_run1_success'])
            dd = sum(1 for d in s
                     if d['vuln_type'] == 'oob' and not d['baseline_run1_success'])
            tables.append(np.array([[a, b], [c, dd]]))
        return filt, tables

    def test_keys_present(self, results):
        vta = results['vuln_type_analysis']
        for k in ['odds_ratio', 'p_value', 'test_statistic',
                   'consistency_statistic', 'consistency_p_value']:
            assert k in vta, f"Missing vuln type analysis key: {k}"

    def test_odds_ratio(self, data, results):
        _, tables = self._build_strata(data)
        st = StratifiedTable(tables)
        exp_adj = st.oddsratio_pooled
        actual = results['vuln_type_analysis']['odds_ratio']
        assert abs(actual - exp_adj) < 0.15, \
            f"Vuln type OR: got {actual}, expected {exp_adj:.4f}"

    def test_not_crude_odds_ratio(self, data, results):
        """Ensure the reported OR is not the naive unadjusted value."""
        filt, tables = self._build_strata(data)
        us = sum(1 for d in filt
                 if d['vuln_type'] == 'uaf_df' and d['baseline_run1_success'])
        uf = sum(1 for d in filt
                 if d['vuln_type'] == 'uaf_df' and not d['baseline_run1_success'])
        os_ = sum(1 for d in filt
                  if d['vuln_type'] == 'oob' and d['baseline_run1_success'])
        of_ = sum(1 for d in filt
                  if d['vuln_type'] == 'oob' and not d['baseline_run1_success'])
        crude_or, _ = fisher_exact([[us, uf], [os_, of_]])

        st = StratifiedTable(tables)
        adj_or = st.oddsratio_pooled

        actual = results['vuln_type_analysis']['odds_ratio']
        # If crude and adjusted differ meaningfully, actual must be closer to adjusted
        if abs(crude_or - adj_or) > 0.05:
            assert abs(actual - adj_or) < abs(actual - crude_or), \
                f"OR ({actual}) appears closer to naive unadjusted value ({crude_or:.4f}) " \
                f"than to properly computed value ({adj_or:.4f})"

    def test_p_value(self, data, results):
        _, tables = self._build_strata(data)
        st = StratifiedTable(tables)
        assoc = st.test_null_odds()
        actual = results['vuln_type_analysis']['p_value']
        assert abs(actual - assoc.pvalue) < 0.05, \
            f"Vuln type p-value: got {actual}, expected {assoc.pvalue:.4f}"

    def test_consistency_valid(self, results):
        vta = results['vuln_type_analysis']
        assert vta['consistency_p_value'] >= 0.0
        assert vta['consistency_p_value'] <= 1.0
        assert vta['consistency_statistic'] >= 0.0


# ---------------------------------------------------------------------------
# Configuration comparison tests
# ---------------------------------------------------------------------------

class TestConfigComparison:
    def test_all_comparisons_present(self, results):
        pt = results['config_comparison_tests']
        for k in ['baseline_vs_no_gdb', 'baseline_vs_no_utilities',
                   'baseline_vs_degraded_prompt', 'baseline_vs_no_commit_msg']:
            assert k in pt, f"Missing comparison: {k}"
            assert 'p_value' in pt[k], f"Missing p_value in {k}"
            assert 0.0 <= pt[k]['p_value'] <= 1.0

    def test_no_commit_msg_discordant_direction(self, data, results):
        """Removing commit messages should reduce success:
        more cases go baseline=yes,config=no than the reverse."""
        clean = [d for d in data if not d['cheating_detected']]
        b = sum(1 for d in clean
                if d['baseline_run1_success'] and not d['no_commit_msg_success'])
        c = sum(1 for d in clean
                if not d['baseline_run1_success'] and d['no_commit_msg_success'])
        assert b >= c, (
            f"Expected baseline better than no_commit_msg "
            f"in discordant pairs (b={b}, c={c})"
        )

    def test_pvalue_no_commit_msg(self, data, results):
        """Independently compute test p-value for baseline vs
        no_commit_msg using discordant pairs."""
        clean = [d for d in data if not d['cheating_detected']]
        b = sum(1 for d in clean
                if d['baseline_run1_success'] and not d['no_commit_msg_success'])
        c = sum(1 for d in clean
                if not d['baseline_run1_success'] and d['no_commit_msg_success'])

        if b + c == 0:
            exp_p = 1.0
        elif b + c < 25:
            from scipy.stats import binomtest
            exp_p = binomtest(min(b, c), b + c, 0.5).pvalue
        else:
            stat = (b - c) ** 2 / (b + c)
            exp_p = 1.0 - chi2.cdf(stat, 1)

        actual_p = results['config_comparison_tests']['baseline_vs_no_commit_msg']['p_value']
        assert abs(actual_p - exp_p) < 0.15, \
            f"Config comparison p (no_commit_msg): got {actual_p}, expected {exp_p:.4f}"


# ---------------------------------------------------------------------------
# Convergence analysis
# ---------------------------------------------------------------------------

class TestConvergence:
    def test_keys_present(self, results):
        conv = results['convergence_analysis']
        for k in ['run1_successes', 'run2_successes', 'union_2_runs',
                   'union_rate_2_runs', 'run3_additional', 'union_rate_3_runs']:
            assert k in conv, f"Missing convergence key: {k}"

    def test_convergence_counts(self, data, results):
        r1 = {d['id'] for d in data if eff_baseline(d)}
        r2 = {d['id'] for d in data if d['baseline_run2_success']}
        r3 = {d['id'] for d in data
              if d.get('baseline_run3_success') is True}
        u12 = r1 | r2
        u123 = u12 | r3
        n = len(data)

        conv = results['convergence_analysis']
        assert conv['run1_successes'] == len(r1), \
            f"Run1 count: got {conv['run1_successes']}, expected {len(r1)}"
        assert conv['run2_successes'] == len(r2), \
            f"Run2 count: got {conv['run2_successes']}, expected {len(r2)}"
        assert conv['union_2_runs'] == len(u12), \
            f"Union 2 runs: got {conv['union_2_runs']}, expected {len(u12)}"
        assert abs(conv['union_rate_2_runs'] - len(u12) / n) < 0.01
        assert conv['run3_additional'] == len(r3 - u12), \
            f"Run3 additional: got {conv['run3_additional']}, expected {len(r3 - u12)}"
        assert abs(conv['union_rate_3_runs'] - len(u123) / n) < 0.01

    def test_union_monotonic(self, results):
        conv = results['convergence_analysis']
        assert conv['union_2_runs'] >= conv['run1_successes']
        assert conv['union_2_runs'] >= conv['run2_successes']
        assert conv['union_rate_3_runs'] >= conv['union_rate_2_runs'] - 0.001


# ---------------------------------------------------------------------------
# Cutoff analysis
# ---------------------------------------------------------------------------

class TestCutoff:
    def test_keys_present(self, results):
        ca = results['cutoff_analysis']
        for k in ['pre_cutoff_rate', 'post_cutoff_rate', 'odds_ratio', 'p_value']:
            assert k in ca, f"Missing cutoff key: {k}"

    def test_cutoff_rates(self, data, results):
        pre = [d for d in data if not d['is_post_cutoff']]
        post = [d for d in data if d['is_post_cutoff']]
        pre_s = sum(1 for d in pre if eff_baseline(d))
        post_s = sum(1 for d in post if eff_baseline(d))

        ca = results['cutoff_analysis']
        if len(pre) > 0:
            assert abs(ca['pre_cutoff_rate'] - pre_s / len(pre)) < 0.01
        if len(post) > 0:
            assert abs(ca['post_cutoff_rate'] - post_s / len(post)) < 0.01

    def test_cutoff_fisher(self, data, results):
        pre = [d for d in data if not d['is_post_cutoff']]
        post = [d for d in data if d['is_post_cutoff']]
        pre_s = sum(1 for d in pre if eff_baseline(d))
        pre_f = len(pre) - pre_s
        post_s = sum(1 for d in post if eff_baseline(d))
        post_f = len(post) - post_s

        exp_or, exp_p = fisher_exact([[pre_s, pre_f], [post_s, post_f]])
        ca = results['cutoff_analysis']
        assert abs(ca['odds_ratio'] - exp_or) < 0.15
        assert abs(ca['p_value'] - exp_p) < 0.05
        assert 0.0 <= ca['p_value'] <= 1.0


# ---------------------------------------------------------------------------
# Subsystem analysis
# ---------------------------------------------------------------------------

class TestSubsystem:
    def test_all_subsystems_present(self, data, results):
        subs = {d['subsystem'] for d in data}
        for s in subs:
            assert s in results['subsystem_analysis'], \
                f"Missing subsystem: {s}"

    def test_subsystem_counts(self, data, results):
        for sub, info in results['subsystem_analysis'].items():
            expected_n = sum(1 for d in data if d['subsystem'] == sub)
            assert info['n'] == expected_n, \
                f"Wrong count for {sub}: got {info['n']}, expected {expected_n}"

    def test_subsystem_rates(self, data, results):
        for sub, info in results['subsystem_analysis'].items():
            cases = [d for d in data if d['subsystem'] == sub]
            expected = sum(1 for d in cases if eff_baseline(d)) / len(cases)
            assert abs(info['success_rate'] - expected) < 0.01, \
                f"Wrong rate for {sub}: got {info['success_rate']}, expected {expected:.4f}"

    def test_subsystem_or_valid(self, results):
        for sub, info in results['subsystem_analysis'].items():
            assert info['odds_ratio'] >= 0.0
            assert 0.0 <= info['p_value'] <= 1.0


# ---------------------------------------------------------------------------
# Commit message analysis
# ---------------------------------------------------------------------------

class TestCommitMsg:
    def test_all_levels_present(self, results):
        cm = results['commit_msg_analysis']
        for lvl in ['1', '2', '3']:
            assert lvl in cm, f"Missing commit msg level: {lvl}"
            assert 'n' in cm[lvl]
            assert 'success_rate' in cm[lvl]

    def test_level_counts(self, data, results):
        for lvl in [1, 2, 3]:
            expected_n = sum(1 for d in data if d['commit_msg_level'] == lvl)
            actual = results['commit_msg_analysis'][str(lvl)]
            assert actual['n'] == expected_n, \
                f"Wrong count for level {lvl}: got {actual['n']}, expected {expected_n}"

    def test_level_rates(self, data, results):
        for lvl in [1, 2, 3]:
            cases = [d for d in data if d['commit_msg_level'] == lvl]
            if len(cases) > 0:
                expected = sum(1 for d in cases if eff_baseline(d)) / len(cases)
                actual = results['commit_msg_analysis'][str(lvl)]['success_rate']
                assert abs(actual - expected) < 0.01, \
                    f"Wrong rate for level {lvl}"

    def test_rate_ordering(self, results):
        """Higher disclosure should generally yield higher success."""
        cm = results['commit_msg_analysis']
        if cm['3']['n'] >= 5 and cm['1']['n'] >= 5:
            assert cm['3']['success_rate'] >= cm['1']['success_rate'] - 0.15
