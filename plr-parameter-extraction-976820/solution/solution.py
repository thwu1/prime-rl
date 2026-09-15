#!/usr/bin/env python3
"""PLR parameter extraction tool following Kelbsch et al. (2019) standards.

Processes chromatic pupillometry recordings to extract standard PLR/PIPR
parameters, handles blink artifacts, and performs Horner syndrome assessment.
"""


import argparse
import csv
import json
import os
import sys

import numpy as np
from scipy.signal import savgol_filter
from scipy.interpolate import interp1d


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_protocol(input_dir):
    path = os.path.join(input_dir, 'protocol.json')
    with open(path) as f:
        return json.load(f)


def load_recording(filepath):
    times, diameters, stimulus = [], [], []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row['time_s']))
            diameters.append(float(row['diameter_mm']))
            stimulus.append(int(row['stimulus']))
    return np.array(times), np.array(diameters), np.array(stimulus)


# ── Artifact detection and removal ────────────────────────────────────────────

def detect_artifacts(times, diameters, proto):
    """Detect blink artifacts using amplitude and velocity thresholds."""
    n = len(diameters)
    is_artifact = np.zeros(n, dtype=bool)

    # Amplitude threshold: unrealistically small diameter
    amp_thresh = proto['blink_diameter_threshold_mm']
    is_artifact |= (diameters < amp_thresh)

    # Velocity threshold: physiologically implausible rate of change
    if n > 1:
        dt = np.diff(times)
        dt[dt == 0] = 1e-6
        vel = np.diff(diameters) / dt
        vel_thresh = proto['blink_velocity_threshold_mm_s']
        fast = np.abs(vel) > vel_thresh
        is_artifact[:-1] |= fast
        is_artifact[1:] |= fast

    # Expand artifact regions by 2 samples on each side to catch edges
    expanded = is_artifact.copy()
    for offset in [1, 2]:
        expanded[offset:] |= is_artifact[:-offset]
        expanded[:-offset] |= is_artifact[offset:]

    # Count contiguous blink events
    blink_count = 0
    in_blink = False
    for a in expanded:
        if a and not in_blink:
            blink_count += 1
            in_blink = True
        elif not a:
            in_blink = False

    return expanded, blink_count


def interpolate_artifacts(times, diameters, is_artifact):
    """Replace artifact regions with linearly interpolated values."""
    clean_mask = ~is_artifact
    if np.sum(clean_mask) < 2:
        return diameters.copy()

    f_interp = interp1d(
        times[clean_mask], diameters[clean_mask],
        kind='linear', fill_value='extrapolate', bounds_error=False
    )
    result = diameters.copy()
    result[is_artifact] = f_interp(times[is_artifact])
    return result


def smooth_signal(diameters, window=7, polyorder=3):
    """Apply Savitzky-Golay smoothing."""
    if len(diameters) < window:
        return diameters.copy()
    return savgol_filter(diameters, window, polyorder)


# ── Parameter extraction ──────────────────────────────────────────────────────

def compute_velocity(times, diameters):
    """Compute velocity using Savitzky-Golay derivative for noise robustness."""
    dt = np.mean(np.diff(times))
    if dt <= 0:
        return np.zeros_like(diameters)
    window = min(9, len(diameters))
    if window % 2 == 0:
        window -= 1
    if window < 5:
        return np.gradient(diameters, times)
    return savgol_filter(diameters, window, 3, deriv=1, delta=dt)


def find_latency(times, velocity, onset_time, threshold=-1.5):
    """Find latency as first time velocity drops below threshold after onset."""
    for i in range(len(times)):
        if times[i] >= onset_time and velocity[i] < threshold:
            return times[i] - onset_time
    return 0.0


def find_t75(times, diameters, min_idx, max_constr_mm, baseline):
    """Find T75: time from max constriction to 75% recovery.

    Returns None if the signal never recovers to 75% within the recording.
    """
    target_diam = diameters[min_idx] + 0.75 * max_constr_mm
    if target_diam >= baseline:
        return None

    min_time = times[min_idx]
    for i in range(min_idx + 1, len(times)):
        if diameters[i] >= target_diam:
            # Linear interpolation for sub-sample precision
            d_prev = diameters[i - 1]
            d_curr = diameters[i]
            t_prev = times[i - 1]
            t_curr = times[i]
            if d_curr != d_prev:
                frac = (target_diam - d_prev) / (d_curr - d_prev)
                t_cross = t_prev + frac * (t_curr - t_prev)
            else:
                t_cross = t_curr
            return t_cross - min_time
    return None


