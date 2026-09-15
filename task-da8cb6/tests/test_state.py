"""
Test suite for actuator dynamics identification with model validation.

Verifies identified parameters, pipeline ordering, novel response predictions,
and calibration fit quality against ground truth.
"""

import pytest
import json
import csv
import math
import os

# Ground truth actuator parameters and pipeline configurations
TRUE_PARAMS = {
    'A': {'dead_time': 0.12, 'time_constant': 0.08,
          'max_acceleration': 2.5, 'max_velocity': 2.0,
          'pipeline': 'standard'},
    'B': {'dead_time': 0.20, 'time_constant': 0.25,
          'max_acceleration': 1.8, 'max_velocity': 1.5,
          'pipeline': 'standard'},
    'C': {'dead_time': 0.05, 'time_constant': 0.15,
          'max_acceleration': 3.5, 'max_velocity': 3.0,
          'pipeline': 'standard'},
    'D': {'dead_time': 0.18, 'time_constant': 0.10,
          'max_acceleration': 2.0, 'max_velocity': 1.8,
          'pipeline': 'swapped'},
}

STANDARD_ORDER = ["dead_time", "velocity_saturation", "lpf", "acceleration_limit"]
SWAPPED_ORDER = ["dead_time", "velocity_saturation", "acceleration_limit", "lpf"]

DT_SIM = 0.001
DT_OUT = 0.01
NOVEL_DURATION = 8.0


def simulate_standard(commands, dt, dead_time, time_constant,
                      max_acceleration, max_velocity):
    """Reference: dead_time -> sat -> LPF -> accel_limit."""
    delay_samples = max(0, int(round(dead_time / dt)))
    buf_len = delay_samples + 1
    buffer = [0.0] * buf_len
    lpf_state = 0.0
    accel_state = 0.0
    alpha = dt / (time_constant + dt)
    max_change = max_acceleration * dt
    n = len(commands)
    responses = [0.0] * n
    for i in range(n):
        buffer[i % buf_len] = commands[i]
        delayed = buffer[(i - delay_samples) % buf_len]
        saturated = max(-max_velocity, min(max_velocity, delayed))
        lpf_state += alpha * (saturated - lpf_state)
        diff = lpf_state - accel_state
        if diff > max_change:
            accel_state += max_change
        elif diff < -max_change:
            accel_state -= max_change
        else:
            accel_state = lpf_state
        responses[i] = accel_state
    return responses


def simulate_swapped(commands, dt, dead_time, time_constant,
                     max_acceleration, max_velocity):
    """Swapped: dead_time -> sat -> accel_limit -> LPF."""
    delay_samples = max(0, int(round(dead_time / dt)))
    buf_len = delay_samples + 1
    buffer = [0.0] * buf_len
    accel_state = 0.0
    lpf_state = 0.0
    alpha = dt / (time_constant + dt)
    max_change = max_acceleration * dt
    n = len(commands)
    responses = [0.0] * n
    for i in range(n):
        buffer[i % buf_len] = commands[i]
        delayed = buffer[(i - delay_samples) % buf_len]
        saturated = max(-max_velocity, min(max_velocity, delayed))
        diff = saturated - accel_state
        if diff > max_change:
            accel_state += max_change
        elif diff < -max_change:
            accel_state -= max_change
        else:
            accel_state = saturated
        lpf_state += alpha * (accel_state - lpf_state)
        responses[i] = lpf_state
    return responses


# Novel command functions — must match generate_data.py exactly

def novel_command_A(t):
    """Chirp: frequency sweeps 0.1 to 1.0 Hz over 8s."""
    f0, f1, T = 0.1, 1.0, 8.0
    phase = 2 * math.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * T))
    return 1.0 * math.sin(phase)


def novel_command_B(t):
    """Trapezoidal velocity profile."""
    if t < 1.0:
        return 0.6 * t
    elif t < 3.0:
        return 0.6
    elif t < 4.5:
        return 0.6 - 0.8 * (t - 3.0)
    elif t < 6.5:
        return -0.6
    elif t < 8.0:
        return -0.6 + 0.4 * (t - 6.5)
    return 0.0


def novel_command_C(t):
    """Sum of two sinusoids."""
    return 1.2 * math.sin(2 * math.pi * 0.3 * t) + \
           0.5 * math.sin(2 * math.pi * 1.1 * t + 0.7)


