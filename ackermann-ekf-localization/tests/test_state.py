"""Tests for sensor integrity evaluation and robust localization."""

import csv
import json
import os
import sqlite3

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Ground truth: compromised landmarks (embedded for verification)
# ---------------------------------------------------------------------------

COMPROMISED_LANDMARK_IDS = {4, 9}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_angle(a):
    """Normalize angle to [-pi, pi)."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def generate_true_trajectory():
    """Deterministic ground truth trajectory (no randomness)."""
    L = 2.5
    dt = 0.1
    N = 500

    states = np.zeros((N + 1, 3))

    for k in range(N):
        t = k * dt
        v = 2.0 + 0.5 * np.sin(0.2 * t)
        delta = 0.05 * np.sin(0.1 * t + 0.3) + 0.03 * np.cos(0.2 * t)

        x, y, theta = states[k]
        states[k + 1, 0] = x + v * np.cos(theta) * dt
        states[k + 1, 1] = y + v * np.sin(theta) * dt
        states[k + 1, 2] = normalize_angle(
            theta + (v / L) * np.tan(delta) * dt
        )

    return states


def dead_reckoning_trajectory():
    """Trajectory from noisy controls alone (no measurement updates)."""
    with open('/app/config.json') as f:
        config = json.load(f)
    L = config['vehicle']['wheelbase']
    dt = config['dt']
    init = config['filter']['initial_state']

    conn = sqlite3.connect('/app/sensor_data.db')
    c = conn.cursor()
    c.execute('SELECT velocity, steering_angle FROM controls ORDER BY timestep')
    controls = [(row[0], row[1]) for row in c.fetchall()]
    conn.close()

    N = len(controls)
    states = np.zeros((N + 1, 3))
    states[0] = init

    for k in range(N):
        v, delta = controls[k]
        x, y, theta = states[k]
        states[k + 1, 0] = x + v * np.cos(theta) * dt
        states[k + 1, 1] = y + v * np.sin(theta) * dt
        states[k + 1, 2] = normalize_angle(
            theta + (v / L) * np.tan(delta) * dt
        )

    return states


def read_trajectory():
    path = '/app/output/trajectory.csv'
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    timesteps = np.array([int(r['timestep']) for r in rows])
    x = np.array([float(r['x']) for r in rows])
    y = np.array([float(r['y']) for r in rows])
    theta = np.array([float(r['theta']) for r in rows])
    return timesteps, x, y, theta


def read_covariance():
    path = '/app/output/covariance.csv'
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    timesteps = np.array([int(r['timestep']) for r in rows])
    P = np.zeros((len(rows), 3, 3))
    for i, r in enumerate(rows):
        P[i, 0, 0] = float(r['P00'])
        P[i, 0, 1] = float(r['P01'])
        P[i, 0, 2] = float(r['P02'])
        P[i, 1, 0] = P[i, 0, 1]
        P[i, 1, 1] = float(r['P11'])
        P[i, 1, 2] = float(r['P12'])
        P[i, 2, 0] = P[i, 0, 2]
        P[i, 2, 1] = P[i, 1, 2]
        P[i, 2, 2] = float(r['P22'])
    return timesteps, P


def read_stats():
    with open('/app/output/stats.json') as f:
        return json.load(f)


def read_diagnosis():
    with open('/app/output/diagnosis.json') as f:
        return json.load(f)


def read_comparison():
    with open('/app/output/comparison.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test: diagnosis of compromised landmarks
# ---------------------------------------------------------------------------

class TestDiagnosis:
    def test_diagnosis_file_exists(self):
        assert os.path.exists('/app/output/diagnosis.json'), \
            "diagnosis.json not found"

    def test_compromised_landmarks_detected(self):
        """Must detect all truly compromised landmarks."""
        diag = read_diagnosis()
        detected = set(diag['compromised_landmarks'])
        missing = COMPROMISED_LANDMARK_IDS - detected
        assert len(missing) == 0, \
            f"Failed to detect compromised landmarks: {missing}"

    def test_no_false_positives(self):
        """Must not flag honest landmarks as compromised."""
        diag = read_diagnosis()
        detected = set(diag['compromised_landmarks'])
        false_pos = detected - COMPROMISED_LANDMARK_IDS
        assert len(false_pos) == 0, \
            f"False positive landmark detections: {false_pos}"

    def test_evidence_present(self):
        """Each compromised landmark must have supporting evidence."""
        diag = read_diagnosis()
        for lm_id in diag['compromised_landmarks']:
            key = str(lm_id)
            assert key in diag['evidence'], \
                f"Missing evidence for landmark {lm_id}"
            ev = diag['evidence'][key]
            assert 'mean_range_innovation' in ev, \
                f"Missing mean_range_innovation for landmark {lm_id}"
            assert 'num_observations' in ev, \
                f"Missing num_observations for landmark {lm_id}"
            assert 'p_value' in ev, \
                f"Missing p_value for landmark {lm_id}"

    def test_p_values_significant(self):
        """Compromised landmarks must have statistically significant bias."""
        diag = read_diagnosis()
        for lm_id in diag['compromised_landmarks']:
            p = diag['evidence'][str(lm_id)]['p_value']
            assert p < 0.01, \
                f"Landmark {lm_id} p_value {p:.6f} not significant (need <0.01)"

    def test_positive_bias_direction(self):
        """Compromised landmarks should show positive range bias."""
        diag = read_diagnosis()
        for lm_id in diag['compromised_landmarks']:
            mri = diag['evidence'][str(lm_id)]['mean_range_innovation']
            assert mri > 0.1, \
                f"Landmark {lm_id} mean_range_innovation {mri:.4f} " \
                f"should be clearly positive"

    def test_sufficient_observations(self):
        """Evidence should be based on adequate sample size."""
        diag = read_diagnosis()
        for lm_id in diag['compromised_landmarks']:
            n = diag['evidence'][str(lm_id)]['num_observations']
            assert n >= 10, \
                f"Landmark {lm_id} only has {n} observations (need >=10)"


# ---------------------------------------------------------------------------
# Test: comparison between baseline and robust filter
# ---------------------------------------------------------------------------

class TestComparison:
    def test_comparison_file_exists(self):
        assert os.path.exists('/app/output/comparison.json'), \
            "comparison.json not found"

    def test_comparison_keys(self):
        comp = read_comparison()
        for key in ['baseline_position_rmse', 'robust_position_rmse',
                     'baseline_heading_rmse', 'robust_heading_rmse']:
            assert key in comp, f"Missing key '{key}' in comparison.json"

    def test_rmse_values_positive(self):
        comp = read_comparison()
        for key in ['baseline_position_rmse', 'robust_position_rmse',
                     'baseline_heading_rmse', 'robust_heading_rmse']:
            assert comp[key] > 0, f"{key} must be positive, got {comp[key]}"

    def test_robust_improvement(self):
        """Robust filter must reduce position RMSE by at least 30%."""
        comp = read_comparison()
        ratio = comp['robust_position_rmse'] / comp['baseline_position_rmse']
        assert ratio < 0.7, \
            f"Robust RMSE {comp['robust_position_rmse']:.4f} is not 30% " \
            f"better than baseline {comp['baseline_position_rmse']:.4f} " \
            f"(ratio={ratio:.3f})"


# ---------------------------------------------------------------------------
# Test: output files exist with correct format
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_trajectory_exists(self):
        assert os.path.exists('/app/output/trajectory.csv'), \
            "trajectory.csv not found"

    def test_covariance_exists(self):
        assert os.path.exists('/app/output/covariance.csv'), \
            "covariance.csv not found"

    def test_stats_exists(self):
        assert os.path.exists('/app/output/stats.json'), \
            "stats.json not found"

    def test_trajectory_row_count(self):
        t, x, y, theta = read_trajectory()
        assert len(t) == 501, f"Expected 501 rows, got {len(t)}"

    def test_trajectory_timesteps(self):
        t, x, y, theta = read_trajectory()
        assert t[0] == 0, f"First timestep should be 0, got {t[0]}"
        assert t[-1] == 500, f"Last timestep should be 500, got {t[-1]}"

    def test_covariance_row_count(self):
        t, P = read_covariance()
        assert len(t) == 501, f"Expected 501 covariance rows, got {len(t)}"


# ---------------------------------------------------------------------------
# Test: trajectory accuracy against ground truth
# ---------------------------------------------------------------------------

class TestTrajectoryAccuracy:
    def test_position_rmse_x(self):
        true = generate_true_trajectory()
        t, x, y, theta = read_trajectory()
        mask = t >= 50
        err = x[mask] - true[t[mask], 0]
        rmse = np.sqrt(np.mean(err ** 2))
        assert rmse < 0.5, f"X RMSE {rmse:.4f} exceeds 0.5 m"

    def test_position_rmse_y(self):
        true = generate_true_trajectory()
        t, x, y, theta = read_trajectory()
        mask = t >= 50
        err = y[mask] - true[t[mask], 1]
        rmse = np.sqrt(np.mean(err ** 2))
        assert rmse < 0.5, f"Y RMSE {rmse:.4f} exceeds 0.5 m"

    def test_heading_rmse(self):
        true = generate_true_trajectory()
        t, x, y, theta = read_trajectory()
        mask = t >= 50
        err = normalize_angle(theta[mask] - true[t[mask], 2])
        rmse = np.sqrt(np.mean(err ** 2))
        assert rmse < 0.15, f"Heading RMSE {rmse:.4f} exceeds 0.15 rad"

    def test_better_than_dead_reckoning(self):
        true = generate_true_trajectory()
        dr = dead_reckoning_trajectory()
        t, x, y, theta = read_trajectory()
        mask = t >= 50
        ekf_err = np.sqrt(
            (x[mask] - true[t[mask], 0]) ** 2 +
            (y[mask] - true[t[mask], 1]) ** 2
        )
        dr_err = np.sqrt(
            (dr[t[mask], 0] - true[t[mask], 0]) ** 2 +
            (dr[t[mask], 1] - true[t[mask], 1]) ** 2
        )
        ekf_rmse = np.sqrt(np.mean(ekf_err ** 2))
        dr_rmse = np.sqrt(np.mean(dr_err ** 2))
        assert ekf_rmse < dr_rmse, \
            f"Filter RMSE ({ekf_rmse:.4f}) not better than DR ({dr_rmse:.4f})"

    def test_final_position(self):
        true = generate_true_trajectory()
        t, x, y, theta = read_trajectory()
        err = np.sqrt(
            (x[-1] - true[-1, 0]) ** 2 + (y[-1] - true[-1, 1]) ** 2
        )
        assert err < 1.0, f"Final position error {err:.4f} m exceeds 1.0 m"


# ---------------------------------------------------------------------------
# Test: filter consistency (NEES) and covariance health
# ---------------------------------------------------------------------------

class TestFilterConsistency:
    def test_nees_in_bounds(self):
        true = generate_true_trajectory()
        t, x, y, theta = read_trajectory()
        t_cov, P = read_covariance()

        nees_list = []
        for i in range(len(t)):
            if t[i] < 50:
                continue
            k = t[i]
            e = np.array([
                x[i] - true[k, 0],
                y[i] - true[k, 1],
                normalize_angle(theta[i] - true[k, 2])
            ])
            try:
                P_inv = np.linalg.inv(P[i])
                nees = float(e.T @ P_inv @ e)
                if np.isfinite(nees):
                    nees_list.append(nees)
            except np.linalg.LinAlgError:
                pass

        assert len(nees_list) > 100, "Too few valid NEES samples"
        mean_nees = np.mean(nees_list)
        assert 0.3 < mean_nees < 10.0, \
            f"Mean NEES {mean_nees:.2f} outside acceptable range [0.3, 10.0]"

    def test_covariance_positive_definite(self):
        t, P = read_covariance()
        for i in range(0, len(t), 25):
            eigvals = np.linalg.eigvalsh(P[i])
            assert np.all(eigvals > 0), \
                f"Covariance not PD at timestep {t[i]}: eigvals={eigvals}"

    def test_covariance_bounded(self):
        t, P = read_covariance()
        for i in range(50, len(t)):
            diag = np.diag(P[i])
            assert np.all(diag > 1e-10), \
                f"Covariance diagonal too small at timestep {t[i]}"
            assert np.all(diag < 100.0), \
                f"Covariance diagonal too large at timestep {t[i]}"


# ---------------------------------------------------------------------------
# Test: trajectory smoothness
# ---------------------------------------------------------------------------

class TestTrajectorySmoothness:
    def test_no_position_jumps(self):
        t, x, y, theta = read_trajectory()
        dt = 0.1
        max_step = 5.0 * dt

        for i in range(1, len(t)):
            if t[i] - t[i - 1] != 1:
                continue
            d = np.sqrt((x[i] - x[i - 1]) ** 2 + (y[i] - y[i - 1]) ** 2)
            assert d < max_step, \
                f"Position jump {d:.4f} m at timestep {t[i]}"

    def test_no_heading_jumps(self):
        t, x, y, theta = read_trajectory()
        dt = 0.1
        max_omega = 2.0

        for i in range(1, len(t)):
            if t[i] - t[i - 1] != 1:
                continue
            dtheta = abs(normalize_angle(theta[i] - theta[i - 1]))
            assert dtheta < max_omega * dt * 2, \
                f"Heading jump {dtheta:.4f} rad at timestep {t[i]}"


# ---------------------------------------------------------------------------
# Test: outlier handling stats
# ---------------------------------------------------------------------------

class TestOutlierHandling:
    def test_stats_keys(self):
        stats = read_stats()
        assert 'outliers_detected' in stats, "Missing 'outliers_detected'"
        assert 'total_observations' in stats, "Missing 'total_observations'"

    def test_outlier_count_reasonable(self):
        stats = read_stats()
        assert stats['outliers_detected'] > 10, \
            f"Too few outliers detected: {stats['outliers_detected']}"
        assert stats['outliers_detected'] < stats['total_observations'] * 0.3, \
            f"Too many outliers: {stats['outliers_detected']}/{stats['total_observations']}"

    def test_total_observations_reasonable(self):
        stats = read_stats()
        assert stats['total_observations'] > 500, \
            f"Too few observations: {stats['total_observations']}"


# ---------------------------------------------------------------------------
# Test: trajectory plot
# ---------------------------------------------------------------------------

class TestPlotOutput:
    def test_plot_exists(self):
        assert os.path.exists('/app/output/trajectory_plot.png'), \
            "trajectory_plot.png not found"

    def test_plot_valid_png(self):
        with open('/app/output/trajectory_plot.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            "trajectory_plot.png is not a valid PNG file"

    def test_plot_reasonable_size(self):
        size = os.path.getsize('/app/output/trajectory_plot.png')
        assert size >= 1000, \
            f"Plot file too small ({size} bytes), likely empty or corrupt"


# ---------------------------------------------------------------------------
# Test: filter_residuals table in SQLite
# ---------------------------------------------------------------------------

class TestResidualTable:
    def test_table_exists(self):
        conn = sqlite3.connect('/app/sensor_data.db')
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='filter_residuals'"
        )
        result = c.fetchone()
        conn.close()
        assert result is not None, \
            "Table 'filter_residuals' not found in sensor_data.db"

    def test_table_columns(self):
        conn = sqlite3.connect('/app/sensor_data.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(filter_residuals)")
        columns = {row[1] for row in c.fetchall()}
        conn.close()
        expected = {
            'timestep', 'landmark_id', 'range_residual',
            'bearing_residual', 'mahalanobis', 'accepted'
        }
        missing = expected - columns
        assert not missing, f"Missing columns in filter_residuals: {missing}"

    def test_table_row_count(self):
        conn = sqlite3.connect('/app/sensor_data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM filter_residuals")
        count = c.fetchone()[0]
        conn.close()
        assert count > 500, \
            f"Expected >500 residual rows, got {count}"

    def test_accepted_binary(self):
        conn = sqlite3.connect('/app/sensor_data.db')
        c = conn.cursor()
        c.execute("SELECT DISTINCT accepted FROM filter_residuals")
        values = {row[0] for row in c.fetchall()}
        conn.close()
        assert values.issubset({0, 1}), \
            f"accepted values should be 0 or 1, got {values}"

    def test_residual_stats_consistency(self):
        """Residual table counts must match stats.json."""
        conn = sqlite3.connect('/app/sensor_data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM filter_residuals WHERE accepted=0")
        db_outliers = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM filter_residuals")
        db_total = c.fetchone()[0]
        conn.close()
        stats = read_stats()
        assert db_outliers == stats['outliers_detected'], \
            f"DB outliers ({db_outliers}) != stats ({stats['outliers_detected']})"
        assert db_total == stats['total_observations'], \
            f"DB total ({db_total}) != stats ({stats['total_observations']})"
