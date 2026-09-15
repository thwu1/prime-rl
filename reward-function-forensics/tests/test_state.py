"""Tests for reward function forensics and configuration design task.

"""

import json
import os
import sqlite3
import sys

import numpy as np
import pytest

sys.path.insert(0, '/app')


class TestGaussianSigmoid:
    """Verify the Gaussian sigmoid implementation is correct."""

    def test_gaussian_at_margin(self):
        """Gaussian sigmoid must return value_at_1 when x == 1."""
        from reward_system import _sigmoids
        val = _sigmoids(1.0, 0.1, "gaussian")
        assert abs(val - 0.1) < 1e-6, (
            f"Gaussian sigmoid at x=1 with value_at_1=0.1 should return 0.1, "
            f"got {val:.6f}"
        )

    def test_gaussian_at_zero(self):
        """Gaussian sigmoid must return 1.0 when x == 0."""
        from reward_system import _sigmoids
        val = _sigmoids(0.0, 0.1, "gaussian")
        assert abs(val - 1.0) < 1e-6, (
            f"Gaussian sigmoid at x=0 should return 1.0, got {val:.6f}"
        )

    def test_gaussian_monotone_decay(self):
        """Gaussian sigmoid must strictly decrease for increasing x > 0."""
        from reward_system import _sigmoids
        vals = [_sigmoids(x, 0.1, "gaussian") for x in [0.0, 0.5, 1.0, 2.0, 3.0]]
        for i in range(len(vals) - 1):
            assert vals[i] > vals[i + 1], (
                f"Gaussian must be monotone decreasing: "
                f"f({[0, 0.5, 1, 2, 3][i]})={vals[i]:.6f} <= "
                f"f({[0, 0.5, 1, 2, 3][i+1]})={vals[i+1]:.6f}"
            )

    def test_gaussian_specific_value(self):
        """Verify Gaussian sigmoid at x=0.5 with known scale."""
        from reward_system import _sigmoids
        val = _sigmoids(0.5, 0.1, "gaussian")
        scale = np.sqrt(-2 * np.log(0.1))
        expected = np.exp(-0.5 * (0.5 * scale) ** 2)
        assert abs(val - expected) < 1e-6, (
            f"Gaussian at x=0.5: expected {expected:.6f}, got {val:.6f}. "
            f"Scale should be sqrt(-2*ln(0.1))={scale:.4f}"
        )


class TestToleranceFunction:
    """Verify the tolerance function computes correctly."""

    def test_in_bounds_returns_one(self):
        from reward_system import tolerance
        assert tolerance(0.5, bounds=(0.0, 1.0), margin=1.0) == 1.0

    def test_at_lower_bound(self):
        from reward_system import tolerance
        assert tolerance(0.0, bounds=(0.0, 1.0), margin=1.0) == 1.0

    def test_at_upper_bound(self):
        from reward_system import tolerance
        assert tolerance(1.0, bounds=(0.0, 1.0), margin=1.0) == 1.0

    def test_above_upper_bound(self):
        """x > upper should decay via sigmoid with d = (x - upper) / margin."""
        from reward_system import tolerance
        val = tolerance(1.5, bounds=(0.0, 1.0), margin=1.0, sigmoid="gaussian")
        # d = (1.5 - 1.0) / 1.0 = 0.5
        scale = np.sqrt(-2 * np.log(0.1))
        expected = np.exp(-0.5 * (0.5 * scale) ** 2)
        assert abs(val - expected) < 1e-6, (
            f"tolerance(1.5, (0,1), margin=1): expected {expected:.6f}, got {val:.6f}"
        )

    def test_below_lower_bound(self):
        """x < lower should decay via sigmoid with d = (lower - x) / margin."""
        from reward_system import tolerance
        val = tolerance(-0.3, bounds=(0.0, 1.0), margin=1.0, sigmoid="gaussian")
        scale = np.sqrt(-2 * np.log(0.1))
        expected = np.exp(-0.5 * (0.3 * scale) ** 2)
        assert abs(val - expected) < 1e-6, (
            f"tolerance(-0.3, (0,1), margin=1): expected {expected:.6f}, got {val:.6f}"
        )

    def test_zero_margin_binary(self):
        from reward_system import tolerance
        assert tolerance(0.5, bounds=(0.0, 1.0), margin=0.0) == 1.0
        assert tolerance(1.5, bounds=(0.0, 1.0), margin=0.0) == 0.0


