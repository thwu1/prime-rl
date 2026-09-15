"""Tests for tidal turbine array wake simulator and layout optimizer."""

import json
import numpy as np
import sys
import os
import yaml
import pytest

sys.path.insert(0, '/app')


def load_config():
    """Load and merge channel + turbine configuration."""
    with open('/app/config.yaml') as f:
        config = yaml.safe_load(f)
    turbine_path = os.path.join('/app', config['turbine_file'])
    with open(turbine_path) as f:
        config['turbine'] = yaml.safe_load(f)
    return config


class TestModuleInterface:
    def test_required_functions_exist(self):
        from tidal_farm import (
            interpolate_coefficient,
            compute_wake_deficit,
            compute_array_power,
            optimize_layout,
        )


class TestInterpolateCoefficient:
    def setup_method(self):
        config = load_config()
        self.speeds = config['turbine']['curves']['speeds']
        self.cp = config['turbine']['curves']['power_coefficients']
        self.ct = config['turbine']['curves']['thrust_coefficients']

    def test_rated_region_cp(self):
        """Cp should be 0.437 throughout the rated region (1.0-3.05 m/s)."""
        from tidal_farm import interpolate_coefficient
        for u in [1.5, 2.0, 2.5, 3.0]:
            cp = interpolate_coefficient(u, self.speeds, self.cp)
            assert abs(cp - 0.437) < 1e-6, f"Cp at {u} m/s should be 0.437, got {cp}"

    def test_rated_region_ct(self):
        """Ct should be ~0.516484 throughout the rated region."""
        from tidal_farm import interpolate_coefficient
        for u in [1.5, 2.0, 2.5, 3.0]:
            ct = interpolate_coefficient(u, self.speeds, self.ct)
            assert abs(ct - 0.516484) < 1e-4, f"Ct at {u} m/s should be ~0.516484, got {ct}"

    def test_low_speed_cp(self):
        """Cp at 0.5 m/s should be small but positive (below cut-in ramp)."""
        from tidal_farm import interpolate_coefficient
        cp = interpolate_coefficient(0.5, self.speeds, self.cp)
        assert 0 < cp < 0.05, f"Cp at 0.5 m/s should be small positive, got {cp}"

    def test_post_cutout_cp(self):
        """Cp above cut-out should be near zero."""
        from tidal_farm import interpolate_coefficient
        cp = interpolate_coefficient(6.0, self.speeds, self.cp)
        assert cp < 0.001, f"Cp at 6.0 m/s should be near zero, got {cp}"

    def test_monotonic_decrease_after_rated(self):
        """Cp must decrease monotonically after rated speed."""
        from tidal_farm import interpolate_coefficient
        test_speeds = [3.05, 3.5, 4.0, 4.5, 5.0]
        cps = [interpolate_coefficient(u, self.speeds, self.cp) for u in test_speeds]
        for i in range(len(cps) - 1):
            assert cps[i] >= cps[i + 1] - 1e-10, (
                f"Cp should decrease: {cps[i]} at {test_speeds[i]} vs "
                f"{cps[i+1]} at {test_speeds[i+1]}"
            )