def novel_command_D(t):
    """Asymmetric pulse train."""
    cycle = t % 3.0
    if cycle < 1.0:
        return 1.2
    elif cycle < 1.5:
        return 0.0
    elif cycle < 2.5:
        return -0.8
    return 0.0


NOVEL_FUNCS = {
    'A': novel_command_A, 'B': novel_command_B,
    'C': novel_command_C, 'D': novel_command_D,
}


def generate_ground_truth_novel(config_name):
    """Generate ground truth novel response at 1000 Hz, output at 100 Hz."""
    params = TRUE_PARAMS[config_name]
    func = NOVEL_FUNCS[config_name]
    n_sim = int(round(NOVEL_DURATION / DT_SIM))
    commands = [func(i * DT_SIM) for i in range(n_sim)]
    sim_fn = simulate_swapped if params['pipeline'] == 'swapped' \
        else simulate_standard
    responses = sim_fn(
        commands, DT_SIM,
        params['dead_time'], params['time_constant'],
        params['max_acceleration'], params['max_velocity']
    )
    downsample = int(round(DT_OUT / DT_SIM))
    times_out = [i * DT_SIM for i in range(0, n_sim, downsample)]
    resp_out = [responses[i] for i in range(0, n_sim, downsample)]
    return times_out, resp_out


def read_csv_data(filepath):
    """Read CSV file, return dict of lowercase column name -> list of floats."""
    data = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames]
        for h in headers:
            data[h] = []
        for row in reader:
            for h_orig, h_clean in zip(reader.fieldnames, headers):
                data[h_clean].append(float(row[h_orig].strip()))
    return data


def compute_rmse(predicted, actual):
    """Compute RMSE between two lists."""
    n = min(len(predicted), len(actual))
    assert n > 0, "Empty data for RMSE computation"
    mse = sum((predicted[i] - actual[i]) ** 2 for i in range(n)) / n
    return math.sqrt(mse)


# =====================================================================
# Structural tests
# =====================================================================

class TestOutputStructure:

    def test_identified_params_exists(self):
        assert os.path.exists('/app/output/identified_params.json'), \
            "Missing /app/output/identified_params.json"

    def test_pipeline_config_exists(self):
        assert os.path.exists('/app/output/pipeline_config.json'), \
            "Missing /app/output/pipeline_config.json"

    def test_calibration_rmse_exists(self):
        assert os.path.exists('/app/output/calibration_rmse.json'), \
            "Missing /app/output/calibration_rmse.json"

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_novel_response_exists(self, name):
        path = f'/app/output/novel_response_{name}.csv'
        assert os.path.exists(path), f"Missing {path}"

    def test_params_format(self):
        with open('/app/output/identified_params.json') as f:
            params = json.load(f)
        for name in ['A', 'B', 'C', 'D']:
            assert name in params, f"Missing config '{name}'"
            for key in ['dead_time', 'time_constant',
                        'max_acceleration', 'max_velocity']:
                assert key in params[name], \
                    f"Missing '{key}' for config {name}"
                val = params[name][key]
                assert isinstance(val, (int, float)), \
                    f"{key} for {name} must be numeric"
                assert val > 0, \
                    f"{key} for {name} must be positive, got {val}"

    def test_pipeline_config_format(self):
        with open('/app/output/pipeline_config.json') as f:
            config = json.load(f)
        required_stages = {"dead_time", "velocity_saturation",
                           "lpf", "acceleration_limit"}
        for name in ['A', 'B', 'C', 'D']:
            assert name in config, f"Missing config '{name}'"
            order = config[name]
            assert isinstance(order, list), \
                f"{name} pipeline must be a list"
            assert len(order) == 4, \
                f"{name} pipeline must have 4 stages, got {len(order)}"
            assert set(order) == required_stages, \
                f"{name} pipeline must contain exactly {required_stages}"

    def test_calibration_rmse_format(self):
        with open('/app/output/calibration_rmse.json') as f:
            rmse_data = json.load(f)
        for name in ['A', 'B', 'C', 'D']:
            assert name in rmse_data, f"Missing config '{name}'"
            for step_type in ['small', 'medium', 'large']:
                assert step_type in rmse_data[name], \
                    f"Missing '{step_type}' for {name}"
                val = rmse_data[name][step_type]
                assert isinstance(val, (int, float)), \
                    f"{step_type} RMSE for {name} must be numeric"
                assert val >= 0, \
                    f"{step_type} RMSE for {name} must be non-negative"