class TestTrackingLinVel:
    """Verify tracking_lin_vel uses squared L2 error."""

    def test_perfect_tracking(self):
        from reward_system import RewardComputer
        rc = RewardComputer(sigma=0.25)
        cmd = np.array([1.0, 0.5, 0.3])
        vel = np.array([1.0, 0.5, 999.0])  # z is ignored
        val = rc.tracking_lin_vel(cmd, vel)
        assert abs(val - 1.0) < 1e-6, (
            f"Perfect xy tracking should give 1.0, got {val:.6f}"
        )

    def test_known_error(self):
        """Error should be sum of squared differences in xy."""
        from reward_system import RewardComputer
        rc = RewardComputer(sigma=0.25)
        cmd = np.array([1.0, 0.0, 0.0])
        vel = np.array([0.5, 0.3, 0.0])
        # Correct: error = (1.0-0.5)^2 + (0.0-0.3)^2 = 0.25 + 0.09 = 0.34
        expected = np.exp(-0.34 / 0.25)
        val = rc.tracking_lin_vel(cmd, vel)
        assert abs(val - expected) < 1e-6, (
            f"tracking_lin_vel: expected {expected:.6f} (squared L2 error=0.34), "
            f"got {val:.6f}"
        )

    def test_symmetric_error(self):
        """Verify squared error (not absolute): opposite-sign errors combine."""
        from reward_system import RewardComputer
        rc = RewardComputer(sigma=0.25)
        cmd = np.array([0.0, 0.0, 0.0])
        vel1 = np.array([0.5, 0.5, 0.0])
        vel2 = np.array([-0.5, -0.5, 0.0])
        # Both should give the same tracking reward (squared L2 is symmetric)
        v1 = rc.tracking_lin_vel(cmd, vel1)
        v2 = rc.tracking_lin_vel(cmd, vel2)
        assert abs(v1 - v2) < 1e-6, (
            f"Squared L2 should be symmetric: vel1 gives {v1:.6f}, vel2 gives {v2:.6f}"
        )
        # error = 0.25 + 0.25 = 0.5
        expected = np.exp(-0.5 / 0.25)
        assert abs(v1 - expected) < 1e-6


class TestAngVelXY:
    """Verify cost_ang_vel_xy only penalizes roll/pitch, not yaw."""

    def test_pure_yaw_zero_cost(self):
        """Pure yaw rotation should have zero ang_vel_xy cost."""
        from reward_system import RewardComputer
        rc = RewardComputer()
        angvel = np.array([0.0, 0.0, 5.0])
        val = rc.cost_ang_vel_xy(angvel)
        assert abs(val) < 1e-10, (
            f"cost_ang_vel_xy should be 0 for pure yaw (z-axis rotation), got {val}. "
            f"Ensure only indices [0:2] (roll, pitch) are penalized — yaw is "
            f"handled separately by tracking_ang_vel."
        )

    def test_roll_pitch_only(self):
        """Roll/pitch with zero yaw should give sum of squared xy components."""
        from reward_system import RewardComputer
        rc = RewardComputer()
        angvel = np.array([0.3, 0.4, 0.0])
        val = rc.cost_ang_vel_xy(angvel)
        expected = 0.3**2 + 0.4**2  # 0.25
        assert abs(val - expected) < 1e-10, (
            f"cost_ang_vel_xy([0.3, 0.4, 0]) should be {expected}, got {val}"
        )

    def test_yaw_component_excluded(self):
        """Adding yaw rotation should not change the cost."""
        from reward_system import RewardComputer
        rc = RewardComputer()
        angvel_no_yaw = np.array([0.3, 0.4, 0.0])
        angvel_with_yaw = np.array([0.3, 0.4, 10.0])
        v1 = rc.cost_ang_vel_xy(angvel_no_yaw)
        v2 = rc.cost_ang_vel_xy(angvel_with_yaw)
        assert abs(v1 - v2) < 1e-10, (
            f"Yaw component must not affect ang_vel_xy cost: "
            f"without yaw = {v1:.6f}, with yaw = {v2:.6f}. "
            f"The z-component of angular velocity is yaw rate, which is "
            f"tracked by tracking_ang_vel, not penalized here."
        )


