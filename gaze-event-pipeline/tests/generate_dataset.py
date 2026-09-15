#!/usr/bin/env python3
"""Generate synthetic BIDS eye-tracking dataset with known ground truth."""

import os
import sys
import json
import gzip
import math
import numpy as np

NOISE_SD = 0.1  # pixel noise sd (very clean signal)
PUPIL_BASELINE = 3500.0
PUPIL_NOISE_SD = 20.0

SCREEN_A = {
    "ScreenDistance": 0.6,
    "ScreenSize": [0.531, 0.299],
    "ScreenResolution": [1920, 1080],
    "ScreenOrigin": ["top", "left"],
    "ScreenRefreshRate": 60
}

SCREEN_B = {
    "ScreenDistance": 0.7,
    "ScreenSize": [0.597, 0.336],
    "ScreenResolution": [2560, 1440],
    "ScreenOrigin": ["top", "left"],
    "ScreenRefreshRate": 120
}


def compute_dva(x1, y1, x2, y2, screen):
    """Compute visual angle in degrees between two pixel positions."""
    sw, sh = screen["ScreenSize"]
    rw, rh = screen["ScreenResolution"]
    dist = screen["ScreenDistance"]
    dx_m = (x2 - x1) * (sw / rw)
    dy_m = (y2 - y1) * (sh / rh)
    disp_m = math.sqrt(dx_m ** 2 + dy_m ** 2)
    return math.degrees(2.0 * math.atan2(disp_m, 2.0 * dist))


def generate_recording(rng, fs, timestamp_base, events_spec, screen):
    """Generate synthetic gaze data for one recording.

    events_spec: list of tuples:
      ('fixation', duration_ms, cx, cy)
      ('saccade', duration_ms, sx, sy, ex, ey)
      ('blink', duration_ms)
      ('dropout', duration_ms, cx, cy)  -- NaN coords, non-zero pupil
    """
    timestamps = []
    x_coords = []
    y_coords = []
    pupil_sizes = []
    ground_truth_events = []

    dt_ms = 1000.0 / fs
    sample_idx = 0

    for spec in events_spec:
        event_type = spec[0]
        duration_ms = spec[1]
        n_samples = int(round(duration_ms / dt_ms))
        onset_time = timestamp_base + sample_idx * dt_ms

        if event_type == 'fixation':
            cx, cy = spec[2], spec[3]
            for j in range(n_samples):
                t = timestamp_base + (sample_idx + j) * dt_ms
                timestamps.append(t)
                x_coords.append(cx + rng.normal(0, NOISE_SD))
                y_coords.append(cy + rng.normal(0, NOISE_SD))
                pupil_sizes.append(PUPIL_BASELINE + rng.normal(0, PUPIL_NOISE_SD))
            ground_truth_events.append({
                'onset': onset_time,
                'duration': n_samples * dt_ms,
                'trial_type': 'fixation',
                'blink': 0,
                'amplitude_dva': None,
                'n_samples': n_samples,
            })

        elif event_type == 'saccade':
            sx, sy, ex, ey = spec[2], spec[3], spec[4], spec[5]
            for j in range(n_samples):
                t = timestamp_base + (sample_idx + j) * dt_ms
                frac = j / max(n_samples - 1, 1)
                x = sx + (ex - sx) * frac
                y = sy + (ey - sy) * frac
                timestamps.append(t)
                x_coords.append(x)
                y_coords.append(y)
                pupil_sizes.append(PUPIL_BASELINE + rng.normal(0, PUPIL_NOISE_SD))
            amp = compute_dva(sx, sy, ex, ey, screen)
            ground_truth_events.append({
                'onset': onset_time,
                'duration': n_samples * dt_ms,
                'trial_type': 'saccade',
                'blink': 0,
                'amplitude_dva': round(amp, 3),
                'n_samples': n_samples,
            })

        elif event_type == 'blink':
            for j in range(n_samples):
                t = timestamp_base + (sample_idx + j) * dt_ms
                timestamps.append(t)
                x_coords.append(float('nan'))
                y_coords.append(float('nan'))
                pupil_sizes.append(0.0)
            ground_truth_events.append({
                'onset': onset_time,
                'duration': n_samples * dt_ms,
                'trial_type': 'blink',
                'blink': 1,
                'amplitude_dva': None,
                'n_samples': n_samples,
            })

        elif event_type == 'dropout':
            # Signal dropout: NaN coordinates but non-zero pupil
            # Should be classified as fixation (no measurable velocity)
            for j in range(n_samples):
                t = timestamp_base + (sample_idx + j) * dt_ms
                timestamps.append(t)
                x_coords.append(float('nan'))
                y_coords.append(float('nan'))
                pupil_sizes.append(PUPIL_BASELINE + rng.normal(0, PUPIL_NOISE_SD))
            ground_truth_events.append({
                'onset': onset_time,
                'duration': n_samples * dt_ms,
                'trial_type': 'fixation',
                'blink': 0,
                'amplitude_dva': None,
                'n_samples': n_samples,
            })

        sample_idx += n_samples

    data = {
        'timestamp': timestamps,
        'x_coordinate': x_coords,
        'y_coordinate': y_coords,
        'pupil_size': pupil_sizes,
    }
    return data, ground_truth_events


