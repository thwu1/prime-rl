#!/usr/bin/env python3
"""Generate actuator step response data with measurement noise and novel commands.

Runs during Docker build (datagen stage) and is NOT present in the final image.
"""
import os
import math
import random


def simulate_standard(commands, dt, dead_time, time_constant,
                      max_acceleration, max_velocity):
    """Standard pipeline: dead_time -> sat -> LPF -> accel_limit."""
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
    """Swapped pipeline: dead_time -> sat -> accel_limit -> LPF."""
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


def generate_step_response(dt_sim, dt_out, duration, step_value,
                           dead_time, time_constant, max_acceleration,
                           max_velocity, pipeline, noise_std, seed):
    """Generate noisy step response: rest until t=0.5s, then step."""
    n_sim = int(round(duration / dt_sim))
    n_rest = int(round(0.5 / dt_sim))
    commands = [0.0] * n_sim
    for i in range(n_rest, n_sim):
        commands[i] = step_value

    sim_fn = simulate_swapped if pipeline == 'swapped' else simulate_standard
    responses = sim_fn(commands, dt_sim, dead_time, time_constant,
                       max_acceleration, max_velocity)

    downsample = int(round(dt_out / dt_sim))
    rng = random.Random(seed)
    times, out_cmds, out_resps = [], [], []
    for i in range(0, n_sim, downsample):
        times.append(i * dt_sim)
        out_cmds.append(commands[i])
        out_resps.append(responses[i] + rng.gauss(0, noise_std))

    return times, out_cmds, out_resps


def write_csv(filename, headers, *columns):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w') as f:
        f.write(','.join(headers) + '\n')
        for row in zip(*columns):
            f.write(','.join(f'{v:.6f}' for v in row) + '\n')


def main():
    dt_sim = 0.001
    dt_out = 0.01
    step_duration = 5.0
    novel_duration = 8.0

    configs = {
        'A': {'dead_time': 0.12, 'time_constant': 0.08,
              'max_acceleration': 2.5, 'max_velocity': 2.0,
              'noise_std': 0.008, 'pipeline': 'standard'},
        'B': {'dead_time': 0.20, 'time_constant': 0.25,
              'max_acceleration': 1.8, 'max_velocity': 1.5,
              'noise_std': 0.012, 'pipeline': 'standard'},
        'C': {'dead_time': 0.05, 'time_constant': 0.15,
              'max_acceleration': 3.5, 'max_velocity': 3.0,
              'noise_std': 0.010, 'pipeline': 'standard'},
        'D': {'dead_time': 0.18, 'time_constant': 0.10,
              'max_acceleration': 2.0, 'max_velocity': 1.8,
              'noise_std': 0.015, 'pipeline': 'swapped'},
    }

    step_values = {
        'A': {'small': 0.4, 'medium': 1.2, 'large': 3.5},
        'B': {'small': 0.3, 'medium': 0.8, 'large': 2.5},
        'C': {'small': 0.5, 'medium': 1.5, 'large': 5.0},
        'D': {'small': 0.3, 'medium': 1.0, 'large': 3.0},
    }

    seeds = {
        ('A', 'small'): 101, ('A', 'medium'): 102, ('A', 'large'): 103,
        ('B', 'small'): 201, ('B', 'medium'): 202, ('B', 'large'): 203,
        ('C', 'small'): 301, ('C', 'medium'): 302, ('C', 'large'): 303,
        ('D', 'small'): 401, ('D', 'medium'): 402, ('D', 'large'): 403,
    }

    for name, params in configs.items():
        for step_type, step_val in step_values[name].items():
            t, cmd, resp = generate_step_response(
                dt_sim, dt_out, step_duration, step_val,
                params['dead_time'], params['time_constant'],
                params['max_acceleration'], params['max_velocity'],
                params['pipeline'], params['noise_std'],
                seeds[(name, step_type)]
            )
            write_csv(f'/app/data/config_{name}_{step_type}_step.csv',
                      ['time', 'command', 'response'], t, cmd, resp)

    # Novel command profiles
    def novel_A(t):
        """Chirp: frequency sweeps 0.1 to 1.0 Hz over 8s."""
        f0, f1, T = 0.1, 1.0, 8.0
        phase = 2 * math.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * T))
        return 1.0 * math.sin(phase)

    def novel_B(t):
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

    def novel_C(t):
        """Sum of two sinusoids."""
        return 1.2 * math.sin(2 * math.pi * 0.3 * t) + \
               0.5 * math.sin(2 * math.pi * 1.1 * t + 0.7)

    def novel_D(t):
        """Asymmetric pulse train."""
        cycle = t % 3.0
        if cycle < 1.0:
            return 1.2
        elif cycle < 1.5:
            return 0.0
        elif cycle < 2.5:
            return -0.8
        return 0.0

    novel_funcs = {'A': novel_A, 'B': novel_B, 'C': novel_C, 'D': novel_D}

    for name, func in novel_funcs.items():
        n_sim = int(round(novel_duration / dt_sim))
        commands_sim = [func(i * dt_sim) for i in range(n_sim)]
        downsample = int(round(dt_out / dt_sim))
        times_out = [i * dt_sim for i in range(0, n_sim, downsample)]
        cmds_out = [commands_sim[i] for i in range(0, n_sim, downsample)]
        write_csv(f'/app/data/novel_command_{name}.csv',
                  ['time', 'command'], times_out, cmds_out)


if __name__ == '__main__':
    main()