class TestGaitBezier:
    """Verify cubic Bezier interpolation and gait trajectory."""

    def test_bezier_at_zero(self):
        from gait_utils import cubic_bezier_interpolation
        assert abs(cubic_bezier_interpolation(0.0, 1.0, 0.0) - 0.0) < 1e-10

    def test_bezier_at_one(self):
        from gait_utils import cubic_bezier_interpolation
        assert abs(cubic_bezier_interpolation(0.0, 1.0, 1.0) - 1.0) < 1e-10

    def test_bezier_at_half(self):
        from gait_utils import cubic_bezier_interpolation
        val = cubic_bezier_interpolation(0.0, 1.0, 0.5)
        assert abs(val - 0.5) < 1e-10, f"Bezier at x=0.5 should be 0.5, got {val}"

    def test_bezier_at_quarter(self):
        """Critical test: distinguishes correct x^2*(1-x) from wrong x*(1-x)^2."""
        from gait_utils import cubic_bezier_interpolation
        val = cubic_bezier_interpolation(0.0, 1.0, 0.25)
        # Correct: 0.25^3 + 3*(0.25^2 * 0.75) = 0.015625 + 0.140625 = 0.15625
        expected = 0.15625
        assert abs(val - expected) < 1e-6, (
            f"Bezier at x=0.25: expected {expected}, got {val:.6f}. "
            f"Check that the formula uses x^2*(1-x), not x*(1-x)^2."
        )

    def test_bezier_at_three_quarters(self):
        from gait_utils import cubic_bezier_interpolation
        val = cubic_bezier_interpolation(0.0, 1.0, 0.75)
        # Correct: 0.75^3 + 3*(0.75^2 * 0.25) = 0.421875 + 0.421875 = 0.84375
        expected = 0.84375
        assert abs(val - expected) < 1e-6, (
            f"Bezier at x=0.75: expected {expected}, got {val:.6f}"
        )

    def test_get_rz_at_peak(self):
        """At phi=0 (x=0.5), foot should be at swing_height."""
        from gait_utils import get_rz
        val = get_rz(0.0, 0.08)
        assert abs(val - 0.08) < 1e-6, (
            f"get_rz(0, 0.08) should return 0.08 (peak), got {val}"
        )

    def test_get_rz_at_quarter_phase(self):
        """At phi=-3pi/4 (x=0.125), verify against correct bezier."""
        from gait_utils import get_rz
        phi = -3 * np.pi / 4
        val = get_rz(phi, 0.08)
        # x = (phi + pi)/(2*pi) = (pi/4)/(2*pi) = 0.125
        # stance phase (x <= 0.5): bezier(0, 0.08, 2*0.125=0.25)
        # correct bezier(0,0.08,0.25) = 0.08 * 0.15625 = 0.0125
        expected = 0.0125
        assert abs(val - expected) < 1e-6, (
            f"get_rz(-3pi/4, 0.08): expected {expected}, got {val:.6f}"
        )