# =====================================================================
# Parameter accuracy tests
# =====================================================================

class TestParameterAccuracy:

    @pytest.fixture(autouse=True)
    def load_params(self):
        with open('/app/output/identified_params.json') as f:
            self.params = json.load(f)

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_dead_time(self, name):
        true_val = TRUE_PARAMS[name]['dead_time']
        est = self.params[name]['dead_time']
        err = abs(est - true_val)
        assert err < 0.025, (
            f"{name} dead_time: est={est:.4f}, true={true_val:.4f}, "
            f"error={err:.4f} > 0.025"
        )

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_time_constant(self, name):
        true_val = TRUE_PARAMS[name]['time_constant']
        est = self.params[name]['time_constant']
        rel_err = abs(est - true_val) / true_val
        assert rel_err < 0.25, (
            f"{name} time_constant: est={est:.4f}, true={true_val:.4f}, "
            f"rel_err={rel_err:.2%} > 25%"
        )

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_max_acceleration(self, name):
        true_val = TRUE_PARAMS[name]['max_acceleration']
        est = self.params[name]['max_acceleration']
        rel_err = abs(est - true_val) / true_val
        assert rel_err < 0.25, (
            f"{name} max_accel: est={est:.4f}, true={true_val:.4f}, "
            f"rel_err={rel_err:.2%} > 25%"
        )

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_max_velocity(self, name):
        true_val = TRUE_PARAMS[name]['max_velocity']
        est = self.params[name]['max_velocity']
        rel_err = abs(est - true_val) / true_val
        assert rel_err < 0.08, (
            f"{name} max_vel: est={est:.4f}, true={true_val:.4f}, "
            f"rel_err={rel_err:.2%} > 8%"
        )


# =====================================================================
# Pipeline order identification tests
# =====================================================================

class TestPipelineOrder:

    @pytest.fixture(autouse=True)
    def load_config(self):
        with open('/app/output/pipeline_config.json') as f:
            self.config = json.load(f)

    @pytest.mark.parametrize("name", ['A', 'B', 'C'])
    def test_standard_pipeline(self, name):
        assert self.config[name] == STANDARD_ORDER, (
            f"Actuator {name} should use standard pipeline ordering "
            f"{STANDARD_ORDER}, got {self.config[name]}"
        )

    def test_swapped_pipeline_D(self):
        assert self.config['D'] == SWAPPED_ORDER, (
            f"Actuator D should use swapped pipeline ordering "
            f"(acceleration_limit before lpf) {SWAPPED_ORDER}, "
            f"got {self.config['D']}"
        )


# =====================================================================
# Novel response prediction tests
# =====================================================================

class TestNovelResponse:

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_response_length(self, name):
        expected_n = int(round(NOVEL_DURATION / DT_OUT))
        data = read_csv_data(f'/app/output/novel_response_{name}.csv')
        pred_n = len(data['response'])
        assert abs(pred_n - expected_n) <= 2, (
            f"{name} novel response: {pred_n} points, expected ~{expected_n}"
        )

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_response_accuracy(self, name):
        gt_times, gt_resp = generate_ground_truth_novel(name)
        data = read_csv_data(f'/app/output/novel_response_{name}.csv')
        rmse = compute_rmse(data['response'], gt_resp)
        assert rmse < 0.15, (
            f"{name} novel response RMSE = {rmse:.4f} > 0.15"
        )


# =====================================================================
# Calibration fit quality tests
# =====================================================================

class TestCalibrationFit:

    @pytest.mark.parametrize("name", ['A', 'B', 'C', 'D'])
    def test_fit_quality(self, name):
        """Calibration RMSE should indicate adequate model fit."""
        with open('/app/output/calibration_rmse.json') as f:
            rmse_data = json.load(f)
        for step_type in ['small', 'medium', 'large']:
            val = rmse_data[name][step_type]
            assert val < 0.05, (
                f"{name}/{step_type} calibration RMSE = {val:.4f} > 0.05 "
                f"(indicates poor model fit — wrong pipeline order or "
                f"incorrect parameters)"
            )
