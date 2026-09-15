#!/usr/bin/env python3
"""Pytest verification of PLR parameter extraction results."""


import json
import os
import pytest

GROUND_TRUTH_PATH = '/tests/ground_truth.json'
REPORT_PATH = '/app/results/report.json'


@pytest.fixture(scope='session')
def ground_truth():
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='session')
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


def approx_eq(actual, expected, rel_tol=0.15, abs_tol=0.3):
    """Check approximate equality with combined relative/absolute tolerance."""
    if expected is None:
        return actual is None
    if actual is None:
        return False
    if expected == 0:
        return abs(actual) < abs_tol
    return abs(actual - expected) <= max(rel_tol * abs(expected), abs_tol)


# ── Report structure ──────────────────────────────────────────────────────────

class TestReportStructure:
    def test_report_exists(self, report):
        assert report is not None

    def test_has_conditions(self, report):
        assert 'conditions' in report
        assert 'blue' in report['conditions']
        assert 'red' in report['conditions']

    def test_conditions_have_average(self, report):
        for cond in ['blue', 'red']:
            assert 'average' in report['conditions'][cond]
            assert 'n_valid_trials' in report['conditions'][cond]

    def test_has_net_pipr(self, report):
        assert 'net_pipr_6s_pct' in report

    def test_has_horner_assessment(self, report):
        assert 'horner_assessment' in report
        ha = report['horner_assessment']
        assert 'dilation_lag_4s_mm' in ha
        assert 'affected_eye' in ha
        assert 't75_left_s' in ha
        assert 't75_right_s' in ha

    def test_has_artifact_summary(self, report):
        assert 'artifact_summary' in report


# ── Blue condition parameters ─────────────────────────────────────────────────

