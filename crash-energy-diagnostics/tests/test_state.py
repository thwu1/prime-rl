"""Tests for crash simulation post-processing pipeline."""

import json
import os
import subprocess

import pytest


def load_report():
    path = '/app/results/report.json'
    assert os.path.exists(path), f"Report not found at {path}"
    with open(path) as f:
        return json.load(f)


# ──────────────────────── Report structure ────────────────────────


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/results/report.json')

    def test_top_level_keys(self):
        r = load_report()
        for key in ['energy_balance', 'peak_accelerations', 'hic', 'assessment']:
            assert key in r, f"Missing top-level key: {key}"

    def test_energy_balance_keys(self):
        eb = load_report()['energy_balance']
        for key in ['max_error_pct', 'first_violation_time', 'error_source']:
            assert key in eb, f"Missing energy_balance key: {key}"

    def test_peak_accelerations_keys(self):
        pa = load_report()['peak_accelerations']
        for cfc in ['CFC60', 'CFC180', 'CFC600', 'CFC1000']:
            assert cfc in pa, f"Missing CFC class: {cfc}"

    def test_hic_keys(self):
        hic = load_report()['hic']
        assert 'hic15' in hic, "Missing hic.hic15"
        assert 'hic36' in hic, "Missing hic.hic36"


# ──────────────────────── Energy balance ──────────────────────────


class TestEnergyBalance:
    def test_max_error_pct_value(self):
        """Hourglass anomaly creates ~6.4% max energy error."""
        err = load_report()['energy_balance']['max_error_pct']
        assert isinstance(err, (int, float))
        assert 5.5 < err < 7.5, f"Expected ~6.4%, got {err}%"

    def test_first_violation_time(self):
        """2% threshold first exceeded around t = 0.078 s."""
        fvt = load_report()['energy_balance']['first_violation_time']
        assert fvt is not None, "Expected a 2% violation to occur"
        assert 0.070 < fvt < 0.085, f"Expected ~0.078 s, got {fvt} s"

    def test_error_source_is_hourglass(self):
        """Dominant energy error source is hourglass modes."""
        src = load_report()['energy_balance']['error_source']
        assert src == 'hourglass', f"Expected 'hourglass', got '{src}'"


# ──────────────────────── SAE J211 CFC filtering ──────────────────


class TestCFCFiltering:
    def test_positive_peaks(self):
        for cfc, val in load_report()['peak_accelerations'].items():
            assert val > 0, f"{cfc} peak acceleration must be positive"

    def test_reasonable_range(self):
        """All filtered peaks between 20 g and 100 g for this crash pulse."""
        for cfc, val in load_report()['peak_accelerations'].items():
            assert 20 < val < 100, f"{cfc} = {val} g outside expected [20, 100]"

    def test_more_filtering_gives_lower_peak(self):
        """CFC60 (strongest low-pass) should yield lower peak than CFC1000."""
        pa = load_report()['peak_accelerations']
        assert pa['CFC60'] < pa['CFC1000'], (
            f"CFC60 ({pa['CFC60']}) should be < CFC1000 ({pa['CFC1000']})"
        )


# ──────────────────────── HIC ─────────────────────────────────────


class TestHIC:
    def test_hic15_range(self):
        """HIC15 for ~45 g crash pulse should be in [50, 600]."""
        hic15 = load_report()['hic']['hic15']
        assert isinstance(hic15, (int, float))
        assert 50 < hic15 < 600, f"HIC15 = {hic15} outside [50, 600]"

    def test_hic36_range(self):
        """HIC36 should be in [100, 1000] for this pulse."""
        hic36 = load_report()['hic']['hic36']
        assert isinstance(hic36, (int, float))
        assert 100 < hic36 < 1000, f"HIC36 = {hic36} outside [100, 1000]"

    def test_hic36_geq_hic15(self):
        """HIC36 >= HIC15 (superset of time windows)."""
        hic = load_report()['hic']
        assert hic['hic36'] >= hic['hic15'] - 0.2, (
            f"HIC36 ({hic['hic36']}) must be >= HIC15 ({hic['hic15']})"
        )


# ──────────────────────── Assessment ──────────────────────────────


class TestAssessment:
    def test_assessment_is_fail(self):
        """Assessment should be FAIL because max energy error > 5%."""
        assert load_report()['assessment'] == 'FAIL'


# ──────────────────────── Executability ───────────────────────────


class TestExecutability:
    def test_main_script_exists(self):
        assert os.path.exists('/app/crashdiag/main.py'), \
            "Pipeline script must exist at /app/crashdiag/main.py"

    def test_main_runs_successfully(self):
        """Pipeline must execute without errors and regenerate the report."""
        result = subprocess.run(
            ['python3', '/app/crashdiag/main.py'],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"main.py failed:\n{result.stderr[:500]}"

    def test_report_valid_after_rerun(self):
        """After re-running the pipeline, the report must still contain valid data."""
        r = load_report()
        assert isinstance(r['energy_balance']['max_error_pct'], (int, float))
        assert isinstance(r['hic']['hic15'], (int, float))
        assert isinstance(r['hic']['hic36'], (int, float))
        for val in r['peak_accelerations'].values():
            assert isinstance(val, (int, float))
