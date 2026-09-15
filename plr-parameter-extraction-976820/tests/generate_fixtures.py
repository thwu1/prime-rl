#!/usr/bin/env python3
"""Generate synthetic PLR recordings with known ground truth for testing.

Uses a parametric exponential constriction/redilation model with configurable
PIPR fraction, noise, and blink artifacts. Ground truth is computed analytically.
"""


import json
import math
import os
import csv
import random

SEED = 42

# Protocol constants (must match /app/protocol.json)
FS = 30
PRE_STIM = 2.0
STIM_DUR = 1.0
POST_STIM = 32.0
ONSET = PRE_STIM
OFFSET = PRE_STIM + STIM_DUR
TOTAL_DUR = PRE_STIM + STIM_DUR + POST_STIM
N_SAMPLES = int(TOTAL_DUR * FS) + 1
DT = 1.0 / FS
NOISE_STD = 0.03


# ── Signal model ──────────────────────────────────────────────────────────────

def plr_signal(t, baseline, latency, A, tau_c, tau_r, pipr_frac):
    """Compute clean PLR diameter at time t using exponential model."""
    if t < ONSET + latency:
        return baseline
    elif t < OFFSET:
        tc = t - ONSET - latency
        return baseline - A * (1.0 - math.exp(-tc / tau_c))
    else:
        tc_total = OFFSET - ONSET - latency
        constr_at_off = A * (1.0 - math.exp(-tc_total / tau_c))
        sustained = pipr_frac * constr_at_off
        recoverable = constr_at_off - sustained
        tr = t - OFFSET
        return (baseline - constr_at_off) + recoverable * (1.0 - math.exp(-tr / tau_r))


# ── Condition parameters ─────────────────────────────────────────────────────

BLUE_PARAMS = {
    'baseline': 6.50, 'latency': 0.200,
    'A': 2.20, 'tau_c': 0.300, 'tau_r': 1.500, 'pipr_frac': 0.35,
}
RED_PARAMS = {
    'baseline': 6.50, 'latency': 0.230,
    'A': 1.80, 'tau_c': 0.280, 'tau_r': 1.200, 'pipr_frac': 0.03,
}
HORNER_RIGHT_PARAMS = {
    'baseline': 6.30, 'latency': 0.210,
    'A': 1.90, 'tau_c': 0.280, 'tau_r': 1.500, 'pipr_frac': 0.05,
}
HORNER_LEFT_PARAMS = {
    'baseline': 5.80, 'latency': 0.220,
    'A': 1.50, 'tau_c': 0.300, 'tau_r': 5.000, 'pipr_frac': 0.05,
}

# Blink artifact specifications: (time_s, duration_s)
BLUE_02_BLINKS = [(0.50, 0.167), (1.30, 0.133), (5.00, 0.200)]
BLUE_03_BLINKS = [(2.50, 0.167), (7.00, 0.133), (15.00, 0.167)]


# ── Ground truth computation ─────────────────────────────────────────────────