class TestConfigRecovery:
    """Verify the recovered reward weight configuration."""

    TRUE_WEIGHTS = {
        'tracking_lin_vel': 1.5,
        'tracking_ang_vel': 0.75,
        'lin_vel_z': -0.8,
        'ang_vel_xy': -0.05,
        'orientation': -3.0,
        'action_rate': -0.015,
        'torques': -0.0003,
        'joint_limits': -1.0,
        'feet_air_time': 0.12,
        'feet_clearance': -2.5,
    }

    def test_config_file_exists(self):
        assert os.path.exists('/app/results/config.json'), (
            "Config file /app/results/config.json not found"
        )

    def test_config_format(self):
        with open('/app/results/config.json') as f:
            config = json.load(f)
        assert 'weights' in config, "Config must contain 'weights' key"
        assert 'sigma' in config, "Config must contain 'sigma' key"
        assert 'dt' in config, "Config must contain 'dt' key"
        assert abs(config['sigma'] - 0.25) < 0.01, (
            f"sigma should be 0.25, got {config['sigma']}"
        )
        assert abs(config['dt'] - 0.02) < 0.001, (
            f"dt should be 0.02, got {config['dt']}"
        )

    def test_all_weight_keys_present(self):
        with open('/app/results/config.json') as f:
            config = json.load(f)
        for name in self.TRUE_WEIGHTS:
            assert name in config['weights'], f"Missing weight key: {name}"

    def test_recovered_weights_accuracy(self):
        with open('/app/results/config.json') as f:
            config = json.load(f)
        weights = config['weights']

        for name, true_val in self.TRUE_WEIGHTS.items():
            recovered = weights[name]
            tol = max(abs(true_val) * 0.05, 0.02)
            assert abs(recovered - true_val) < tol, (
                f"Weight '{name}': expected {true_val:.6f}, "
                f"got {recovered:.6f} (tolerance={tol:.6f})"
            )

    def test_reward_reconstruction(self):
        """Recomputed rewards from fixed code + recovered weights must match."""
        with open('/app/results/config.json') as f:
            config = json.load(f)

        from reward_system import RewardComputer
        rc = RewardComputer(
            sigma=config['sigma'],
            swing_height=config.get('swing_height', 0.08),
        )

        data = np.load('/app/data/trajectory.npz')
        ref_rewards = np.load('/app/data/reference_rewards.npy')
        dt = config['dt']
        weights = config['weights']

        max_err = 0.0
        for t in range(len(ref_rewards)):
            components = rc.compute_all(
                commands=data['commands'][t],
                local_vel=data['local_vel'][t],
                ang_vel=data['ang_vel'][t],
                global_linvel=data['global_linvel'][t],
                global_angvel=data['global_angvel'][t],
                up_vector=data['up_vector'][t],
                actions=data['actions'][t],
                prev_actions=data['prev_actions'][t],
                actuator_force=data['actuator_force'][t],
                joint_pos=data['joint_pos'][t],
                soft_lowers=data['soft_lowers'],
                soft_uppers=data['soft_uppers'],
                air_time=data['air_time'][t],
                first_contact=data['first_contact'][t],
                foot_z=data['foot_z'][t],
                foot_vel=data['foot_vel'][t],
                gait_phase=data['gait_phase'][t],
            )
            total = sum(weights[k] * v for k, v in components.items())
            total = np.clip(total * dt, 0.0, 10000.0)
            err = abs(float(total) - float(ref_rewards[t]))
            max_err = max(max_err, err)

        assert max_err < 1e-4, (
            f"Reconstructed rewards deviate from reference by {max_err:.6e} "
            f"(threshold: 1e-4)"
        )


