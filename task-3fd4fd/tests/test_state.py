#!/usr/bin/env python3
"""Tests for multi-core EKF binary log forensics task.

Verifies corrected noise parameters, channel diagnostics, GPS outage
detection, magnetometer anomaly detection, lane-switch identification,
and cruise-phase boundary detection.
"""

import json
import os
import pytest

# Ground-truth sensor noise values
TRUTH_PARAMS = {
    'EK3_VELNE_NOISE': 0.80,
    'EK3_VELD_NOISE': 0.50,
    'EK3_POSNE_NOISE': 1.50,
    'EK3_ALT_NOISE': 3.00,
    'EK3_MAG_NOISE': 0.05,
    'EK3_YAW_NOISE': 0.50,
}

PARAM_RANGES = {
    'EK3_VELNE_NOISE': (0.05, 5.0),
    'EK3_VELD_NOISE': (0.05, 5.0),
    'EK3_POSNE_NOISE': (0.1, 10.0),
    'EK3_ALT_NOISE': (0.1, 10.0),
    'EK3_MAG_NOISE': (0.01, 0.5),
    'EK3_YAW_NOISE': (0.01, 1.0),
}

TOLERANCE = 0.20
OUTPUT_FILE = '/app/output/analysis_results.json'


def load_output():
    with open(OUTPUT_FILE) as f:
        return json.load(f)


# ── Output structure ──

class TestOutputFormat:
    def test_output_file_exists(self):
        assert os.path.exists(OUTPUT_FILE), f"Missing: {OUTPUT_FILE}"

    def test_valid_json(self):
        data = load_output()
        assert isinstance(data, dict)

    def test_required_keys(self):
        data = load_output()
        for key in ('corrected_params', 'inconsistent_channels',
                     'primary_core_switches', 'cruise_phase',
                     'gps_outage', 'anomalies'):
            assert key in data, f"Missing key: '{key}'"

    def test_all_params_present(self):
        data = load_output()
        for p in TRUTH_PARAMS:
            assert p in data['corrected_params'], f"Missing param: {p}"


# ── Corrected parameter accuracy ──

class TestCorrectedParams:
    @pytest.mark.parametrize("param", list(TRUTH_PARAMS.keys()))
    def test_param_accuracy(self, param):
        data = load_output()
        value = float(data['corrected_params'][param])
        truth = TRUTH_PARAMS[param]
        lo = truth * (1 - TOLERANCE)
        hi = truth * (1 + TOLERANCE)
        assert lo <= value <= hi, (
            f"{param}={value:.4f} outside [{lo:.4f}, {hi:.4f}] (truth={truth})"
        )


class TestParamRanges:
    def test_all_in_range(self):
        data = load_output()
        for param, (lo, hi) in PARAM_RANGES.items():
            value = float(data['corrected_params'][param])
            assert lo <= value <= hi, (
                f"{param}={value:.4f} outside valid range [{lo}, {hi}]"
            )


# ── Channel diagnostics ──

class TestChannelDiagnostics:
    def test_misconfigured_detected(self):
        """At least 4 of 5 misconfigured channels must be flagged."""
        data = load_output()
        inconsistent = set(data['inconsistent_channels'])
        must_find = {'VelN', 'VelE', 'PosN', 'PosE', 'Alt'}
        found = must_find & inconsistent
        assert len(found) >= 4, (
            f"Expected ≥4 of {must_find} inconsistent, found: {found}"
        )

    def test_consistent_not_flagged(self):
        """Correctly-tuned channels must not be false-flagged."""
        data = load_output()
        inconsistent = set(data['inconsistent_channels'])
        must_not_flag = {'VelD', 'MagX', 'MagY', 'Yaw'}
        false_pos = must_not_flag & inconsistent
        assert len(false_pos) == 0, (
            f"False positives: {false_pos}"
        )


# ── Anomaly detection ──

class TestAnomalyDetection:
    def test_gps_outage_detected(self):
        data = load_output()
        gps = data.get('gps_outage', {})
        assert gps.get('detected', False) is True, "GPS outage not detected"

    def test_gps_outage_bounds(self):
        data = load_output()
        gps = data.get('gps_outage', {})
        if not gps.get('detected', False):
            pytest.skip("GPS outage not detected")
        start = gps.get('start_index', -1)
        end = gps.get('end_index', -1)
        assert 500 <= start <= 700, f"GPS start_index={start}, expected ~600"
        assert 900 <= end <= 1100, f"GPS end_index={end}, expected ~1000"

    def test_mag_anomaly_detected(self):
        """MagZ / magnetometer bias must appear in anomalies."""
        data = load_output()
        anomalies = data.get('anomalies', [])
        found = False
        for a in anomalies:
            text = str(a).lower()
            if 'magz' in text or 'mag_z' in text or 'imz' in text:
                found = True
                break
            if 'mag' in text and any(w in text for w in
                    ('bias', 'shift', 'anomal', 'offset', 'interfere')):
                found = True
                break
        assert found, f"Magnetometer anomaly not found. Got: {anomalies}"


# ── Multi-core / lane switching ──

class TestLaneSwitching:
    def test_switch_detected(self):
        data = load_output()
        switches = data.get('primary_core_switches', [])
        assert len(switches) >= 1, "No primary core switches detected"

    def test_switch_details(self):
        data = load_output()
        switches = data.get('primary_core_switches', [])
        found = False
        for sw in switches:
            fc = sw.get('from_core', -1)
            tc = sw.get('to_core', -1)
            idx = sw.get('sample_index', -1)
            if fc == 0 and tc == 1 and 1100 <= idx <= 1300:
                found = True
                break
        assert found, (
            f"Expected core 0→1 switch near sample 1200, got: {switches}"
        )


# ── Flight phase detection ──

class TestFlightPhase:
    def test_cruise_start(self):
        data = load_output()
        cruise = data.get('cruise_phase', {})
        start = cruise.get('start_sample', -1)
        assert 200 <= start <= 400, (
            f"cruise start_sample={start}, expected ~300"
        )

    def test_cruise_end(self):
        data = load_output()
        cruise = data.get('cruise_phase', {})
        end = cruise.get('end_sample', -1)
        assert 1600 <= end <= 1800, (
            f"cruise end_sample={end}, expected ~1700"
        )