def compute_ground_truth(params):
    """Compute analytically-derived ground truth parameters."""
    bl = params['baseline']
    lat = params['latency']
    A = params['A']
    tc = params['tau_c']
    tr = params['tau_r']
    pf = params['pipr_frac']

    # Constriction at stimulus offset
    tc_total = OFFSET - ONSET - lat
    constr_at_off = A * (1.0 - math.exp(-tc_total / tc))
    min_diam = bl - constr_at_off

    max_constr_mm = constr_at_off
    max_constr_pct = max_constr_mm / bl * 100.0
    time_to_max = OFFSET - ONSET  # min occurs at offset for this model

    # MCV = A / tau_c (analytical peak velocity at constriction onset)
    mcv = A / tc

    # Redilation
    sustained = pf * constr_at_off
    recoverable = constr_at_off - sustained
    redil_vel = recoverable / tr

    # T75: time from max constriction to 75% recovery
    target_recovery = 0.75 * max_constr_mm
    t75 = None
    if recoverable > 0:
        remaining_at_target = max_constr_mm - target_recovery  # = 0.25 * max_constr_mm
        # remaining constriction = sustained + recoverable * exp(-t/tau_r)
        # solve: sustained + recoverable * exp(-t/tau_r) = remaining_at_target
        exp_val = (remaining_at_target - sustained) / recoverable
        if exp_val > 0:
            t75 = -tr * math.log(exp_val)
        # if exp_val <= 0, recovery never reaches 75% (strong PIPR)

    # PIPR at 6s post-offset
    d_6s = plr_signal(OFFSET + 6.0, bl, lat, A, tc, tr, pf)
    pipr_6s_pct = (bl - d_6s) / bl * 100.0

    # PIPR plateau (10-30s post-offset) - approximate as asymptotic value
    d_plateau = bl - sustained  # asymptotic diameter
    pipr_plateau_pct = (bl - d_plateau) / bl * 100.0

    # AUC via numerical integration on clean signal (trapezoidal)
    times = [i * DT for i in range(N_SAMPLES)]
    clean = [plr_signal(t, bl, lat, A, tc, tr, pf) for t in times]

    def compute_auc(t_start_post, t_end_post):
        abs_start = OFFSET + t_start_post
        abs_end = OFFSET + t_end_post
        auc = 0.0
        for i in range(len(times) - 1):
            t_mid = (times[i] + times[i + 1]) / 2.0
            if abs_start <= t_mid <= abs_end:
                c1 = (bl - clean[i]) / bl * 100.0
                c2 = (bl - clean[i + 1]) / bl * 100.0
                auc += (c1 + c2) / 2.0 * (times[i + 1] - times[i])
        return auc

    pipr_early_auc = compute_auc(2.0, 10.0)
    pipr_late_auc = compute_auc(10.0, 30.0)

    return {
        'baseline_mm': round(bl, 4),
        'max_constriction_mm': round(max_constr_mm, 4),
        'max_constriction_pct': round(max_constr_pct, 4),
        'latency_s': round(lat, 4),
        'time_to_max_constriction_s': round(time_to_max, 4),
        'max_constriction_velocity_mm_s': round(mcv, 4),
        'redilation_velocity_mm_s': round(redil_vel, 4),
        't75_s': round(t75, 4) if t75 is not None else None,
        'pipr_6s_pct': round(pipr_6s_pct, 4),
        'pipr_plateau_pct': round(pipr_plateau_pct, 4),
        'pipr_early_auc': round(pipr_early_auc, 4),
        'pipr_late_auc': round(pipr_late_auc, 4),
    }


# ── Recording generation ─────────────────────────────────────────────────────

def generate_recording(params, blink_times=None):
    """Generate a PLR recording with optional blink artifacts."""
    times = [i * DT for i in range(N_SAMPLES)]
    bl = params['baseline']
    lat = params['latency']
    A = params['A']
    tc = params['tau_c']
    tr = params['tau_r']
    pf = params['pipr_frac']

    clean = [plr_signal(t, bl, lat, A, tc, tr, pf) for t in times]
    noisy = [d + random.gauss(0, NOISE_STD) for d in clean]

    blink_count = 0
    total_artifact_samples = 0
    if blink_times:
        for bt, bdur in blink_times:
            start_idx = int(bt * FS)
            n_samp = max(1, int(bdur * FS))
            if 0 <= start_idx and start_idx + n_samp < len(noisy):
                blink_count += 1
                total_artifact_samples += n_samp
                for j in range(n_samp):
                    noisy[start_idx + j] = 0.3 + random.gauss(0, 0.1)

    stim = [1 if ONSET <= t < OFFSET else 0 for t in times]
    artifact_pct = round(total_artifact_samples / len(times) * 100.0, 2)

    return times, noisy, stim, blink_count, artifact_pct