def extract_plr_params(times, diameters, proto):
    """Extract standard PLR/PIPR parameters from a clean, smoothed recording."""
    onset = proto['pre_stimulus_s']
    offset = onset + proto['stimulus_duration_s']

    # Baseline from pre-stimulus period
    pre_mask = times < onset
    if not np.any(pre_mask):
        return None
    baseline = float(np.mean(diameters[pre_mask]))

    # Max constriction: minimum diameter after onset
    post_onset_mask = times >= onset
    post_idx = np.where(post_onset_mask)[0]
    if len(post_idx) == 0:
        return None

    min_local_idx = np.argmin(diameters[post_onset_mask])
    min_global_idx = post_idx[min_local_idx]
    min_diam = diameters[min_global_idx]
    min_time = times[min_global_idx]

    max_constr_mm = baseline - min_diam
    max_constr_pct = max_constr_mm / baseline * 100.0 if baseline > 0 else 0.0
    time_to_max = min_time - onset

    # Velocity
    vel = compute_velocity(times, diameters)

    # MCV: peak absolute negative velocity during constriction phase
    constr_mask = (times >= onset) & (times <= min_time + 0.05)
    neg_vel_mask = constr_mask & (vel < 0)
    if np.any(neg_vel_mask):
        mcv = float(np.max(np.abs(vel[neg_vel_mask])))
    else:
        mcv = 0.0

    # Latency
    latency = find_latency(times, vel, onset)

    # Redilation velocity: peak positive velocity after min
    redil_mask = times > min_time
    pos_vel_mask = redil_mask & (vel > 0)
    if np.any(pos_vel_mask):
        redil_vel = float(np.max(vel[pos_vel_mask]))
    else:
        redil_vel = 0.0

    # T75
    t75 = find_t75(times, diameters, min_global_idx, max_constr_mm, baseline)

    # PIPR at configured time post-offset
    pipr_time = proto['pipr_amplitude_time_s']
    pipr_abs_time = offset + pipr_time
    pipr_idx = np.argmin(np.abs(times - pipr_abs_time))
    pipr_6s_pct = (baseline - diameters[pipr_idx]) / baseline * 100.0

    # PIPR plateau (late window)
    plat_start = offset + proto['pipr_late_window_s'][0]
    plat_end = offset + proto['pipr_late_window_s'][1]
    plat_mask = (times >= plat_start) & (times <= plat_end)
    if np.any(plat_mask):
        pipr_plateau_pct = float(np.mean(
            (baseline - diameters[plat_mask]) / baseline * 100.0))
    else:
        pipr_plateau_pct = 0.0

    # Early AUC
    early_start = offset + proto['pipr_early_window_s'][0]
    early_end = offset + proto['pipr_early_window_s'][1]
    early_mask = (times >= early_start) & (times <= early_end)
    if np.sum(early_mask) > 1:
        constr_pct = (baseline - diameters[early_mask]) / baseline * 100.0
        early_auc = float(np.trapezoid(constr_pct, times[early_mask]))
    else:
        early_auc = 0.0

    # Late AUC
    late_start = offset + proto['pipr_late_window_s'][0]
    late_end = offset + proto['pipr_late_window_s'][1]
    late_mask = (times >= late_start) & (times <= late_end)
    if np.sum(late_mask) > 1:
        constr_pct = (baseline - diameters[late_mask]) / baseline * 100.0
        late_auc = float(np.trapezoid(constr_pct, times[late_mask]))
    else:
        late_auc = 0.0

    return {
        'baseline_mm': round(baseline, 4),
        'max_constriction_mm': round(max_constr_mm, 4),
        'max_constriction_pct': round(max_constr_pct, 4),
        'latency_s': round(latency, 4),
        'time_to_max_constriction_s': round(time_to_max, 4),
        'max_constriction_velocity_mm_s': round(mcv, 4),
        'redilation_velocity_mm_s': round(redil_vel, 4),
        't75_s': round(t75, 4) if t75 is not None else None,
        'pipr_6s_pct': round(pipr_6s_pct, 4),
        'pipr_plateau_pct': round(pipr_plateau_pct, 4),
        'pipr_early_auc': round(early_auc, 4),
        'pipr_late_auc': round(late_auc, 4),
    }


# ── Recording processing pipeline ────────────────────────────────────────────

def process_recording(filepath, proto):
    """Full pipeline: load → detect artifacts → clean → smooth → extract."""
    times, diameters, stimulus = load_recording(filepath)

    is_artifact, blink_count = detect_artifacts(times, diameters, proto)
    artifact_pct = float(np.sum(is_artifact) / len(is_artifact) * 100.0)

    artifact_info = {
        'blinks_detected': int(blink_count),
        'artifact_pct': round(artifact_pct, 2),
    }

    # Reject trial if too many artifacts
    if artifact_pct > proto['artifact_trial_threshold_pct']:
        return None, artifact_info

    # Clean and smooth
    clean_diam = interpolate_artifacts(times, diameters, is_artifact)
    smooth_diam = smooth_signal(clean_diam)

    params = extract_plr_params(times, smooth_diam, proto)
    return params, artifact_info


