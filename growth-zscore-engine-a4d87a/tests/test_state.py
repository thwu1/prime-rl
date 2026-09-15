"""
Test suite for the LMS Growth Assessment Engine.
Verifies z-scores, percentiles, chart routing, transition blending,
percentile crossing detection, and growth velocity computation.

"""

import json
import subprocess
import csv
import math
import os
import pytest

Z_TOLERANCE = 0.01
P_TOLERANCE = 0.005


def read_lms_data(csv_path, chart, measure, gender):
    """Read LMS data from CSV, returning list of dicts sorted by age."""
    data = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row['chart'] == chart and
                    row['measure'] == measure and
                    row['gender'] == gender):
                data.append({
                    'age': float(row['age']),
                    'L': float(row['L']),
                    'M': float(row['M']),
                    'S': float(row['S'])
                })
    return sorted(data, key=lambda x: x['age'])


def interpolate_lms(age, data):
    """Linear interpolation of LMS parameters at given age."""
    if not data:
        return None
    ages = [d['age'] for d in data]
    if age < ages[0] - 1e-10 or age > ages[-1] + 1e-10:
        return None

    for d in data:
        if abs(d['age'] - age) < 1e-10:
            return d['L'], d['M'], d['S']

    for i in range(len(data) - 1):
        if data[i]['age'] <= age <= data[i + 1]['age']:
            span = data[i + 1]['age'] - data[i]['age']
            if span == 0:
                return data[i]['L'], data[i]['M'], data[i]['S']
            t = (age - data[i]['age']) / span
            L = data[i]['L'] + t * (data[i + 1]['L'] - data[i]['L'])
            M = data[i]['M'] + t * (data[i + 1]['M'] - data[i]['M'])
            S = data[i]['S'] + t * (data[i + 1]['S'] - data[i]['S'])
            return L, M, S
    return None


def compute_zscore(x, L, M, S):
    """LMS z-score computation with L=0 handling."""
    if abs(L) < 1e-10:
        return math.log(x / M) / S
    return ((x / M) ** L - 1) / (L * S)


