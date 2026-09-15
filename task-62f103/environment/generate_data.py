#!/usr/bin/env python3
"""Generate synthetic Eurobench-format biomechanical gait data with realistic artifacts.

"""

import numpy as np
import yaml
import os


def main():
    rng = np.random.RandomState(42)

    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/config', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    SAMPLE_RATE = 100
    DURATION = 25.0
    t = np.arange(0, DURATION, 1.0 / SAMPLE_RATE)

    subjects = {
        1: {'height': 1.75, 'weight': 70.0, 'leg_length': 0.85, 'age': 28},
        2: {'height': 1.65, 'weight': 80.0, 'leg_length': 0.78, 'age': 55},
    }
    for subj_id, info in subjects.items():
        path = f'/app/data/subject_{subj_id}_info.yaml'
        with open(path, 'w') as f:
            yaml.dump(info, f, default_flow_style=False)

    configs = {
        (1, 1): dict(
            stride_time_mean=1.10, stride_time_std=0.02,
            hip_amp_r=20.0, knee_amp_r=30.0, ankle_amp_r=15.0,
            hip_amp_l=20.0, knee_amp_l=30.0, ankle_amp_l=15.0,
            hip_offset=5.0, knee_offset=15.0, ankle_offset=0.0,
            noise_std=0.5, stance_ratio=0.60, step_offset=0.50,
        ),
        (1, 2): dict(
            stride_time_mean=1.25, stride_time_std=0.025,
            hip_amp_r=22.5, knee_amp_r=32.5, ankle_amp_r=17.5,
            hip_amp_l=22.5, knee_amp_l=32.5, ankle_amp_l=17.5,
            hip_offset=8.0, knee_offset=18.0, ankle_offset=3.0,
            noise_std=0.6, stance_ratio=0.62, step_offset=0.50,
        ),
        (2, 1): dict(
            stride_time_mean=1.35, stride_time_std=0.04,
            hip_amp_r=16.0, knee_amp_r=24.0, ankle_amp_r=11.0,
            hip_amp_l=14.4, knee_amp_l=21.6, ankle_amp_l=9.9,
            hip_offset=3.0, knee_offset=12.0, ankle_offset=-2.0,
            noise_std=1.5, stance_ratio=0.63, step_offset=0.48,
        ),
        (2, 2): dict(
            stride_time_mean=1.50, stride_time_std=0.05,
            hip_amp_r=17.5, knee_amp_r=25.0, ankle_amp_r=12.5,
            hip_amp_l=15.4, knee_amp_l=22.0, ankle_amp_l=11.0,
            hip_offset=5.0, knee_offset=14.0, ankle_offset=0.0,
            noise_std=1.8, stance_ratio=0.65, step_offset=0.47,
        ),
    }

    for (subj, cond), cfg in sorted(configs.items()):
        for run in [1, 2, 3]:
            generate_run(rng, t, SAMPLE_RATE, subj, cond, run, cfg)

    print("Synthetic gait data generated successfully.")


def generate_heel_strikes(rng, duration, stride_mean, stride_std):
    hs = [0.0]
    while True:
        delta = max(0.5, stride_mean + rng.normal(0, stride_std))
        next_t = hs[-1] + delta
        if next_t >= duration - 0.5:
            break
        hs.append(round(next_t, 4))
    return hs


def corrupt_heel_strikes(hs, subj, cond, run):
    """Inject realistic measurement artifacts into heel strike event list."""
    hs = [float(x) for x in hs]

    # Run 2: duplicate and near-duplicate detections (sensor bounce)
    if run == 2:
        idx = len(hs) // 3
        hs.insert(idx + 1, hs[idx])
        idx2 = 2 * len(hs) // 3
        hs.insert(idx2 + 1, round(hs[idx2] + 0.015, 4))

    # Run 3: phantom event creating physiologically impossible short stride
    if run == 3:
        idx = len(hs) // 2
        hs.insert(idx + 1, round(hs[idx] + 0.20, 4))

    # Subject 2, run 1: temporal ordering error from buffer timing
    if subj == 2 and run == 1:
        idx = len(hs) // 4
        if idx + 1 < len(hs):
            hs[idx], hs[idx + 1] = hs[idx + 1], hs[idx]

    return hs