def write_csv(filepath, times, diameters, stimulus):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time_s', 'diameter_mm', 'stimulus'])
        for t, d, s in zip(times, diameters, stimulus):
            writer.writerow([f'{t:.4f}', f'{d:.4f}', s])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    random.seed(SEED)
    data_dir = '/app/data'
    os.makedirs(data_dir, exist_ok=True)

    # Copy protocol.json into data dir
    import shutil
    if os.path.exists('/app/protocol.json'):
        shutil.copy('/app/protocol.json', os.path.join(data_dir, 'protocol.json'))

    gt = {'conditions': {}, 'artifacts': {}, 'horner_assessment': {}}

    # ── Blue condition ────────────────────────────────────────────────────
    blue_gt = compute_ground_truth(BLUE_PARAMS)
    blink_configs = {1: None, 2: BLUE_02_BLINKS, 3: BLUE_03_BLINKS}

    for trial in range(1, 4):
        fname = f'blue_{trial:02d}.csv'
        times, noisy, stim, bc, ap = generate_recording(
            BLUE_PARAMS, blink_configs[trial])
        write_csv(os.path.join(data_dir, fname), times, noisy, stim)
        gt['artifacts'][fname] = {'blinks_detected': bc, 'artifact_pct': ap}

    gt['conditions']['blue'] = {'n_valid_trials': 3, 'average': blue_gt}

    # ── Red condition ─────────────────────────────────────────────────────
    red_gt = compute_ground_truth(RED_PARAMS)

    for trial in range(1, 4):
        fname = f'red_{trial:02d}.csv'
        times, noisy, stim, bc, ap = generate_recording(RED_PARAMS)
        write_csv(os.path.join(data_dir, fname), times, noisy, stim)
        gt['artifacts'][fname] = {'blinks_detected': bc, 'artifact_pct': ap}

    gt['conditions']['red'] = {'n_valid_trials': 3, 'average': red_gt}

    # ── Net PIPR ──────────────────────────────────────────────────────────
    gt['net_pipr_6s_pct'] = round(
        blue_gt['pipr_6s_pct'] - red_gt['pipr_6s_pct'], 4)

    # ── Horner recordings ─────────────────────────────────────────────────
    for side, params in [('right', HORNER_RIGHT_PARAMS),
                         ('left', HORNER_LEFT_PARAMS)]:
        fname = f'horner_{side}.csv'
        times, noisy, stim, bc, ap = generate_recording(params)
        write_csv(os.path.join(data_dir, fname), times, noisy, stim)
        gt['artifacts'][fname] = {'blinks_detected': bc, 'artifact_pct': ap}

    # Horner ground truth
    horner_r_gt = compute_ground_truth(HORNER_RIGHT_PARAMS)
    horner_l_gt = compute_ground_truth(HORNER_LEFT_PARAMS)

    d_right_4s = plr_signal(OFFSET + 4.0, **{k: HORNER_RIGHT_PARAMS[k]
                            for k in ['baseline', 'latency', 'A', 'tau_c',
                                      'tau_r', 'pipr_frac']})
    d_left_4s = plr_signal(OFFSET + 4.0, **{k: HORNER_LEFT_PARAMS[k]
                           for k in ['baseline', 'latency', 'A', 'tau_c',
                                     'tau_r', 'pipr_frac']})

    gt['horner_assessment'] = {
        'dilation_lag_4s_mm': round(abs(d_right_4s - d_left_4s), 4),
        'affected_eye': 'left',
        't75_right_s': horner_r_gt['t75_s'],
        't75_left_s': horner_l_gt['t75_s'],
    }

    # Write ground truth
    os.makedirs('/tests', exist_ok=True)
    with open('/tests/ground_truth.json', 'w') as f:
        json.dump(gt, f, indent=2)

    print(f"Generated {len(os.listdir(data_dir))} files in {data_dir}")
    print(f"Ground truth written to /tests/ground_truth.json")


if __name__ == '__main__':
    main()