class TestBlueCondition:
    def test_n_valid_trials(self, report, ground_truth):
        actual = report['conditions']['blue']['n_valid_trials']
        expected = ground_truth['conditions']['blue']['n_valid_trials']
        assert actual == expected, f"Blue valid trials: {actual} != {expected}"

    def test_baseline(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['baseline_mm']
        expected = ground_truth['conditions']['blue']['average']['baseline_mm']
        assert approx_eq(actual, expected, rel_tol=0.05, abs_tol=0.15), \
            f"Blue baseline: {actual} vs {expected}"

    def test_max_constriction_mm(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['max_constriction_mm']
        expected = ground_truth['conditions']['blue']['average']['max_constriction_mm']
        assert approx_eq(actual, expected, rel_tol=0.20, abs_tol=0.4), \
            f"Blue max constriction mm: {actual} vs {expected}"

    def test_max_constriction_pct(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['max_constriction_pct']
        expected = ground_truth['conditions']['blue']['average']['max_constriction_pct']
        assert approx_eq(actual, expected, rel_tol=0.20, abs_tol=6.0), \
            f"Blue max constriction %: {actual} vs {expected}"

    def test_latency(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['latency_s']
        expected = ground_truth['conditions']['blue']['average']['latency_s']
        assert abs(actual - expected) < 0.08, \
            f"Blue latency: {actual} vs {expected}"

    def test_time_to_max_constriction(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['time_to_max_constriction_s']
        expected = ground_truth['conditions']['blue']['average']['time_to_max_constriction_s']
        assert abs(actual - expected) < 0.20, \
            f"Blue time to max: {actual} vs {expected}"

    def test_mcv(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['max_constriction_velocity_mm_s']
        expected = ground_truth['conditions']['blue']['average']['max_constriction_velocity_mm_s']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=1.5), \
            f"Blue MCV: {actual} vs {expected}"

    def test_redilation_velocity(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['redilation_velocity_mm_s']
        expected = ground_truth['conditions']['blue']['average']['redilation_velocity_mm_s']
        assert approx_eq(actual, expected, rel_tol=0.40, abs_tol=0.5), \
            f"Blue redilation vel: {actual} vs {expected}"

    def test_t75_null_for_strong_pipr(self, report, ground_truth):
        """Blue condition with strong PIPR: 75% recovery is unachievable."""
        expected = ground_truth['conditions']['blue']['average']['t75_s']
        actual = report['conditions']['blue']['average']['t75_s']
        if expected is None:
            assert actual is None, \
                f"Blue T75 should be null (strong PIPR) but got {actual}"
        else:
            assert actual is not None
            assert abs(actual - expected) < 2.0

    def test_pipr_6s(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['pipr_6s_pct']
        expected = ground_truth['conditions']['blue']['average']['pipr_6s_pct']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=4.0), \
            f"Blue PIPR 6s: {actual} vs {expected}"

    def test_pipr_plateau(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['pipr_plateau_pct']
        expected = ground_truth['conditions']['blue']['average']['pipr_plateau_pct']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=4.0), \
            f"Blue PIPR plateau: {actual} vs {expected}"

    def test_pipr_early_auc(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['pipr_early_auc']
        expected = ground_truth['conditions']['blue']['average']['pipr_early_auc']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=25.0), \
            f"Blue early AUC: {actual} vs {expected}"

    def test_pipr_late_auc(self, report, ground_truth):
        actual = report['conditions']['blue']['average']['pipr_late_auc']
        expected = ground_truth['conditions']['blue']['average']['pipr_late_auc']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=50.0), \
            f"Blue late AUC: {actual} vs {expected}"


# ── Red condition parameters ──────────────────────────────────────────────────

class TestRedCondition:
    def test_n_valid_trials(self, report, ground_truth):
        actual = report['conditions']['red']['n_valid_trials']
        expected = ground_truth['conditions']['red']['n_valid_trials']
        assert actual == expected

    def test_baseline(self, report, ground_truth):
        actual = report['conditions']['red']['average']['baseline_mm']
        expected = ground_truth['conditions']['red']['average']['baseline_mm']
        assert approx_eq(actual, expected, rel_tol=0.05, abs_tol=0.15), \
            f"Red baseline: {actual} vs {expected}"

    def test_max_constriction_mm(self, report, ground_truth):
        actual = report['conditions']['red']['average']['max_constriction_mm']
        expected = ground_truth['conditions']['red']['average']['max_constriction_mm']
        assert approx_eq(actual, expected, rel_tol=0.20, abs_tol=0.4), \
            f"Red max constriction mm: {actual} vs {expected}"

    def test_latency(self, report, ground_truth):
        actual = report['conditions']['red']['average']['latency_s']
        expected = ground_truth['conditions']['red']['average']['latency_s']
        assert abs(actual - expected) < 0.08, \
            f"Red latency: {actual} vs {expected}"

    def test_mcv(self, report, ground_truth):
        actual = report['conditions']['red']['average']['max_constriction_velocity_mm_s']
        expected = ground_truth['conditions']['red']['average']['max_constriction_velocity_mm_s']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=1.5), \
            f"Red MCV: {actual} vs {expected}"

    def test_t75_defined(self, report, ground_truth):
        """Red condition with weak PIPR: T75 should be defined."""
        expected = ground_truth['conditions']['red']['average']['t75_s']
        actual = report['conditions']['red']['average']['t75_s']
        if expected is not None:
            assert actual is not None, "Red T75 should be defined (weak PIPR)"
            assert abs(actual - expected) < 1.5, \
                f"Red T75: {actual} vs {expected}"

    def test_pipr_6s_small(self, report, ground_truth):
        actual = report['conditions']['red']['average']['pipr_6s_pct']
        expected = ground_truth['conditions']['red']['average']['pipr_6s_pct']
        assert approx_eq(actual, expected, rel_tol=0.60, abs_tol=3.0), \
            f"Red PIPR 6s: {actual} vs {expected}"

    def test_pipr_early_auc(self, report, ground_truth):
        actual = report['conditions']['red']['average']['pipr_early_auc']
        expected = ground_truth['conditions']['red']['average']['pipr_early_auc']
        assert approx_eq(actual, expected, rel_tol=0.40, abs_tol=10.0), \
            f"Red early AUC: {actual} vs {expected}"


# ── Net PIPR ──────────────────────────────────────────────────────────────────

class TestNetPIPR:
    def test_net_pipr_value(self, report, ground_truth):
        actual = report['net_pipr_6s_pct']
        expected = ground_truth['net_pipr_6s_pct']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=5.0), \
            f"Net PIPR: {actual} vs {expected}"

    def test_net_pipr_positive(self, report):
        """Blue PIPR should exceed red PIPR (melanopsin contribution)."""
        assert report['net_pipr_6s_pct'] > 0, \
            f"Net PIPR should be positive, got {report['net_pipr_6s_pct']}"

    def test_net_pipr_physiological_range(self, report):
        """Net PIPR should be in physiologically plausible range (2-25%)."""
        val = report['net_pipr_6s_pct']
        assert 2.0 < val < 25.0, f"Net PIPR {val}% outside plausible range"


# ── Horner assessment ─────────────────────────────────────────────────────────

class TestHornerAssessment:
    def test_affected_eye_correct(self, report, ground_truth):
        actual = report['horner_assessment']['affected_eye']
        expected = ground_truth['horner_assessment']['affected_eye']
        assert actual == expected, \
            f"Horner affected eye: '{actual}' vs '{expected}'"

    def test_dilation_lag(self, report, ground_truth):
        actual = report['horner_assessment']['dilation_lag_4s_mm']
        expected = ground_truth['horner_assessment']['dilation_lag_4s_mm']
        assert approx_eq(actual, expected, rel_tol=0.35, abs_tol=0.4), \
            f"Dilation lag: {actual} vs {expected}"

    def test_dilation_lag_positive(self, report):
        assert report['horner_assessment']['dilation_lag_4s_mm'] > 0

    def test_t75_right(self, report, ground_truth):
        actual = report['horner_assessment']['t75_right_s']
        expected = ground_truth['horner_assessment']['t75_right_s']
        if expected is not None:
            assert actual is not None, "Horner right T75 should be defined"
            assert abs(actual - expected) < 1.5, \
                f"Horner right T75: {actual} vs {expected}"

    def test_t75_left(self, report, ground_truth):
        actual = report['horner_assessment']['t75_left_s']
        expected = ground_truth['horner_assessment']['t75_left_s']
        if expected is not None:
            assert actual is not None, "Horner left T75 should be defined"
            assert abs(actual - expected) < 3.0, \
                f"Horner left T75: {actual} vs {expected}"

    def test_t75_asymmetry(self, report):
        """Affected eye must have longer T75 (slower redilation)."""
        t75_left = report['horner_assessment']['t75_left_s']
        t75_right = report['horner_assessment']['t75_right_s']
        affected = report['horner_assessment']['affected_eye']
        if t75_left is not None and t75_right is not None:
            if affected == 'left':
                assert t75_left > t75_right, \
                    f"Left (affected) T75 {t75_left} should exceed right {t75_right}"
            elif affected == 'right':
                assert t75_right > t75_left


# ── Artifact detection ────────────────────────────────────────────────────────

class TestArtifactDetection:
    def test_blue_01_clean(self, report):
        info = report['artifact_summary']['blue_01.csv']
        assert info['blinks_detected'] == 0, \
            f"Blue 01 should be clean, detected {info['blinks_detected']} blinks"

    def test_blue_02_blinks_detected(self, report, ground_truth):
        actual = report['artifact_summary']['blue_02.csv']['blinks_detected']
        expected = ground_truth['artifacts']['blue_02.csv']['blinks_detected']
        assert abs(actual - expected) <= 1, \
            f"Blue 02 blinks: {actual} vs {expected}"

    def test_blue_03_blinks_detected(self, report, ground_truth):
        actual = report['artifact_summary']['blue_03.csv']['blinks_detected']
        expected = ground_truth['artifacts']['blue_03.csv']['blinks_detected']
        assert abs(actual - expected) <= 1, \
            f"Blue 03 blinks: {actual} vs {expected}"

    def test_red_trials_clean(self, report):
        for trial in range(1, 4):
            fname = f'red_{trial:02d}.csv'
            info = report['artifact_summary'][fname]
            assert info['blinks_detected'] == 0, \
                f"{fname} should be clean, detected {info['blinks_detected']} blinks"

    def test_artifact_pct_format(self, report):
        for fname, info in report['artifact_summary'].items():
            assert 'artifact_pct' in info
            assert isinstance(info['artifact_pct'], (int, float))
            assert 0 <= info['artifact_pct'] <= 100


# ── Cross-condition consistency ───────────────────────────────────────────────

class TestCrossConditionConsistency:
    def test_blue_constriction_larger_than_red(self, report):
        """Blue stimulus typically produces larger constriction."""
        blue_constr = report['conditions']['blue']['average']['max_constriction_mm']
        red_constr = report['conditions']['red']['average']['max_constriction_mm']
        assert blue_constr > red_constr * 0.8, \
            f"Blue constriction {blue_constr} should be comparable or larger than red {red_constr}"

    def test_blue_pipr_larger_than_red(self, report):
        """Blue (melanopsin-activating) should produce larger PIPR than red."""
        blue_pipr = report['conditions']['blue']['average']['pipr_6s_pct']
        red_pipr = report['conditions']['red']['average']['pipr_6s_pct']
        assert blue_pipr > red_pipr, \
            f"Blue PIPR {blue_pipr}% should exceed red PIPR {red_pipr}%"

    def test_baselines_consistent(self, report):
        """Both conditions should have similar baselines (same eye)."""
        blue_bl = report['conditions']['blue']['average']['baseline_mm']
        red_bl = report['conditions']['red']['average']['baseline_mm']
        assert abs(blue_bl - red_bl) < 0.5, \
            f"Baselines should be similar: blue {blue_bl} vs red {red_bl}"