class TestTrainingHistoryAnalysis:
    """Verify the training history audit results."""

    EXPECTED_ANCESTOR_ID = 14
    EXPECTED_PARETO_IDS = {8, 14, 19, 20}

    # Weight bounds from runs with gait_quality_score > 0.7
    # Filtered runs: 8, 11, 14, 16, 17, 19, 20
    EXPECTED_BOUNDS = {
        'tracking_lin_vel': [1.4, 2.1],
        'tracking_ang_vel': [0.68, 1.05],
        'lin_vel_z': [-0.86, -0.6],
        'ang_vel_xy': [-0.055, -0.038],
        'orientation': [-3.2, -2.4],
        'action_rate': [-0.016, -0.01],
        'torques': [-0.00034, -0.0002],
        'joint_limits': [-1.1, -0.7],
        'feet_air_time': [0.11, 0.155],
        'feet_clearance': [-2.65, -1.9],
    }

    def test_analysis_file_exists(self):
        assert os.path.exists('/app/results/analysis.json'), (
            "Analysis file /app/results/analysis.json not found"
        )

    def test_analysis_format(self):
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        required_keys = ['ancestor_run_id', 'weight_bounds',
                         'pareto_front_run_ids', 'component_sensitivity']
        for key in required_keys:
            assert key in analysis, f"analysis.json missing required key: {key}"

    def test_ancestor_run_id(self):
        """The ancestor must be the run closest in L2 weight space."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        assert analysis['ancestor_run_id'] == self.EXPECTED_ANCESTOR_ID, (
            f"Expected ancestor run_id={self.EXPECTED_ANCESTOR_ID}, "
            f"got {analysis['ancestor_run_id']}"
        )

    def test_pareto_front_membership(self):
        """Pareto front on (avg_episode_return, sim_to_real_transfer_score)."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        computed = set(analysis['pareto_front_run_ids'])
        assert computed == self.EXPECTED_PARETO_IDS, (
            f"Expected Pareto front {sorted(self.EXPECTED_PARETO_IDS)}, "
            f"got {sorted(computed)}"
        )

    def test_pareto_front_sorted(self):
        """Pareto front IDs must be sorted ascending."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        ids = analysis['pareto_front_run_ids']
        assert ids == sorted(ids), (
            f"Pareto front IDs must be sorted ascending, got {ids}"
        )

    def test_weight_bounds_keys(self):
        """All 10 reward component bounds must be present."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        bounds = analysis['weight_bounds']
        for name in self.EXPECTED_BOUNDS:
            assert name in bounds, f"Missing weight bound: {name}"
            assert isinstance(bounds[name], list) and len(bounds[name]) == 2, (
                f"Bound for {name} must be [min, max], got {bounds[name]}"
            )

    def test_weight_bounds_accuracy(self):
        """Weight bounds must match expected min/max from quality-filtered runs."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        bounds = analysis['weight_bounds']
        for name, expected in self.EXPECTED_BOUNDS.items():
            assert abs(bounds[name][0] - expected[0]) < 1e-6, (
                f"Weight bound min for {name}: expected {expected[0]}, "
                f"got {bounds[name][0]}"
            )
            assert abs(bounds[name][1] - expected[1]) < 1e-6, (
                f"Weight bound max for {name}: expected {expected[1]}, "
                f"got {bounds[name][1]}"
            )

    def test_component_sensitivity_keys(self):
        """All 10 component sensitivity values must be present."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        sens = analysis['component_sensitivity']
        for name in self.EXPECTED_BOUNDS:
            assert name in sens, f"Missing sensitivity for: {name}"
            assert isinstance(sens[name], (int, float)), (
                f"Sensitivity for {name} must be numeric, got {type(sens[name])}"
            )
            assert sens[name] > 0, (
                f"Sensitivity for {name} must be positive, got {sens[name]}"
            )

    def test_component_sensitivity_least(self):
        """The least sensitive component should be orientation."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        sens = analysis['component_sensitivity']
        min_key = min(sens, key=sens.get)
        assert min_key == 'orientation', (
            f"Least sensitive component should be 'orientation', got '{min_key}' "
            f"(value={sens[min_key]:.6f}). Orientation CV={sens.get('orientation', 'N/A')}"
        )

    def test_component_sensitivity_most(self):
        """The most sensitive component should be torques."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        sens = analysis['component_sensitivity']
        max_key = max(sens, key=sens.get)
        assert max_key == 'torques', (
            f"Most sensitive component should be 'torques', got '{max_key}' "
            f"(value={sens[max_key]:.6f}). Torques CV={sens.get('torques', 'N/A')}"
        )

    def test_component_sensitivity_range(self):
        """All sensitivity values should be in a reasonable range."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        sens = analysis['component_sensitivity']
        for name, val in sens.items():
            assert 0.05 < val < 0.5, (
                f"Sensitivity for {name}={val:.6f} outside expected range (0.05, 0.5)"
            )


class TestHypervolumeIndicator:
    """Verify the hypervolume indicator of the Pareto front."""

    REFERENCE_POINT = (38.5, 0.28)

    def test_hypervolume_exists(self):
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        assert 'hypervolume_indicator' in analysis, (
            "analysis.json must contain 'hypervolume_indicator'"
        )
        assert isinstance(analysis['hypervolume_indicator'], (int, float)), (
            "hypervolume_indicator must be numeric"
        )

    def test_hypervolume_positive(self):
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        assert analysis['hypervolume_indicator'] > 0, (
            "Hypervolume must be positive"
        )

    def test_hypervolume_value(self):
        """Verify hypervolume matches independent computation from database."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/data/training_history.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT run_id, avg_episode_return, sim_to_real_transfer_score "
            "FROM training_runs ORDER BY run_id"
        )
        runs = cursor.fetchall()
        conn.close()

        # Independently compute Pareto front
        pareto = []
        for run_id, ret, trans in runs:
            dominated = False
            for _, r2, t2 in runs:
                if r2 > ret and t2 > trans:
                    dominated = True
                    break
            if not dominated:
                pareto.append((ret, trans))

        # Sort by return descending for sweep-line hypervolume
        pareto.sort(key=lambda p: -p[0])

        ref_r, ref_t = self.REFERENCE_POINT
        hv = 0.0
        for i, (ret, trans) in enumerate(pareto):
            next_ret = pareto[i + 1][0] if i + 1 < len(pareto) else ref_r
            hv += (ret - next_ret) * (trans - ref_t)

        assert abs(analysis['hypervolume_indicator'] - hv) < 0.01, (
            f"Hypervolume: expected {hv:.4f}, got {analysis['hypervolume_indicator']:.4f}. "
            f"Reference point is {self.REFERENCE_POINT}."
        )