class TestComputeWakeDeficit:
    def test_jensen_centerline(self):
        """Deficit on centerline must match Jensen formula exactly."""
        from tidal_farm import compute_wake_deficit
        D, Ct, k, U = 20.0, 0.5, 0.04, 3.0
        x = 100.0
        Dw = D + 2 * k * x
        expected = U * (1 - np.sqrt(1 - Ct)) * (D / Dw) ** 2
        deficit = compute_wake_deficit(U, Ct, D, x, 0.0, k)
        assert abs(deficit - expected) < 1e-10, f"Expected {expected}, got {deficit}"

    def test_upstream_zero(self):
        """No wake effect upstream of turbine."""
        from tidal_farm import compute_wake_deficit
        assert compute_wake_deficit(3.0, 0.5, 20.0, -50.0, 0.0, 0.04) == 0.0

    def test_zero_downstream(self):
        """No wake effect at x_downstream=0."""
        from tidal_farm import compute_wake_deficit
        assert compute_wake_deficit(3.0, 0.5, 20.0, 0.0, 0.0, 0.04) == 0.0

    def test_outside_wake_zero(self):
        """No deficit outside wake cone."""
        from tidal_farm import compute_wake_deficit
        D, k, x = 20.0, 0.04, 100.0
        Dw = D + 2 * k * x  # = 28.0
        deficit = compute_wake_deficit(3.0, 0.5, D, x, Dw, k)
        assert deficit == 0.0

    def test_edge_of_wake(self):
        """Deficit transitions at wake boundary."""
        from tidal_farm import compute_wake_deficit
        D, k, x = 20.0, 0.04, 100.0
        Dw = D + 2 * k * x  # = 28.0
        inside = compute_wake_deficit(3.0, 0.5, D, x, Dw / 2 - 0.01, k)
        outside = compute_wake_deficit(3.0, 0.5, D, x, Dw / 2 + 0.01, k)
        assert inside > 0
        assert outside == 0.0

    def test_decreasing_with_distance(self):
        """Deficit must decrease with downstream distance."""
        from tidal_farm import compute_wake_deficit
        deficits = [
            compute_wake_deficit(3.0, 0.5, 20.0, x, 0.0, 0.04)
            for x in [40, 80, 160, 320]
        ]
        for i in range(len(deficits) - 1):
            assert deficits[i] > deficits[i + 1]

    def test_proportional_to_velocity(self):
        """Deficit scales linearly with freestream velocity."""
        from tidal_farm import compute_wake_deficit
        d1 = compute_wake_deficit(3.0, 0.5, 20.0, 100.0, 0.0, 0.04)
        d2 = compute_wake_deficit(6.0, 0.5, 20.0, 100.0, 0.0, 0.04)
        assert abs(d2 / d1 - 2.0) < 1e-10


class TestComputeArrayPower:
    def test_single_turbine_power(self):
        """Single turbine power matches analytic actuator disc formula."""
        from tidal_farm import compute_array_power
        config = load_config()
        pos = np.array([[320.0, 160.0]])
        total, individual = compute_array_power(pos, config)

        U = config['channel']['inflow_velocity']
        rho = config['channel']['density']
        D = config['turbine']['diameter']
        A = np.pi * (D / 2) ** 2
        expected = 0.5 * rho * A * 0.437 * U ** 3

        assert abs(total - expected) / expected < 0.02, (
            f"Single turbine power {total:.0f} W should be within 2% of {expected:.0f} W"
        )

    def test_returns_correct_count(self):
        """Individual powers array has one entry per turbine."""
        from tidal_farm import compute_array_power
        config = load_config()
        pos = np.array([[200.0, 120.0], [300.0, 120.0], [400.0, 120.0]])
        total, individual = compute_array_power(pos, config)
        assert len(individual) == 3
        assert abs(total - sum(individual)) < 1.0

    def test_below_betz_limit(self):
        """Single-turbine power must not exceed Betz limit."""
        from tidal_farm import compute_array_power
        config = load_config()
        pos = np.array([[320.0, 160.0]])
        total, _ = compute_array_power(pos, config)

        U = config['channel']['inflow_velocity']
        rho = config['channel']['density']
        D = config['turbine']['diameter']
        betz = (16.0 / 27.0) * 0.5 * rho * np.pi * (D / 2) ** 2 * U ** 3
        assert total < betz, f"Power {total:.0f} exceeds Betz limit {betz:.0f}"

    def test_inline_wake_reduces_power(self):
        """Downstream turbine in same row must produce significantly less."""
        from tidal_farm import compute_array_power
        config = load_config()
        pos = np.array([[250.0, 160.0], [350.0, 160.0]])
        _, individual = compute_array_power(pos, config)
        assert individual[1] < individual[0] * 0.95, (
            f"Downstream {individual[1]:.0f} not sufficiently less than "
            f"upstream {individual[0]:.0f}"
        )

    def test_side_by_side_similar(self):
        """Turbines at same x, different y should produce similar power."""
        from tidal_farm import compute_array_power
        config = load_config()
        pos = np.array([[320.0, 120.0], [320.0, 200.0]])
        _, individual = compute_array_power(pos, config)
        ratio = individual[0] / individual[1]
        assert 0.95 < ratio < 1.05, f"Side-by-side ratio = {ratio:.3f}"

    def test_below_garrett_cummins_limit(self):
        """Array power must not exceed Garrett-Cummins channel limit."""
        from tidal_farm import compute_array_power
        config = load_config()
        pos = np.array([
            [200, 120], [200, 160], [200, 200],
            [280, 120], [280, 160], [280, 200],
            [360, 140], [360, 180],
        ], dtype=float)
        total, _ = compute_array_power(pos, config)

        U = config['channel']['inflow_velocity']
        rho = config['channel']['density']
        W = config['channel']['width']
        H = config['channel']['depth']
        gc = (16.0 / 27.0) * 0.5 * rho * W * H * U ** 3
        assert total < gc, f"Array power {total:.0f} exceeds GC limit {gc:.0f}"

    def test_additional_upstream_reduces_downstream(self):
        """Adding an extra upstream turbine should reduce downstream power."""
        from tidal_farm import compute_array_power
        config = load_config()

        pos2 = np.array([[200.0, 160.0], [400.0, 160.0]])
        _, ind2 = compute_array_power(pos2, config)

        pos3 = np.array([[200.0, 160.0], [300.0, 160.0], [400.0, 160.0]])
        _, ind3 = compute_array_power(pos3, config)

        assert ind3[2] < ind2[1], (
            f"Last turbine with extra wake ({ind3[2]:.0f}) should be less "
            f"than without ({ind2[1]:.0f})"
        )