def make_joint_signal(t, heel_strikes, amplitude, offset, noise_std, rng):
    signal = np.full_like(t, offset, dtype=float)
    for i in range(len(heel_strikes) - 1):
        hs1 = heel_strikes[i]
        hs2 = heel_strikes[i + 1]
        mask = (t >= hs1) & (t < hs2)
        if not np.any(mask):
            continue
        cycle_t = t[mask] - hs1
        cycle_dur = hs2 - hs1
        phase = 2.0 * np.pi * cycle_t / cycle_dur
        signal[mask] = offset + amplitude * np.sin(phase)
    signal += rng.normal(0, noise_std, len(t))
    return signal


def generate_run(rng, t, sample_rate, subj, cond, run, cfg):
    duration = t[-1] + 1.0 / sample_rate

    r_hs_clean = generate_heel_strikes(
        rng, duration, cfg['stride_time_mean'], cfg['stride_time_std']
    )

    l_hs_clean = []
    for i in range(len(r_hs_clean) - 1):
        stride = r_hs_clean[i + 1] - r_hs_clean[i]
        l_hs_clean.append(round(r_hs_clean[i] + stride * cfg['step_offset'], 4))

    r_to = []
    for i in range(len(r_hs_clean) - 1):
        stride = r_hs_clean[i + 1] - r_hs_clean[i]
        r_to.append(round(r_hs_clean[i] + stride * cfg['stance_ratio'], 4))

    l_to = []
    for i in range(len(l_hs_clean) - 1):
        if i + 1 < len(l_hs_clean):
            stride_l = l_hs_clean[i + 1] - l_hs_clean[i]
        else:
            stride_l = cfg['stride_time_mean']
        l_to.append(round(l_hs_clean[i] + stride_l * cfg['stance_ratio'], 4))

    l_hs_ext = l_hs_clean + [round(l_hs_clean[-1] + cfg['stride_time_mean'], 4)]

    hip_r = make_joint_signal(
        t, r_hs_clean, cfg['hip_amp_r'], cfg['hip_offset'], cfg['noise_std'], rng
    )
    hip_l = make_joint_signal(
        t, l_hs_ext, cfg['hip_amp_l'], cfg['hip_offset'], cfg['noise_std'], rng
    )
    knee_r = make_joint_signal(
        t, r_hs_clean, cfg['knee_amp_r'], cfg['knee_offset'], cfg['noise_std'], rng
    )
    knee_l = make_joint_signal(
        t, l_hs_ext, cfg['knee_amp_l'], cfg['knee_offset'], cfg['noise_std'], rng
    )
    ankle_r = make_joint_signal(
        t, r_hs_clean, cfg['ankle_amp_r'], cfg['ankle_offset'], cfg['noise_std'], rng
    )
    ankle_l = make_joint_signal(
        t, l_hs_ext, cfg['ankle_amp_l'], cfg['ankle_offset'], cfg['noise_std'], rng
    )

    prefix = f'subject_{subj}_cond_{cond}_run_{run}'
    csv_path = f'/app/data/{prefix}_jointAngles.csv'
    with open(csv_path, 'w') as f:
        f.write(
            'time; hip_flexion_r; hip_flexion_l; '
            'knee_flexion_r; knee_flexion_l; '
            'ankle_flexion_r; ankle_flexion_l\n'
        )
        for i in range(len(t)):
            f.write(
                f'{t[i]:.3f}; {hip_r[i]:.4f}; {hip_l[i]:.4f}; '
                f'{knee_r[i]:.4f}; {knee_l[i]:.4f}; '
                f'{ankle_r[i]:.4f}; {ankle_l[i]:.4f}\n'
            )

    r_hs_corrupted = corrupt_heel_strikes(r_hs_clean, subj, cond, run)
    l_hs_corrupted = corrupt_heel_strikes(l_hs_clean, subj, cond, run)

    events = {
        'r_heel_strike': [float(x) for x in r_hs_corrupted],
        'l_heel_strike': [float(x) for x in l_hs_corrupted],
        'r_toe_off': [float(x) for x in r_to],
        'l_toe_off': [float(x) for x in l_to],
    }
    yaml_path = f'/app/data/{prefix}_gaitEvents.yaml'
    with open(yaml_path, 'w') as f:
        yaml.dump(events, f, default_flow_style=False)


if __name__ == '__main__':
    main()