def normal_cdf(z):
    """Standard normal CDF using erf."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def pma_to_months(pma_weeks):
    """Convert PMA in weeks to WHO postnatal months (term=40 weeks)."""
    return (pma_weeks - 40) * 7 / 30.4375


def run_engine(patients):
    """Run the R growth engine with given patient data."""
    input_path = '/tmp/test_input.json'
    output_path = '/tmp/test_output.json'

    with open(input_path, 'w') as f:
        json.dump(patients, f)

    result = subprocess.run(
        ['Rscript', '/app/growth_engine.R', '/app/data', input_path, output_path],
        capture_output=True, text=True, timeout=120
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"R engine failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    with open(output_path) as f:
        return json.load(f)


class TestWHOTermInfant:
    """Tests for term infant WHO chart lookups."""

    def test_male_birth_median(self):
        """Weight equal to median at birth should give z=0, p=0.5."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L, M, S = interpolate_lms(0, who_data)

        patients = [{
            "id": "T1", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": M}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None, "z_score must not be null"
        assert abs(a['z_score']) < Z_TOLERANCE
        assert a['percentile'] is not None, "percentile must not be null"
        assert abs(a['percentile'] - 0.5) < P_TOLERANCE
        assert a['chart_used'] == 'who_2006_infant'

    def test_male_birth_above_median(self):
        """Above-median weight should give positive z and high percentile."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L, M, S = interpolate_lms(0, who_data)
        expected_z = compute_zscore(4.0, L, M, S)
        expected_p = normal_cdf(expected_z)

        patients = [{
            "id": "T2", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": 4.0}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None
        assert abs(a['z_score'] - expected_z) < Z_TOLERANCE, \
            f"z={a['z_score']}, expected={expected_z:.4f}"
        assert abs(a['percentile'] - expected_p) < P_TOLERANCE, \
            f"p={a['percentile']}, expected={expected_p:.4f}"

    def test_male_birth_below_median(self):
        """Below-median weight: negative z, low percentile. Catches CDF sign bug."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L, M, S = interpolate_lms(0, who_data)
        expected_z = compute_zscore(2.5, L, M, S)
        expected_p = normal_cdf(expected_z)

        patients = [{
            "id": "T3", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": 2.5}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None
        assert abs(a['z_score'] - expected_z) < Z_TOLERANCE, \
            f"z={a['z_score']}, expected={expected_z:.4f}"
        assert a['percentile'] is not None
        assert abs(a['percentile'] - expected_p) < P_TOLERANCE, \
            f"p={a['percentile']}, expected={expected_p:.4f}"

    def test_female_birth_median(self):
        """Female chart data must load correctly (different gender code)."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'f')
        L, M, S = interpolate_lms(0, who_data)

        patients = [{
            "id": "T4", "ga_birth": 40, "sex": "f",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": M}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None, \
            "Female z_score is null — gender filter likely broken"
        assert abs(a['z_score']) < Z_TOLERANCE


class TestInterpolation:
    """Tests for linear interpolation at non-tabulated ages."""

    def test_interpolated_age_median(self):
        """At a non-tabulated age, interpolated median should yield z~0."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        lms = interpolate_lms(5.5, who_data)
        assert lms is not None, "WHO data should cover 5.5 months"
        L, M, S = lms

        pma = 40 + 5.5 * 30.4375 / 7

        patients = [{
            "id": "T5", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": pma, "measure_type": "weight", "value": M}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None
        assert abs(a['z_score']) < Z_TOLERANCE, \
            f"At interpolated median, z should be ~0, got {a['z_score']}"


class TestFentonPreterm:
    """Tests for Fenton 2013 preterm chart routing."""

    def test_fenton_preterm_median(self):
        """Fenton median at a tabulated preterm age should give z~0."""
        fenton_data = read_lms_data(
            '/app/data/fenton2013.csv', 'fenton_2013', 'weight', 'm')
        assert len(fenton_data) > 0, "Fenton male weight data must exist"

        target_age = None
        target_M = None
        for d in fenton_data:
            if abs(d['age'] - 30) < 0.05:
                target_age = d['age']
                target_M = d['M']
                break
        assert target_age is not None, "Fenton data near 30 weeks expected"

        patients = [{
            "id": "T6", "ga_birth": 28, "sex": "m",
            "measurements": [
                {"pma_weeks": target_age, "measure_type": "weight",
                 "value": target_M}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None, "Fenton z_score must not be null"
        assert abs(a['z_score']) < Z_TOLERANCE
        assert a['chart_used'] == 'fenton_2013'


class TestTransition:
    """Tests for Fenton-to-WHO chart transition blending."""

    def test_fenton_who_blend_at_45_weeks(self):
        """At PMA=45 (midpoint), blend should be 50/50 Fenton+WHO."""
        fenton_data = read_lms_data(
            '/app/data/fenton2013.csv', 'fenton_2013', 'weight', 'm')
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')

        fenton_lms = interpolate_lms(45, fenton_data)
        who_months = pma_to_months(45)
        who_lms = interpolate_lms(who_months, who_data)

        assert fenton_lms is not None, "Fenton data at 45 weeks required"
        assert who_lms is not None, "WHO data at corrected age required"

        fL, fM, fS = fenton_lms
        wL, wM, wS = who_lms
        test_value = fM

        z_fenton = compute_zscore(test_value, fL, fM, fS)
        z_who = compute_zscore(test_value, wL, wM, wS)
        w_who = (45 - 40) / 10.0
        expected_z = (1 - w_who) * z_fenton + w_who * z_who

        patients = [{
            "id": "T7", "ga_birth": 28, "sex": "m",
            "measurements": [
                {"pma_weeks": 45, "measure_type": "weight",
                 "value": test_value}
            ]
        }]
        results = run_engine(patients)
        a = results[0]['assessments'][0]
        assert a['z_score'] is not None, "Transition z_score must not be null"
        assert abs(a['z_score'] - expected_z) < Z_TOLERANCE, \
            f"z={a['z_score']}, expected={expected_z:.4f}"
        assert a['chart_used'] == 'fenton_who_blend'


class TestPercentileCrossing:
    """Tests for percentile crossing detection."""

    def test_crossing_detected(self):
        """Growth from 50th to below 3rd should cross multiple lines."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L0, M0, S0 = interpolate_lms(0, who_data)
        pma_6 = 40 + 6 * 30.4375 / 7

        patients = [{
            "id": "T8", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": M0},
                {"pma_weeks": pma_6, "measure_type": "weight", "value": 6.0}
            ]
        }]
        results = run_engine(patients)

        assert results[0]['assessments'][0]['z_score'] is not None
        assert results[0]['assessments'][1]['z_score'] is not None

        crossings = results[0]['crossings']
        assert len(crossings) > 0, "Should detect at least one crossing"

        crossed = [c['percentile_crossed'] for c in crossings]
        assert 50 in crossed, "Should cross 50th percentile"
        assert 10 in crossed, "Should cross 10th percentile"

        for c in crossings:
            assert c['direction'] == 'down', \
                "All crossings should be downward"


class TestLZeroEdgeCase:
    """Tests for the L=0 special case in the LMS formula."""

    def test_l_zero_zscore(self):
        """lms_zscore with L=0 must return ln(x/M)/S, not NaN."""
        r_code = (
            'source("/app/growth_engine.R")\n'
            'z <- lms_zscore(x=10, L=0, M=9, S=0.1)\n'
            'if (is.na(z) || is.nan(z)) {\n'
            '  cat("FAIL\\n")\n'
            '} else {\n'
            '  cat(sprintf("%.10f\\n", z))\n'
            '}\n'
        )
        with open('/tmp/test_l0.R', 'w') as f:
            f.write(r_code)

        result = subprocess.run(
            ['Rscript', '/tmp/test_l0.R'],
            capture_output=True, text=True, timeout=15
        )

        assert result.returncode == 0, \
            f"R script failed: {result.stderr}"
        output = result.stdout.strip()
        assert output != "FAIL", \
            "lms_zscore(L=0) returned NA/NaN — L=0 case not handled"

        z = float(output)
        expected_z = math.log(10.0 / 9.0) / 0.1
        assert abs(z - expected_z) < Z_TOLERANCE, \
            f"L=0 z-score: got {z}, expected {expected_z:.6f}"


class TestGrowthVelocity:
    """Tests for growth velocity computation."""

    def test_velocities_present_in_output(self):
        """Output must include a 'velocities' key for each patient."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L0, M0, S0 = interpolate_lms(0, who_data)

        patients = [{
            "id": "V0", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": M0}
            ]
        }]
        results = run_engine(patients)
        assert 'velocities' in results[0], \
            "Output must include 'velocities' key"

    def test_velocity_rapid_loss(self):
        """Rapid weight drop should produce rapid_loss flag."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L0, M0, S0 = interpolate_lms(0, who_data)

        pma_later = 44  # 4 weeks after birth
        who_months_later = pma_to_months(pma_later)
        lms_later = interpolate_lms(who_months_later, who_data)
        assert lms_later is not None
        L1, M1, S1 = lms_later

        # Use 70% of median at 4 weeks — very underweight
        low_weight = M1 * 0.7

        z1 = compute_zscore(M0, L0, M0, S0)  # ~0 at birth median
        z2 = compute_zscore(low_weight, L1, M1, S1)

        expected_delta_z = z2 - z1
        expected_rate = expected_delta_z / (pma_later - 40)

        assert expected_rate < -0.1, \
            f"Test setup: rate {expected_rate} should be < -0.1"

        patients = [{
            "id": "V1", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": M0},
                {"pma_weeks": pma_later, "measure_type": "weight",
                 "value": low_weight}
            ]
        }]
        results = run_engine(patients)

        velocities = results[0].get('velocities', [])
        assert len(velocities) == 1, \
            f"Expected 1 velocity entry, got {len(velocities)}"

        v = velocities[0]
        assert v['measure_type'] == 'weight'
        assert v['from_pma'] == 40
        assert v['to_pma'] == pma_later
        assert abs(v['delta_z'] - expected_delta_z) < 0.05, \
            f"delta_z={v['delta_z']}, expected={expected_delta_z:.4f}"
        assert abs(v['delta_z_per_week'] - expected_rate) < 0.02, \
            f"rate={v['delta_z_per_week']}, expected={expected_rate:.4f}"
        assert v['flag'] == 'rapid_loss', \
            f"Expected rapid_loss, got {v['flag']}"

    def test_velocity_normal_tracking(self):
        """Growth tracking the median should produce normal flag."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L0, M0, S0 = interpolate_lms(0, who_data)

        pma_later = 48  # 8 weeks after birth
        who_months_later = pma_to_months(pma_later)
        lms_later = interpolate_lms(who_months_later, who_data)
        assert lms_later is not None
        L1, M1, S1 = lms_later

        # Both at median → z ≈ 0, delta_z ≈ 0
        z1 = compute_zscore(M0, L0, M0, S0)
        z2 = compute_zscore(M1, L1, M1, S1)

        expected_delta_z = z2 - z1
        expected_rate = expected_delta_z / (pma_later - 40)

        patients = [{
            "id": "V2", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight", "value": M0},
                {"pma_weeks": pma_later, "measure_type": "weight",
                 "value": M1}
            ]
        }]
        results = run_engine(patients)

        velocities = results[0].get('velocities', [])
        assert len(velocities) == 1
        v = velocities[0]
        assert abs(v['delta_z'] - expected_delta_z) < 0.05
        assert v['flag'] == 'normal', \
            f"Expected normal, got {v['flag']}"

    def test_velocity_rapid_gain(self):
        """Rapid weight gain should produce rapid_gain flag."""
        who_data = read_lms_data(
            '/app/data/charts_long.csv', 'who_2006_infant', 'weight', 'm')
        L0, M0, S0 = interpolate_lms(0, who_data)

        pma_later = 44  # 4 weeks after birth
        who_months_later = pma_to_months(pma_later)
        lms_later = interpolate_lms(who_months_later, who_data)
        assert lms_later is not None
        L1, M1, S1 = lms_later

        # Start low (70% of birth median), end high (115% of 4-week median)
        low_birth = M0 * 0.7
        high_later = M1 * 1.15

        z1 = compute_zscore(low_birth, L0, M0, S0)
        z2 = compute_zscore(high_later, L1, M1, S1)

        expected_delta_z = z2 - z1
        expected_rate = expected_delta_z / (pma_later - 40)

        assert expected_rate > 0.1, \
            f"Test setup: rate {expected_rate} should be > 0.1"

        patients = [{
            "id": "V3", "ga_birth": 40, "sex": "m",
            "measurements": [
                {"pma_weeks": 40, "measure_type": "weight",
                 "value": low_birth},
                {"pma_weeks": pma_later, "measure_type": "weight",
                 "value": high_later}
            ]
        }]
        results = run_engine(patients)

        velocities = results[0].get('velocities', [])
        assert len(velocities) == 1
        v = velocities[0]
        assert abs(v['delta_z'] - expected_delta_z) < 0.05, \
            f"delta_z={v['delta_z']}, expected={expected_delta_z:.4f}"
        assert v['flag'] == 'rapid_gain', \
            f"Expected rapid_gain, got {v['flag']}"