class TestOptimizeLayout:
    @classmethod
    def setup_class(cls):
        from tidal_farm import compute_array_power, optimize_layout
        cls.config = load_config()
        fb = cls.config['optimization']['farm_bounds']
        D = float(cls.config['turbine']['diameter'])
        xs = np.linspace(fb['x_min'] + 2 * D, fb['x_max'] - 2 * D, 4)
        ys = np.linspace(fb['y_min'] + 2 * D, fb['y_max'] - 2 * D, 2)
        cls.initial = np.array([[x, y] for x in xs for y in ys])
        cls.init_power, _ = compute_array_power(cls.initial, cls.config)
        cls.optimized = optimize_layout(cls.initial, cls.config)
        cls.opt_power, _ = compute_array_power(cls.optimized, cls.config)

    def test_power_improvement(self):
        """Optimized layout must improve power by at least 15%."""
        improvement = (self.opt_power - self.init_power) / self.init_power * 100
        assert improvement > 15, f"Expected >15% improvement, got {improvement:.1f}%"

    def test_min_distance_constraint(self):
        """All pairwise distances must satisfy minimum distance."""
        min_dist = self.config['optimization']['min_distance']
        n = len(self.optimized)
        for i in range(n):
            for j in range(i + 1, n):
                d = np.linalg.norm(self.optimized[i] - self.optimized[j])
                assert d >= min_dist - 1.0, (
                    f"Turbines {i},{j} too close: {d:.1f}m < {min_dist}m"
                )

    def test_farm_bounds_constraint(self):
        """All turbine rotors must remain within farm bounds."""
        fb = self.config['optimization']['farm_bounds']
        r = float(self.config['turbine']['diameter']) / 2
        for i, pos in enumerate(self.optimized):
            assert pos[0] >= fb['x_min'] + r - 1.0, f"Turbine {i} x below min"
            assert pos[0] <= fb['x_max'] - r + 1.0, f"Turbine {i} x above max"
            assert pos[1] >= fb['y_min'] + r - 1.0, f"Turbine {i} y below min"
            assert pos[1] <= fb['y_max'] - r + 1.0, f"Turbine {i} y above max"

    def test_returns_correct_shape(self):
        """Optimized positions must have same shape as initial."""
        assert self.optimized.shape == self.initial.shape


class TestResultsJSON:
    def test_file_exists(self):
        assert os.path.exists('/app/results.json'), "results.json not found"

    def test_schema(self):
        with open('/app/results.json') as f:
            result = json.load(f)
        for key in ['initial_power_watts', 'optimized_power_watts',
                     'improvement_percent', 'num_turbines',
                     'initial_positions', 'optimized_positions']:
            assert key in result, f"Missing key: {key}"

    def test_improvement_recorded(self):
        with open('/app/results.json') as f:
            result = json.load(f)
        assert result['optimized_power_watts'] > result['initial_power_watts']
        assert result['improvement_percent'] > 15.0

    def test_turbine_count(self):
        with open('/app/results.json') as f:
            result = json.load(f)
        assert result['num_turbines'] == 8
        assert len(result['optimized_positions']) == 8
        assert len(result['initial_positions']) == 8

    def test_positions_format(self):
        with open('/app/results.json') as f:
            result = json.load(f)
        for pos in result['optimized_positions']:
            assert len(pos) == 2
            assert all(isinstance(v, (int, float)) for v in pos)
