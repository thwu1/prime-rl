#!/usr/bin/env python3
"""
Actuator system identification with model validation.

For each actuator:
1. Fit parameters using both standard and swapped pipeline orderings
2. Select the pipeline ordering that best fits the measured data
3. Compute calibration RMSE for the selected model
4. Predict novel command response using the identified model
"""

import json
import csv
import math
import os
import random
from scipy.optimize import minimize

STANDARD_ORDER = ["dead_time", "velocity_saturation", "lpf", "acceleration_limit"]
SWAPPED_ORDER = ["dead_time", "velocity_saturation", "acceleration_limit", "lpf"]


def simulate_standard(commands, dt, dead_time, time_constant,
                      max_acceleration, max_velocity):
    """Standard: dead_time -> sat -> LPF -> accel_limit."""
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


def read_csv(filename):
    """Read CSV, return dict of stripped column name -> list of floats."""
    data = {}
    with open(filename) as f:
        reader = csv.DictReader(f)
        headers = [h.strip() for h in reader.fieldnames]
        for h in headers:
            data[h] = []
        for row in reader:
            for h_orig, h_clean in zip(reader.fieldnames, headers):
                data[h_clean].append(float(row[h_orig].strip()))
    return data


def heuristic_init(step_datas):
    """Get initial parameter estimates from step response data features."""
    large_data = step_datas[-1]
    small_data = step_datas[0]
    lt = large_data['time']
    lc = large_data['command']
    lr = large_data['response']
    st = small_data['time']
    sr = small_data['response']

    step_idx = next(j for j, c in enumerate(lc) if abs(c) > 1e-6)
    step_time = lt[step_idx]

    # dead_time: find when response first exceeds noise floor
    threshold = 0.02
    onset_idx = len(lr) - 1
    for j in range(step_idx, len(lr)):
        if abs(lr[j]) > threshold:
            onset_idx = j
            break
    dead_time_est = max(0.01, lt[onset_idx] - step_time)

    # max_velocity: steady-state of large step
    n_ss = min(50, len(lr) // 5)
    max_vel_est = max(0.1, sum(abs(lr[j]) for j in range(-n_ss, 0)) / n_ss)

    # time_constant: 63.2% rise time from small step
    small_ss = sum(sr[-n_ss:]) / n_ss
    target_63 = 0.632 * abs(small_ss) if abs(small_ss) > 0.01 else 0.1
    tc_est = 0.1
    for j in range(step_idx, len(sr)):
        if abs(sr[j]) >= target_63:
            tc_est = max(0.01, st[j] - step_time - dead_time_est)
            break

    # max_acceleration: initial slope of large step
    if onset_idx + 5 < len(lr):
        end_idx = min(onset_idx + 5, len(lr) - 1)
        dt_obs = lt[end_idx] - lt[onset_idx]
        slope = abs(lr[end_idx] - lr[onset_idx]) / max(0.01, dt_obs)
        max_accel_est = max(0.5, slope)
    else:
        max_accel_est = 2.0

    return dead_time_est, tc_est, max_accel_est, max_vel_est


def build_cmd_arrays(step_datas, dt_sim=0.001, dt_out=0.01):
    """Pre-compute command arrays at simulation rate for each step."""
    arrays = []
    for data in step_datas:
        times = data['time']
        cmds = data['command']
        resps = data['response']
        step_idx = next(j for j, c in enumerate(cmds) if abs(c) > 1e-6)
        step_time = times[step_idx]
        step_val = cmds[step_idx]
        n_sim = int(round(times[-1] / dt_sim)) + 1
        ss = int(round(step_time / dt_sim))
        cmd_sim = [0.0] * n_sim
        for j in range(ss, n_sim):
            cmd_sim[j] = step_val
        arrays.append((cmd_sim, n_sim, resps))
    return arrays


def fit_pipeline(sim_fn, step_datas, dt_sim=0.001, dt_out=0.01):
    """Fit actuator parameters using given pipeline simulator."""
    cmd_arrays = build_cmd_arrays(step_datas, dt_sim, dt_out)
    downsample = int(round(dt_out / dt_sim))

    def objective(log_params):
        dt_p = math.exp(log_params[0])
        tc_p = math.exp(log_params[1])
        ma_p = math.exp(log_params[2])
        mv_p = math.exp(log_params[3])
        if dt_p > 2 or tc_p > 5 or ma_p > 50 or mv_p > 20:
            return 1e10
        if dt_p < 0.001 or tc_p < 0.001 or ma_p < 0.01:
            return 1e10
        error = 0.0
        for cmd, n_sim, measured in cmd_arrays:
            resp = sim_fn(cmd, dt_sim, dt_p, tc_p, ma_p, mv_p)
            for j, idx in enumerate(range(0, n_sim, downsample)):
                if j < len(measured) and idx < len(resp):
                    error += (resp[idx] - measured[j]) ** 2
        return error

    dt_est, tc_est, ma_est, mv_est = heuristic_init(step_datas)
    x0 = [math.log(max(0.01, dt_est)),
          math.log(max(0.01, tc_est)),
          math.log(max(0.5, ma_est)),
          math.log(max(0.1, mv_est))]

    best = minimize(objective, x0, method='Nelder-Mead',
                    options={'maxiter': 5000, 'xatol': 1e-8,
                             'fatol': 1e-13, 'adaptive': True})

    # Multiple restarts from perturbed points for robustness
    rng = random.Random(54321)
    for _ in range(5):
        x0p = [x + rng.uniform(-0.5, 0.5) for x in x0]
        r = minimize(objective, x0p, method='Nelder-Mead',
                     options={'maxiter': 4000, 'xatol': 1e-8,
                              'fatol': 1e-13, 'adaptive': True})
        if r.fun < best.fun:
            best = r

    # Additional restarts from wider spread
    for scale in [0.8, 1.2]:
        x0p = [x * scale for x in x0]
        r = minimize(objective, x0p, method='Nelder-Mead',
                     options={'maxiter': 4000, 'xatol': 1e-8,
                              'fatol': 1e-13, 'adaptive': True})
        if r.fun < best.fun:
            best = r

    params = {
        'dead_time': round(math.exp(best.x[0]), 6),
        'time_constant': round(math.exp(best.x[1]), 6),
        'max_acceleration': round(math.exp(best.x[2]), 6),
        'max_velocity': round(math.exp(best.x[3]), 6),
    }
    return params, best.fun


def compute_calibration_rmse(sim_fn, params, step_datas,
                             dt_sim=0.001, dt_out=0.01):
    """Compute per-step RMSE between identified model and measured data."""
    step_types = ['small', 'medium', 'large']
    downsample = int(round(dt_out / dt_sim))
    rmses = {}
    for st, data in zip(step_types, step_datas):
        times = data['time']
        cmds = data['command']
        resps = data['response']
        si = next(j for j, c in enumerate(cmds) if abs(c) > 1e-6)
        sv = cmds[si]
        n_sim = int(round(times[-1] / dt_sim)) + 1
        ss = int(round(times[si] / dt_sim))
        cmd_sim = [0.0] * n_sim
        for j in range(ss, n_sim):
            cmd_sim[j] = sv
        sim_resp = sim_fn(cmd_sim, dt_sim, params['dead_time'],
                          params['time_constant'],
                          params['max_acceleration'],
                          params['max_velocity'])
        pred, actual = [], []
        for j, idx in enumerate(range(0, n_sim, downsample)):
            if j < len(resps) and idx < len(sim_resp):
                pred.append(sim_resp[idx])
                actual.append(resps[j])
        n = len(pred)
        mse = sum((pred[k] - actual[k]) ** 2 for k in range(n)) / n
        rmses[st] = round(math.sqrt(mse), 6)
    return rmses


def predict_novel(cmd_data, params, sim_fn, dt_sim=0.001, dt_out=0.01):
    """Predict novel response by upsampling command and simulating."""
    times = cmd_data['time']
    commands = cmd_data['command']
    n_out = len(times)
    downsample = int(round(dt_out / dt_sim))
    cmd_sim = []
    for j in range(n_out):
        cmd_sim.extend([commands[j]] * downsample)
    n_sim = len(cmd_sim)
    responses = sim_fn(cmd_sim, dt_sim, params['dead_time'],
                       params['time_constant'],
                       params['max_acceleration'],
                       params['max_velocity'])
    out_times = [i * downsample * dt_sim for i in range(n_out)]
    out_resp = [responses[min(i * downsample, n_sim - 1)]
                for i in range(n_out)]
    return out_times, out_resp


def write_csv(filename, headers, *columns):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w') as f:
        f.write(','.join(headers) + '\n')
        for row in zip(*columns):
            f.write(','.join(f'{v:.6f}' for v in row) + '\n')


def main():
    configs = ['A', 'B', 'C', 'D']
    step_types = ['small', 'medium', 'large']

    # Verify data files exist
    for name in configs:
        for st in step_types:
            path = f'/app/data/config_{name}_{st}_step.csv'
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"Data file missing: {path}. "
                    f"Contents of /app/data/: {os.listdir('/app/data') if os.path.isdir('/app/data') else 'DIR NOT FOUND'}"
                )

    identified = {}
    pipeline_config = {}
    cal_rmse = {}

    for name in configs:
        print(f"\n{'=' * 50}")
        print(f"Actuator {name}")

        step_datas = [read_csv(f'/app/data/config_{name}_{st}_step.csv')
                      for st in step_types]

        # Try standard pipeline
        print("  Fitting standard pipeline...")
        params_std, mse_std = fit_pipeline(simulate_standard, step_datas)
        print(f"    MSE = {mse_std:.8f}")

        # Try swapped pipeline (accel_limit before lpf)
        print("  Fitting swapped pipeline...")
        params_swap, mse_swap = fit_pipeline(simulate_swapped, step_datas)
        print(f"    MSE = {mse_swap:.8f}")

        # Select the pipeline with lower MSE
        if mse_swap < mse_std:
            print(f"  -> SWAPPED (ratio {mse_swap / max(mse_std, 1e-20):.4f})")
            identified[name] = params_swap
            pipeline_config[name] = SWAPPED_ORDER
            sim_fn = simulate_swapped
        else:
            print(f"  -> STANDARD (ratio {mse_std / max(mse_swap, 1e-20):.4f})")
            identified[name] = params_std
            pipeline_config[name] = STANDARD_ORDER
            sim_fn = simulate_standard

        print(f"  Params: {identified[name]}")

        cal_rmse[name] = compute_calibration_rmse(
            sim_fn, identified[name], step_datas)
        print(f"  Cal RMSE: {cal_rmse[name]}")

    # Write outputs
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/identified_params.json', 'w') as f:
        json.dump(identified, f, indent=2)
    print("\nWrote identified_params.json")

    with open('/app/output/pipeline_config.json', 'w') as f:
        json.dump(pipeline_config, f, indent=2)
    print("Wrote pipeline_config.json")

    with open('/app/output/calibration_rmse.json', 'w') as f:
        json.dump(cal_rmse, f, indent=2)
    print("Wrote calibration_rmse.json")

    for name in configs:
        sim_fn = simulate_swapped \
            if pipeline_config[name] == SWAPPED_ORDER \
            else simulate_standard
        cmd = read_csv(f'/app/data/novel_command_{name}.csv')
        times, resp = predict_novel(cmd, identified[name], sim_fn)
        write_csv(f'/app/output/novel_response_{name}.csv',
                  ['time', 'response'], times, resp)
        print(f"Wrote novel_response_{name}.csv ({len(resp)} samples)")

    print("\nDone!")


if __name__ == '__main__':
    main()