def average_params(param_list):
    """Average parameters across valid trials."""
    if not param_list:
        return None
    result = {}
    for key in param_list[0]:
        vals = [p[key] for p in param_list if p[key] is not None]
        if not vals:
            result[key] = None
        else:
            result[key] = round(sum(vals) / len(vals), 4)
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='PLR parameter extraction (Kelbsch et al. 2019 standards)')
    parser.add_argument('--input', required=True, help='Input data directory')
    parser.add_argument('--output', required=True, help='Output results directory')
    args = parser.parse_args()

    proto = load_protocol(args.input)
    os.makedirs(args.output, exist_ok=True)

    report = {
        'conditions': {},
        'net_pipr_6s_pct': 0.0,
        'horner_assessment': {},
        'artifact_summary': {},
    }

    # ── Process chromatic conditions ──────────────────────────────────────
    for condition in proto['conditions']:
        trial_params = []
        n_valid = 0
        for trial in range(1, proto['trials_per_condition'] + 1):
            fname = f'{condition}_{trial:02d}.csv'
            filepath = os.path.join(args.input, fname)
            if not os.path.exists(filepath):
                continue
            params, artifact_info = process_recording(filepath, proto)
            report['artifact_summary'][fname] = artifact_info
            if params is not None:
                trial_params.append(params)
                n_valid += 1

        avg = average_params(trial_params)
        report['conditions'][condition] = {
            'n_valid_trials': n_valid,
            'average': avg if avg else {},
        }

    # ── Net PIPR ─────────────────────────────────────────────────────────
    blue_avg = report['conditions'].get('blue', {}).get('average', {})
    red_avg = report['conditions'].get('red', {}).get('average', {})
    blue_pipr = blue_avg.get('pipr_6s_pct')
    red_pipr = red_avg.get('pipr_6s_pct')
    if blue_pipr is not None and red_pipr is not None:
        report['net_pipr_6s_pct'] = round(blue_pipr - red_pipr, 4)

    # ── Horner assessment ────────────────────────────────────────────────
    horner_data = {}
    onset = proto['pre_stimulus_s']
    offset = onset + proto['stimulus_duration_s']
    lag_time = proto['horner_dilation_lag_time_s']
    target_time = offset + lag_time

    for side in ['left', 'right']:
        fname = f'horner_{side}.csv'
        filepath = os.path.join(args.input, fname)
        if not os.path.exists(filepath):
            continue

        params, artifact_info = process_recording(filepath, proto)
        report['artifact_summary'][fname] = artifact_info

        if params is None:
            continue

        # Get diameter at dilation lag time from smoothed signal
        times, diameters, _ = load_recording(filepath)
        is_art, _ = detect_artifacts(times, diameters, proto)
        clean = interpolate_artifacts(times, diameters, is_art)
        smooth = smooth_signal(clean)
        lag_idx = np.argmin(np.abs(times - target_time))

        horner_data[side] = {
            'params': params,
            'diam_at_lag': float(smooth[lag_idx]),
        }

    if 'left' in horner_data and 'right' in horner_data:
        dilation_lag = abs(
            horner_data['right']['diam_at_lag'] -
            horner_data['left']['diam_at_lag']
        )

        t75_left = horner_data['left']['params']['t75_s']
        t75_right = horner_data['right']['params']['t75_s']

        # Affected eye: the one with slower redilation (longer T75)
        if t75_left is not None and t75_right is not None:
            affected = 'left' if t75_left > t75_right else 'right'
        elif t75_left is None and t75_right is not None:
            affected = 'left'  # T75 undefined → very slow redilation
        elif t75_right is None and t75_left is not None:
            affected = 'right'
        else:
            # Both undefined: compare diameters at lag time
            if horner_data['left']['diam_at_lag'] < horner_data['right']['diam_at_lag']:
                affected = 'left'
            else:
                affected = 'right'

        report['horner_assessment'] = {
            'dilation_lag_4s_mm': round(dilation_lag, 4),
            'affected_eye': affected,
            't75_left_s': t75_left,
            't75_right_s': t75_right,
        }
    else:
        report['horner_assessment'] = {
            'dilation_lag_4s_mm': 0.0,
            'affected_eye': 'none',
            't75_left_s': None,
            't75_right_s': None,
        }

    # ── Write report ─────────────────────────────────────────────────────
    report_path = os.path.join(args.output, 'report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {report_path}")


if __name__ == '__main__':
    main()
