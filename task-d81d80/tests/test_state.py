"""Tests for corrected multi-language EKF-SLAM system.

Verifies that:
1. The C motion model produces correct outputs
2. The EKF-SLAM filter converges to ground truth within specified bounds
3. The comparative filter evaluation produces valid robustness analysis

"""

import ctypes
import json
import os
import pickle
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, '/app')
from ekf_slam import EKFSLAM, normalize_angle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def slam_results():
    """Run EKF-SLAM once and share results across all convergence tests."""
    with open('/app/scenario.pkl', 'rb') as f:
        scenario = pickle.load(f)

    slam = EKFSLAM(
        sigma_v=scenario['sigma_v'],
        sigma_omega=scenario['sigma_omega'],
        sigma_range=scenario['sigma_range'],
        sigma_bearing=scenario['sigma_bearing'],
        n_landmarks=scenario['n_landmarks'],
    )

    controls = scenario['controls']
    observations = scenario['observations']
    dt = scenario['dt']
    n_steps = len(controls)

    slam.update(observations[0])
    estimated_poses = [slam.mu[:3].copy()]

    for t in range(n_steps):
        slam.predict(controls[t], dt)
        slam.update(observations[t + 1])
        estimated_poses.append(slam.mu[:3].copy())

    return slam, np.array(estimated_poses), scenario