class TestDesignedConfig:
    """Verify the designed configuration via maximin optimization."""

    def test_designed_config_exists(self):
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        assert 'designed_config' in analysis, (
            "analysis.json must contain 'designed_config'"
        )
        dc = analysis['designed_config']
        assert 'blending_weights' in dc, "designed_config missing 'blending_weights'"
        assert 'maximin_objective' in dc, "designed_config missing 'maximin_objective'"
        assert 'weights' in dc, "designed_config missing 'weights'"

    def test_blending_weights_valid(self):
        """Blending weights must be non-negative and sum to 1."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        bw = analysis['designed_config']['blending_weights']

        assert len(bw) > 0, "Blending weights must not be empty"
        total = sum(bw.values())
        assert abs(total - 1.0) < 1e-4, (
            f"Blending weights must sum to 1.0, got {total:.6f}"
        )
        for run_id, w in bw.items():
            assert w >= -1e-8, (
                f"Blending weight for run {run_id} must be non-negative, got {w}"
            )

    def test_blending_uses_pareto_only(self):
        """Only Pareto-optimal runs may have non-zero blending weights."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        pareto_ids = set(str(x) for x in analysis['pareto_front_run_ids'])
        bw = analysis['designed_config']['blending_weights']
        for run_id, w in bw.items():
            if w > 1e-6:
                assert run_id in pareto_ids, (
                    f"Run {run_id} has blending weight {w:.6f} "
                    f"but is not Pareto-optimal. Only Pareto-optimal "
                    f"runs may be blended."
                )

    def test_maximin_objective_correct(self):
        """The maximin objective must equal min of the two normalized metrics."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/data/training_history.db')
        cursor = conn.cursor()

        pareto_ids = analysis['pareto_front_run_ids']
        bw = analysis['designed_config']['blending_weights']

        returns = {}
        transfers = {}
        for pid in pareto_ids:
            cursor.execute(
                "SELECT avg_episode_return, sim_to_real_transfer_score "
                "FROM training_runs WHERE run_id = ?", (pid,)
            )
            row = cursor.fetchone()
            returns[pid] = row[0]
            transfers[pid] = row[1]
        conn.close()

        max_return = max(returns.values())
        max_transfer = max(transfers.values())

        weighted_return = sum(
            bw.get(str(pid), 0) * returns[pid] / max_return
            for pid in pareto_ids
        )
        weighted_transfer = sum(
            bw.get(str(pid), 0) * transfers[pid] / max_transfer
            for pid in pareto_ids
        )

        expected_obj = min(weighted_return, weighted_transfer)
        reported_obj = analysis['designed_config']['maximin_objective']

        assert abs(reported_obj - expected_obj) < 0.005, (
            f"Maximin objective mismatch: reported {reported_obj:.6f}, "
            f"computed from blending weights {expected_obj:.6f}"
        )

    def test_maximin_better_than_single(self):
        """The blended config must outperform any single Pareto run's maximin."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/data/training_history.db')
        cursor = conn.cursor()

        pareto_ids = analysis['pareto_front_run_ids']
        returns = {}
        transfers = {}
        for pid in pareto_ids:
            cursor.execute(
                "SELECT avg_episode_return, sim_to_real_transfer_score "
                "FROM training_runs WHERE run_id = ?", (pid,)
            )
            row = cursor.fetchone()
            returns[pid] = row[0]
            transfers[pid] = row[1]
        conn.close()

        max_return = max(returns.values())
        max_transfer = max(transfers.values())

        best_single = max(
            min(returns[pid] / max_return, transfers[pid] / max_transfer)
            for pid in pareto_ids
        )

        reported_obj = analysis['designed_config']['maximin_objective']
        assert reported_obj >= best_single - 1e-4, (
            f"Blended maximin {reported_obj:.6f} should be >= "
            f"best single-run maximin {best_single:.6f}"
        )

    def test_maximin_objectives_balanced(self):
        """At the LP optimum, both normalized objectives should be balanced."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/data/training_history.db')
        cursor = conn.cursor()

        pareto_ids = analysis['pareto_front_run_ids']
        bw = analysis['designed_config']['blending_weights']

        returns = {}
        transfers = {}
        for pid in pareto_ids:
            cursor.execute(
                "SELECT avg_episode_return, sim_to_real_transfer_score "
                "FROM training_runs WHERE run_id = ?", (pid,)
            )
            row = cursor.fetchone()
            returns[pid] = row[0]
            transfers[pid] = row[1]
        conn.close()

        max_return = max(returns.values())
        max_transfer = max(transfers.values())

        weighted_return = sum(
            bw.get(str(pid), 0) * returns[pid] / max_return
            for pid in pareto_ids
        )
        weighted_transfer = sum(
            bw.get(str(pid), 0) * transfers[pid] / max_transfer
            for pid in pareto_ids
        )

        assert abs(weighted_return - weighted_transfer) < 0.01, (
            f"At optimum, normalized objectives should be balanced: "
            f"return={weighted_return:.6f}, transfer={weighted_transfer:.6f}. "
            f"Imbalance suggests suboptimal LP solution."
        )

    def test_designed_weights_correct_blend(self):
        """Designed weights must be the correct convex combination of DB weights."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)

        conn = sqlite3.connect('/app/data/training_history.db')
        cursor = conn.cursor()

        bw = analysis['designed_config']['blending_weights']
        designed_weights = analysis['designed_config']['weights']

        weight_names = [
            'tracking_lin_vel', 'tracking_ang_vel', 'lin_vel_z',
            'ang_vel_xy', 'orientation', 'action_rate', 'torques',
            'joint_limits', 'feet_air_time', 'feet_clearance',
        ]

        for wname in weight_names:
            assert wname in designed_weights, (
                f"Designed config missing weight: {wname}"
            )
            expected = 0.0
            col = f'w_{wname}'
            for run_id_str, blend_w in bw.items():
                run_id = int(run_id_str)
                cursor.execute(
                    f"SELECT {col} FROM training_runs WHERE run_id = ?",
                    (run_id,)
                )
                val = cursor.fetchone()[0]
                expected += blend_w * val

            assert abs(designed_weights[wname] - expected) < 1e-3, (
                f"Designed weight '{wname}': expected {expected:.6f} "
                f"(from convex combination), got {designed_weights[wname]:.6f}"
            )
        conn.close()

    def test_designed_weights_all_present(self):
        """All 10 weight components must be present in designed config."""
        with open('/app/results/analysis.json') as f:
            analysis = json.load(f)
        designed_weights = analysis['designed_config']['weights']
        expected_keys = {
            'tracking_lin_vel', 'tracking_ang_vel', 'lin_vel_z',
            'ang_vel_xy', 'orientation', 'action_rate', 'torques',
            'joint_limits', 'feet_air_time', 'feet_clearance',
        }
        assert set(designed_weights.keys()) == expected_keys, (
            f"Designed config weights keys mismatch. "
            f"Expected: {sorted(expected_keys)}, "
            f"Got: {sorted(designed_weights.keys())}"
        )