def write_physio_tsv_gz(path, data, column_order=None):
    """Write gaze data as headerless gzip'd TSV."""
    if column_order is None:
        column_order = ['timestamp', 'x_coordinate', 'y_coordinate', 'pupil_size']
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, 'wt') as f:
        n = len(data['timestamp'])
        for i in range(n):
            fields = []
            for col in column_order:
                val = data[col][i]
                if col == 'timestamp':
                    fields.append(f"{val:.1f}")
                elif col == 'pupil_size':
                    fields.append(f"{val:.1f}")
                elif col in ('x_coordinate', 'y_coordinate'):
                    fields.append("n/a" if math.isnan(val) else f"{val:.2f}")
                else:
                    fields.append(f"{val:.2f}")
            f.write('\t'.join(fields) + '\n')


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def merge_contiguous_fixations(events):
    """Merge contiguous fixation events (e.g., across dropout gaps)."""
    merged = []
    for evt in events:
        if (merged and evt['trial_type'] == 'fixation'
                and merged[-1]['trial_type'] == 'fixation'):
            merged[-1]['duration'] += evt['duration']
            merged[-1]['n_samples'] += evt['n_samples']
        else:
            merged.append(dict(evt))
    return merged


def compute_ground_truth_metrics(gt_events, fs):
    """Compute expected metrics from ground truth events."""
    sac_amps = [e['amplitude_dva'] for e in gt_events
                if e['trial_type'] == 'saccade']
    fix_durs = [e['duration'] for e in gt_events
                if e['trial_type'] == 'fixation']
    blink_samples = sum(e['n_samples'] for e in gt_events
                        if e['trial_type'] == 'blink')
    total_samples = sum(e['n_samples'] for e in gt_events)
    return {
        'n_saccades': sum(1 for e in gt_events if e['trial_type'] == 'saccade'),
        'n_blinks': sum(1 for e in gt_events if e['trial_type'] == 'blink'),
        'n_fixations': sum(1 for e in gt_events if e['trial_type'] == 'fixation'),
        'saccade_onsets': [e['onset'] for e in gt_events
                          if e['trial_type'] == 'saccade'],
        'saccade_amplitudes': sac_amps,
        'total_duration_sec': total_samples / float(fs),
        'mean_saccade_amplitude_dva': (
            sum(sac_amps) / len(sac_amps) if sac_amps else 0.0),
        'mean_fixation_duration_ms': (
            sum(fix_durs) / len(fix_durs) if fix_durs else 0.0),
        'pct_blink': (
            blink_samples / total_samples * 100.0 if total_samples > 0 else 0.0),
    }