@pytest.fixture(scope='module')
def evaluation_report():
    """Run filter_evaluation.py and load the report it produces."""
    script_path = '/app/filter_evaluation.py'
    report_path = '/app/filter_evaluation.json'

    assert os.path.exists(script_path), (
        "/app/filter_evaluation.py does not exist — it must be created"
    )

    # Remove any pre-existing report to ensure fresh generation
    if os.path.exists(report_path):
        os.remove(report_path)

    result = subprocess.run(
        ['python3', script_path],
        capture_output=True, text=True, timeout=300,
        cwd='/app',
    )
    assert result.returncode == 0, (
        f"filter_evaluation.py failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(report_path), (
        "filter_evaluation.py did not create /app/filter_evaluation.json"
    )

    with open(report_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# C motion model tests
# ---------------------------------------------------------------------------

class TestCMotionModel:
    """Verify the C shared library produces correct motion model outputs."""

    def test_forward_motion_at_heading_zero(self):
        """At heading 0, forward motion should increase x, not y."""
        lib = ctypes.CDLL('/app/libmotion.so')
        state = (ctypes.c_double * 3)(0.0, 0.0, 0.0)
        lib.motion_update(state, ctypes.c_double(1.0),
                          ctypes.c_double(0.0), ctypes.c_double(1.0))
        assert state[0] > 0.5, (
            f"At heading 0, x should increase: got x={state[0]:.4f}"
        )
        assert abs(state[1]) < 0.1, (
            f"At heading 0, y should stay near 0: got y={state[1]:.4f}"
        )

    def test_forward_motion_at_heading_pi_half(self):
        """At heading pi/2, forward motion should increase y, not x."""
        lib = ctypes.CDLL('/app/libmotion.so')
        state = (ctypes.c_double * 3)(0.0, 0.0, np.pi / 2)
        lib.motion_update(state, ctypes.c_double(1.0),
                          ctypes.c_double(0.0), ctypes.c_double(1.0))
        assert abs(state[0]) < 0.1, (
            f"At heading pi/2, x should stay near 0: got x={state[0]:.4f}"
        )
        assert state[1] > 0.5, (
            f"At heading pi/2, y should increase: got y={state[1]:.4f}"
        )

    def test_jacobian_consistency(self):
        """Motion Jacobian must be consistent with finite-difference approximation."""
        lib = ctypes.CDLL('/app/libmotion.so')
        v, dt, theta = 1.0, 0.1, 0.7

        # Get analytical Jacobian from C
        jac_buf = (ctypes.c_double * 9)()
        lib.motion_jacobian(jac_buf, ctypes.c_double(v),
                            ctypes.c_double(dt), ctypes.c_double(theta))
        J_analytical = np.array(list(jac_buf)).reshape(3, 3)

        # Finite-difference Jacobian
        eps = 1e-7
        J_numerical = np.zeros((3, 3))
        base_state = np.array([1.0, 2.0, theta])
        for col in range(3):
            sp = base_state.copy()
            sm = base_state.copy()
            sp[col] += eps
            sm[col] -= eps

            bp = (ctypes.c_double * 3)(*sp)
            bm = (ctypes.c_double * 3)(*sm)
            lib.motion_update(bp, ctypes.c_double(v),
                              ctypes.c_double(0.0), ctypes.c_double(dt))
            lib.motion_update(bm, ctypes.c_double(v),
                              ctypes.c_double(0.0), ctypes.c_double(dt))
            fp = np.array([bp[0], bp[1], bp[2]])
            fm = np.array([bm[0], bm[1], bm[2]])
            J_numerical[:, col] = (fp - fm) / (2 * eps)

        np.testing.assert_allclose(J_analytical, J_numerical, atol=1e-4,
                                   err_msg="Motion Jacobian inconsistent with finite differences")


# ---------------------------------------------------------------------------
# Filter convergence tests
# ---------------------------------------------------------------------------

class TestFilterConvergence:
    """Verify the corrected filter converges to ground truth."""

    def test_robot_final_position(self, slam_results):
        """Robot final position estimate must be within 2.0 m of ground truth."""
        slam, est_poses, scenario = slam_results
        true_poses = scenario['true_poses']
        pos_error = np.linalg.norm(est_poses[-1, :2] - true_poses[-1, :2])
        assert pos_error < 2.0, (
            f"Final robot position error {pos_error:.3f} m exceeds 2.0 m"
        )

    def test_robot_final_heading(self, slam_results):
        """Robot final heading estimate must be within 0.3 rad of ground truth."""
        slam, est_poses, scenario = slam_results
        true_poses = scenario['true_poses']
        heading_error = abs(normalize_angle(est_poses[-1, 2] - true_poses[-1, 2]))
        assert heading_error < 0.3, (
            f"Final heading error {heading_error:.3f} rad exceeds 0.3 rad"
        )

    def test_landmark_average_accuracy(self, slam_results):
        """Average landmark position error must be below 1.5 m."""
        slam, _, scenario = slam_results
        true_landmarks = scenario['landmarks']
        errors = []
        for j in range(scenario['n_landmarks']):
            if slam.landmark_observed[j]:
                est_lm = slam.mu[3 + 2 * j: 3 + 2 * j + 2]
                errors.append(np.linalg.norm(est_lm - true_landmarks[j]))
        assert len(errors) > 0, "No landmarks were observed"
        avg_error = np.mean(errors)
        assert avg_error < 1.5, (
            f"Average landmark error {avg_error:.3f} m exceeds 1.5 m"
        )

    def test_landmark_max_accuracy(self, slam_results):
        """No single landmark error should exceed 3.0 m."""
        slam, _, scenario = slam_results
        true_landmarks = scenario['landmarks']
        for j in range(scenario['n_landmarks']):
            if slam.landmark_observed[j]:
                est_lm = slam.mu[3 + 2 * j: 3 + 2 * j + 2]
                err = np.linalg.norm(est_lm - true_landmarks[j])
                assert err < 3.0, (
                    f"Landmark {j} error {err:.3f} m exceeds 3.0 m"
                )

    def test_covariance_positive_semidefinite(self, slam_results):
        """Final covariance matrix must be positive semi-definite."""
        slam, _, _ = slam_results
        eigenvalues = np.linalg.eigvalsh(slam.Sigma)
        min_eig = np.min(eigenvalues)
        assert min_eig > -1e-6, (
            f"Covariance has negative eigenvalue {min_eig:.6e}"
        )

    def test_all_landmarks_observed(self, slam_results):
        """All landmarks in the scenario must be detected and tracked."""
        slam, _, scenario = slam_results
        n_observed = int(np.sum(slam.landmark_observed))
        n_total = scenario['n_landmarks']
        assert n_observed == n_total, (
            f"Only {n_observed}/{n_total} landmarks were observed"
        )

    def test_trajectory_bounded(self, slam_results):
        """Estimated trajectory should not diverge from ground truth."""
        _, est_poses, scenario = slam_results
        true_poses = scenario['true_poses']
        pos_errors = np.linalg.norm(
            est_poses[:, :2] - true_poses[:, :2], axis=1
        )
        max_error = np.max(pos_errors)
        assert max_error < 5.0, (
            f"Trajectory diverged: max position error {max_error:.3f} m "
            f"at step {np.argmax(pos_errors)}"
        )


# ---------------------------------------------------------------------------
# Comparative filter evaluation tests
# ---------------------------------------------------------------------------

class TestFilterEvaluation:
    """Verify the comparative filter evaluation produces valid robustness analysis."""

    def test_report_has_required_top_fields(self, evaluation_report):
        """Report must contain formulations list, recommendation, and rationale."""
        assert 'formulations' in evaluation_report, "Missing 'formulations' field"
        assert isinstance(evaluation_report['formulations'], list)
        assert 'recommended_formulation' in evaluation_report, \
            "Missing 'recommended_formulation'"
        assert isinstance(evaluation_report['recommended_formulation'], str)
        assert 'rationale' in evaluation_report, "Missing 'rationale'"
        assert isinstance(evaluation_report['rationale'], str)

    def test_at_least_two_distinct_formulations(self, evaluation_report):
        """Must compare at least two formulations with distinct names."""
        formulations = evaluation_report['formulations']
        assert len(formulations) >= 2, \
            f"Need >= 2 formulations, got {len(formulations)}"
        names = [f['name'] for f in formulations]
        assert len(set(names)) >= 2, \
            f"Formulation names must be distinct: {names}"

    def test_each_formulation_has_both_conditions(self, evaluation_report):
        """Each formulation must report metrics under clean and corrupted conditions."""
        for f in evaluation_report['formulations']:
            assert 'name' in f and isinstance(f['name'], str), \
                "Each formulation must have a string 'name'"
            assert 'clean' in f and isinstance(f['clean'], dict), \
                f"Formulation '{f.get('name')}' missing 'clean' condition"
            assert 'corrupted' in f and isinstance(f['corrupted'], dict), \
                f"Formulation '{f.get('name')}' missing 'corrupted' condition"

    def test_metrics_have_required_fields(self, evaluation_report):
        """Each condition must contain all required metric fields."""
        required = [
            'position_rmse', 'mean_nis', 'nis_below_95pct',
            'log10_condition_number', 'psd_maintained',
        ]
        for f in evaluation_report['formulations']:
            for cond in ['clean', 'corrupted']:
                for metric in required:
                    assert metric in f[cond], (
                        f"Missing '{metric}' in {f['name']}/{cond}"
                    )

    def test_metric_types(self, evaluation_report):
        """Metric values must have correct types."""
        for f in evaluation_report['formulations']:
            for cond in ['clean', 'corrupted']:
                m = f[cond]
                assert isinstance(m['position_rmse'], (int, float)), \
                    f"position_rmse must be numeric in {f['name']}/{cond}"
                assert isinstance(m['mean_nis'], (int, float)), \
                    f"mean_nis must be numeric in {f['name']}/{cond}"
                assert isinstance(m['nis_below_95pct'], (int, float)), \
                    f"nis_below_95pct must be numeric in {f['name']}/{cond}"
                assert m['log10_condition_number'] is None or \
                    isinstance(m['log10_condition_number'], (int, float)), \
                    f"log10_condition_number must be numeric or null in {f['name']}/{cond}"
                assert isinstance(m['psd_maintained'], bool), \
                    f"psd_maintained must be bool in {f['name']}/{cond}"

    def test_clean_scenario_performance(self, evaluation_report):
        """At least one formulation must achieve reasonable RMSE under clean conditions."""
        best_rmse = min(
            f['clean']['position_rmse']
            for f in evaluation_report['formulations']
        )
        assert best_rmse < 2.0, (
            f"Best clean RMSE {best_rmse:.3f} exceeds 2.0 m"
        )

    def test_clean_nis_consistency(self, evaluation_report):
        """At least one formulation must show NIS consistency under clean conditions."""
        best_pct = max(
            f['clean']['nis_below_95pct']
            for f in evaluation_report['formulations']
        )
        assert best_pct > 80.0, (
            f"Best clean NIS consistency {best_pct:.1f}% below 80%"
        )

    def test_corruption_has_measurable_effect(self, evaluation_report):
        """Corrupted data must measurably degrade at least one formulation."""
        any_degradation = False
        for f in evaluation_report['formulations']:
            cr = f['corrupted']['position_rmse']
            cl = f['clean']['position_rmse']
            if cr > cl * 1.05:
                any_degradation = True
            cn_pct = f['corrupted']['nis_below_95pct']
            cl_pct = f['clean']['nis_below_95pct']
            if cl_pct - cn_pct > 3.0:
                any_degradation = True
        assert any_degradation, (
            "Corruption had no measurable effect on any formulation's metrics"
        )

    def test_psd_maintained_under_clean_conditions(self, evaluation_report):
        """At least one formulation must maintain PSD under clean conditions."""
        any_psd = any(
            f['clean']['psd_maintained']
            for f in evaluation_report['formulations']
        )
        assert any_psd, "No formulation maintained PSD under clean conditions"

    def test_metrics_in_plausible_ranges(self, evaluation_report):
        """All numeric metrics must be in physically plausible ranges."""
        for f in evaluation_report['formulations']:
            for cond in ['clean', 'corrupted']:
                m = f[cond]
                assert 0 < m['position_rmse'] < 200, (
                    f"Implausible RMSE {m['position_rmse']} in {f['name']}/{cond}"
                )
                assert 0 < m['mean_nis'] < 5000, (
                    f"Implausible mean NIS {m['mean_nis']} in {f['name']}/{cond}"
                )
                assert 0 <= m['nis_below_95pct'] <= 100, (
                    f"Implausible NIS% {m['nis_below_95pct']} in {f['name']}/{cond}"
                )

    def test_recommendation_is_valid(self, evaluation_report):
        """Recommendation must name a tested formulation with substantive rationale."""
        names = [f['name'] for f in evaluation_report['formulations']]
        rec = evaluation_report['recommended_formulation']
        assert rec in names, (
            f"Recommended '{rec}' not among tested formulations: {names}"
        )
        rationale = evaluation_report['rationale']
        assert len(rationale) > 20, (
            f"Rationale too short ({len(rationale)} chars) to be substantive"
        )