def generate_dataset(output_dir):
    """Generate complete synthetic BIDS eye-tracking dataset."""
    rng = np.random.RandomState(42)
    os.makedirs(output_dir, exist_ok=True)

    # ---- Root-level BIDS files ----
    write_json(os.path.join(output_dir, 'dataset_description.json'), {
        "Name": "synthetic_eyetracking",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "CC0",
    })

    with open(os.path.join(output_dir, 'participants.tsv'), 'w') as f:
        f.write("participant_id\n")
        f.write("sub-01\n")
        f.write("sub-02\n")
        f.write("sub-03\n")

    write_json(os.path.join(output_dir, 'participants.json'), {
        "participant_id": {"Description": "Participant identifier"}
    })

    # Task-level physio sidecar (inherited by all recordings)
    write_json(os.path.join(output_dir, 'task-gaze_physio.json'), {
        "PhysioType": "eyetrack",
        "Manufacturer": "SyntheticTracker",
        "Columns": ["timestamp", "x_coordinate", "y_coordinate", "pupil_size"],
        "SampleCoordinateSystem": "gaze-on-screen",
        "EyeTrackingMethod": "P-CR",
        "timestamp": {
            "Description": "Timestamp from eye tracker",
            "Units": "ms"
        },
        "x_coordinate": {
            "LongName": "Gaze position (x)",
            "Description": "Gaze x-coordinate on screen",
            "Units": "pixel"
        },
        "y_coordinate": {
            "LongName": "Gaze position (y)",
            "Description": "Gaze y-coordinate on screen",
            "Units": "pixel"
        },
        "pupil_size": {
            "Description": "Pupil area (0 during blinks)",
            "Units": "a.u."
        },
    })

    # Task-level events sidecar with default screen geometry (SCREEN_A)
    write_json(os.path.join(output_dir, 'task-gaze_events.json'), {
        "TaskName": "gaze",
        "StimulusPresentation": SCREEN_A
    })

    ground_truth = {}

    # ============ sub-01 ============
    sub01_dir = os.path.join(output_dir, 'sub-01', 'beh')
    os.makedirs(sub01_dir, exist_ok=True)

    # ---- sub-01, run-01 (1000 Hz, SCREEN_A) ----
    events_1 = [
        ('fixation', 1000, 960, 540),
        ('saccade',    40, 960, 540, 460, 290),
        ('fixation', 1000, 460, 290),
        ('blink',     150),
        ('fixation',  500, 460, 290),
        ('saccade',    60, 460, 290, 1400, 750),
        ('fixation', 1000, 1400, 750),
        ('saccade',    40, 1400, 750, 960, 540),
        ('fixation', 1210, 960, 540),
    ]
    data_1, gt_1 = generate_recording(rng, 1000, 5000000.0, events_1, SCREEN_A)
    write_physio_tsv_gz(
        os.path.join(sub01_dir,
                     'sub-01_task-gaze_run-01_recording-eye1_physio.tsv.gz'),
        data_1)
    write_json(
        os.path.join(sub01_dir,
                     'sub-01_task-gaze_run-01_recording-eye1_physio.json'), {
            "RecordedEye": "left",
            "StartTime": 0,
            "SamplingFrequency": 1000,
            "CalibrationCount": 1,
            "CalibrationType": "HV13",
            "AverageCalibrationError": 0.3,
            "MaximalCalibrationError": 0.6
        })
    with open(os.path.join(sub01_dir,
                           'sub-01_task-gaze_run-01_events.tsv'), 'w') as f:
        f.write("onset\tduration\n")

    metrics_1 = compute_ground_truth_metrics(gt_1, 1000)
    ground_truth['sub-01_task-gaze_run-01_recording-eye1'] = {
        'events': gt_1, 'fs': 1000, 'screen': SCREEN_A, **metrics_1
    }

    # ---- sub-01, run-02 (1000 Hz, SCREEN_A) ----
    events_2 = [
        ('fixation',  800, 300, 200),
        ('saccade',    60, 300, 200, 1600, 900),
        ('fixation', 1000, 1600, 900),
        ('saccade',    40, 1600, 900, 800, 400),
        ('fixation',  500, 800, 400),
        ('blink',     100),
        ('fixation',  400, 800, 400),
        ('saccade',    40, 800, 400, 300, 200),
        ('fixation', 1060, 300, 200),
    ]
    data_2, gt_2 = generate_recording(rng, 1000, 6000000.0, events_2, SCREEN_A)
    write_physio_tsv_gz(
        os.path.join(sub01_dir,
                     'sub-01_task-gaze_run-02_recording-eye1_physio.tsv.gz'),
        data_2)
    write_json(
        os.path.join(sub01_dir,
                     'sub-01_task-gaze_run-02_recording-eye1_physio.json'), {
            "RecordedEye": "left",
            "StartTime": 0,
            "SamplingFrequency": 1000,
            "CalibrationCount": 1,
            "CalibrationType": "HV13",
            "AverageCalibrationError": 0.35,
            "MaximalCalibrationError": 0.7
        })
    with open(os.path.join(sub01_dir,
                           'sub-01_task-gaze_run-02_events.tsv'), 'w') as f:
        f.write("onset\tduration\n")

    metrics_2 = compute_ground_truth_metrics(gt_2, 1000)
    ground_truth['sub-01_task-gaze_run-02_recording-eye1'] = {
        'events': gt_2, 'fs': 1000, 'screen': SCREEN_A, **metrics_2
    }

    # ============ sub-02 ============
    sub02_dir = os.path.join(output_dir, 'sub-02', 'beh')
    os.makedirs(sub02_dir, exist_ok=True)

    # sub-02 has different screen geometry — override at run level
    write_json(
        os.path.join(sub02_dir, 'sub-02_task-gaze_run-01_events.json'), {
            "StimulusPresentation": SCREEN_B
        })

    events_3 = [
        ('fixation', 1000, 1280, 720),
        ('saccade',    50, 1280, 720, 600, 300),
        ('fixation', 1000, 600, 300),
        ('blink',     200),
        ('fixation', 1000, 600, 300),
        ('saccade',    60, 600, 300, 2000, 1100),
        ('fixation', 1000, 2000, 1100),
        ('blink',     150),
        ('fixation',  850, 2000, 1100),
        ('saccade',    50, 2000, 1100, 1280, 720),
        ('fixation',  640, 1280, 720),
    ]
    data_3, gt_3 = generate_recording(rng, 500, 8000000.0, events_3, SCREEN_B)
    write_physio_tsv_gz(
        os.path.join(sub02_dir,
                     'sub-02_task-gaze_run-01_recording-eye1_physio.tsv.gz'),
        data_3)
    write_json(
        os.path.join(sub02_dir,
                     'sub-02_task-gaze_run-01_recording-eye1_physio.json'), {
            "RecordedEye": "right",
            "StartTime": 0,
            "SamplingFrequency": 500,
            "CalibrationCount": 2,
            "CalibrationType": "HV9",
            "AverageCalibrationError": 0.45,
            "MaximalCalibrationError": 0.9
        })
    with open(os.path.join(sub02_dir,
                           'sub-02_task-gaze_run-01_events.tsv'), 'w') as f:
        f.write("onset\tduration\n")

    metrics_3 = compute_ground_truth_metrics(gt_3, 500)
    ground_truth['sub-02_task-gaze_run-01_recording-eye1'] = {
        'events': gt_3, 'fs': 500, 'screen': SCREEN_B, **metrics_3
    }

    # ============ sub-03 ============
    sub03_dir = os.path.join(output_dir, 'sub-03', 'beh')
    os.makedirs(sub03_dir, exist_ok=True)

    # ---- sub-03, run-01: CARDIAC recording (decoy, should be skipped) ----
    cardiac_json = {
        "PhysioType": "cardiac",
        "Manufacturer": "BioSig",
        "Columns": ["timestamp", "cardiac"],
        "SamplingFrequency": 250,
        "StartTime": 0,
        "cardiac": {
            "Description": "Continuous ECG recording",
            "Units": "mV"
        },
        "timestamp": {
            "Description": "Timestamp",
            "Units": "ms"
        }
    }
    write_json(
        os.path.join(sub03_dir,
                     'sub-03_task-gaze_run-01_recording-cardiac1_physio.json'),
        cardiac_json)
    cardiac_path = os.path.join(
        sub03_dir,
        'sub-03_task-gaze_run-01_recording-cardiac1_physio.tsv.gz')
    os.makedirs(os.path.dirname(cardiac_path), exist_ok=True)
    with gzip.open(cardiac_path, 'wt') as f:
        for i in range(500):
            t = 7000000.0 + i * 4.0
            cardiac = 70.0 + 10.0 * math.sin(2 * math.pi * i / 208.33)
            cardiac += rng.normal(0, 2)
            f.write(f"{t:.1f}\t{cardiac:.2f}\n")

    # ---- sub-03, run-02: eyetrack with SWAPPED column order + signal dropout ----
    swapped_columns = ["timestamp", "pupil_size", "x_coordinate", "y_coordinate"]

    events_4 = [
        ('fixation', 800, 960, 540),
        ('saccade',   40, 960, 540, 400, 200),
        ('fixation', 500, 400, 200),
        ('dropout',   30, 400, 200),
        ('fixation', 500, 400, 200),
        ('saccade',   50, 400, 200, 1500, 800),
        ('fixation', 600, 1500, 800),
        ('blink',    100),
        ('fixation', 380, 1500, 800),
    ]
    data_4, gt_4 = generate_recording(rng, 1000, 9000000.0, events_4, SCREEN_A)
    write_physio_tsv_gz(
        os.path.join(sub03_dir,
                     'sub-03_task-gaze_run-02_recording-eye1_physio.tsv.gz'),
        data_4, column_order=swapped_columns)
    # Run-level sidecar overrides Columns to match swapped order
    write_json(
        os.path.join(sub03_dir,
                     'sub-03_task-gaze_run-02_recording-eye1_physio.json'), {
            "RecordedEye": "right",
            "StartTime": 0,
            "SamplingFrequency": 1000,
            "Columns": swapped_columns,
            "CalibrationCount": 1,
            "CalibrationType": "HV5",
            "AverageCalibrationError": 0.5,
            "MaximalCalibrationError": 1.0
        })
    with open(os.path.join(sub03_dir,
                           'sub-03_task-gaze_run-02_events.tsv'), 'w') as f:
        f.write("onset\tduration\n")

    # Merge contiguous fixations (dropout merges with surrounding fixations)
    merged_gt4 = merge_contiguous_fixations(gt_4)
    metrics_4 = compute_ground_truth_metrics(merged_gt4, 1000)
    ground_truth['sub-03_task-gaze_run-02_recording-eye1'] = {
        'events': merged_gt4, 'fs': 1000, 'screen': SCREEN_A, **metrics_4
    }

    # Write ground truth for test verification
    gt_path = os.path.join(os.path.dirname(output_dir.rstrip('/')),
                           'ground_truth.json')
    write_json(gt_path, ground_truth)

    return ground_truth


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else '/app/dataset'
    gt = generate_dataset(out)
    print(f"Generated BIDS dataset at {out} with {len(gt)} recordings")
    for k, v in gt.items():
        print(f"  {k}: {v['n_saccades']} saccades, {v['n_blinks']} blinks, "
              f"{v['n_fixations']} fixations")
