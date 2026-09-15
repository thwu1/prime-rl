#!/usr/bin/env python3
"""Reference implementation: gaze-during-reading analysis pipeline.

Processes raw gaze data, detects fixations and saccades from the raw
position signal, maps fixations to word interest areas, and computes
psycholinguistic reading measures including go-past time.
"""

import argparse
import csv
import math
import os


def _nanmean(vals):
    """Compute mean of non-NaN values."""
    clean = [v for v in vals if not math.isnan(v)]
    return sum(clean) / len(clean) if clean else float('nan')


def _nanmedian(vals):
    """Compute median of non-NaN values."""
    clean = sorted(v for v in vals if not math.isnan(v))
    if not clean:
        return float('nan')
    n = len(clean)
    if n % 2 == 1:
        return clean[n // 2]
    return (clean[n // 2 - 1] + clean[n // 2]) / 2.0


def load_gaze_data(filepath):
    """Load gaze data from a CSV file."""
    timestamps = []
    x_pos = []
    y_pos = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            timestamps.append(int(row['timestamp_ms']))
            try:
                x = float(row['x_deg'])
            except ValueError:
                x = float('nan')
            try:
                y = float(row['y_deg'])
            except ValueError:
                y = float('nan')
            x_pos.append(x)
            y_pos.append(y)
    return timestamps, x_pos, y_pos


def load_aois(filepath):
    """Load AOI definitions grouped by passage_id."""
    aois = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row['passage_id']
            if pid not in aois:
                aois[pid] = []
            aois[pid].append({
                'word_idx': int(row['word_idx']),
                'word_text': row['word_text'],
                'x_min': float(row['x_min']),
                'y_min': float(row['y_min']),
                'x_max': float(row['x_max']),
                'y_max': float(row['y_max']),
            })
    return aois


def apply_blink_margin(x, y, margin_ms=50):
    """Set samples within margin_ms of any NaN gap to NaN.

    Blink-adjacent samples are contaminated by pupil-recovery artifacts
    and must be excluded before event detection.
    """
    n = len(x)
    x_out = list(x)
    y_out = list(y)

    # Find NaN gap boundaries
    in_nan = False
    nan_starts = []
    nan_ends = []
    for i in range(n):
        if math.isnan(x[i]):
            if not in_nan:
                nan_starts.append(i)
                in_nan = True
        else:
            if in_nan:
                nan_ends.append(i - 1)
                in_nan = False
    if in_nan:
        nan_ends.append(n - 1)

    # Expand each NaN gap by the margin
    for start, end in zip(nan_starts, nan_ends):
        m_start = max(0, start - margin_ms)
        m_end = min(n - 1, end + margin_ms)
        for i in range(m_start, m_end + 1):
            x_out[i] = float('nan')
            y_out[i] = float('nan')

    return x_out, y_out


def compute_velocity(timestamps, x, y):
    """Compute 2D velocity using central differences."""
    n = len(timestamps)
    dt = 0.001  # 1 ms in seconds

    vx = [float('nan')] * n
    vy = [float('nan')] * n

    if n < 2:
        return vx, vy

    # Forward difference for first sample
    if not (math.isnan(x[0]) or math.isnan(x[1]) or
            math.isnan(y[0]) or math.isnan(y[1])):
        vx[0] = (x[1] - x[0]) / dt
        vy[0] = (y[1] - y[0]) / dt

    # Central differences for interior samples
    for i in range(1, n - 1):
        if not (math.isnan(x[i - 1]) or math.isnan(x[i + 1]) or
                math.isnan(y[i - 1]) or math.isnan(y[i + 1])):
            vx[i] = (x[i + 1] - x[i - 1]) / (2 * dt)
            vy[i] = (y[i + 1] - y[i - 1]) / (2 * dt)

    # Backward difference for last sample
    if not (math.isnan(x[n - 2]) or math.isnan(x[n - 1]) or
            math.isnan(y[n - 2]) or math.isnan(y[n - 1])):
        vx[n - 1] = (x[n - 1] - x[n - 2]) / dt
        vy[n - 1] = (y[n - 1] - y[n - 2]) / dt

    return vx, vy


def detect_fixations_ivt(timestamps, x, y, vx, vy,
                         threshold=30.0, min_duration_ms=80):
    """Detect fixations using the I-VT algorithm."""
    n = len(timestamps)
    speed = []
    for i in range(n):
        if math.isnan(vx[i]) or math.isnan(vy[i]):
            speed.append(float('nan'))
        else:
            speed.append(math.sqrt(vx[i] ** 2 + vy[i] ** 2))

    fixations = []
    in_fix = False
    start = 0

    for i in range(n):
        is_candidate = (not math.isnan(speed[i])) and speed[i] < threshold
        if is_candidate and not in_fix:
            start = i
            in_fix = True
        elif not is_candidate and in_fix:
            onset = timestamps[start]
            offset = timestamps[i - 1]
            duration = offset - onset
            if duration >= min_duration_ms:
                cx = _nanmean(x[start:i])
                cy = _nanmean(y[start:i])
                if not (math.isnan(cx) or math.isnan(cy)):
                    fixations.append({
                        'onset_ms': onset,
                        'offset_ms': offset,
                        'duration_ms': duration,
                        'x_center': round(cx, 6),
                        'y_center': round(cy, 6),
                    })
            in_fix = False

    # Handle fixation at end of data
    if in_fix:
        onset = timestamps[start]
        offset = timestamps[-1]
        duration = offset - onset
        if duration >= min_duration_ms:
            cx = _nanmean(x[start:])
            cy = _nanmean(y[start:])
            if not (math.isnan(cx) or math.isnan(cy)):
                fixations.append({
                    'onset_ms': onset,
                    'offset_ms': offset,
                    'duration_ms': duration,
                    'x_center': round(cx, 6),
                    'y_center': round(cy, 6),
                })

    return fixations


def compute_engbert_threshold(vx, vy):
    """Compute noise-adaptive velocity threshold (Engbert & Kliegl)."""
    valid_vx = [v for v in vx if not math.isnan(v)]
    valid_vy = [v for v in vy if not math.isnan(v)]

    if not valid_vx or not valid_vy:
        return (1e-10, 1e-10)

    med_vx = _nanmedian(valid_vx)
    med_vy = _nanmedian(valid_vy)

    deviations_x = [(v - med_vx) ** 2 for v in valid_vx]
    deviations_y = [(v - med_vy) ** 2 for v in valid_vy]

    th_x = math.sqrt(_nanmedian(deviations_x))
    th_y = math.sqrt(_nanmedian(deviations_y))

    th_x = max(th_x, 1e-10)
    th_y = max(th_y, 1e-10)

    return (th_x, th_y)


def detect_saccades_engbert(timestamps, vx, vy,
                            lambda_factor=6.0, min_duration_ms=6):
    """Detect saccades using the Engbert & Kliegl algorithm with
    noise-adaptive elliptic velocity threshold."""
    th_x, th_y = compute_engbert_threshold(vx, vy)
    r_x = lambda_factor * th_x
    r_y = lambda_factor * th_y

    n = len(timestamps)
    saccades = []
    in_sac = False
    start = 0

    for i in range(n):
        if math.isnan(vx[i]) or math.isnan(vy[i]):
            is_candidate = False
        else:
            test_val = (vx[i] / r_x) ** 2 + (vy[i] / r_y) ** 2
            is_candidate = test_val > 1.0

        if is_candidate and not in_sac:
            start = i
            in_sac = True
        elif not is_candidate and in_sac:
            onset = timestamps[start]
            offset = timestamps[i - 1]
            duration = offset - onset
            if duration >= min_duration_ms:
                saccades.append({
                    'onset_ms': onset,
                    'offset_ms': offset,
                    'duration_ms': duration,
                })
            in_sac = False

    if in_sac:
        onset = timestamps[start]
        offset = timestamps[-1]
        duration = offset - onset
        if duration >= min_duration_ms:
            saccades.append({
                'onset_ms': onset,
                'offset_ms': offset,
                'duration_ms': duration,
            })

    return saccades


def map_fixation_to_word(fx, fy, aois):
    """Map a fixation centroid to a word AOI."""
    # Containment test
    for aoi in aois:
        if (aoi['x_min'] <= fx <= aoi['x_max'] and
                aoi['y_min'] <= fy <= aoi['y_max']):
            return aoi['word_idx']

    # Nearest-neighbor fallback
    min_dist = float('inf')
    nearest = -1
    for aoi in aois:
        cx = (aoi['x_min'] + aoi['x_max']) / 2
        cy = (aoi['y_min'] + aoi['y_max']) / 2
        dist = math.sqrt((fx - cx) ** 2 + (fy - cy) ** 2)
        if dist < min_dist:
            min_dist = dist
            nearest = aoi['word_idx']

    if min_dist <= 0.5:
        return nearest
    return -1


def compute_landing_position(fx, word_idx, aoi_map):
    """Compute relative landing position within word AOI."""
    if word_idx == -1 or word_idx not in aoi_map:
        return -1.0
    aoi = aoi_map[word_idx]
    width = aoi['x_max'] - aoi['x_min']
    if width <= 0:
        return 0.5
    lp = (fx - aoi['x_min']) / width
    return round(max(0.0, min(1.0, lp)), 6)


def compute_reading_measures(fixation_word_indices, fixation_durations,
                             fixation_x_centers, aoi_map, n_words):
    """Compute reading measures for each word in a trial.

    Implements first-pass/second-pass classification using a progressive
    word frontier, and computes go-past time (regression-path duration)
    and first-fixation landing position.
    """
    max_word_seen = -1
    is_first_pass = []

    for w in fixation_word_indices:
        if w == -1:
            is_first_pass.append(False)
            continue
        if max_word_seen <= w:
            is_first_pass.append(True)
        else:
            is_first_pass.append(False)
        max_word_seen = max(max_word_seen, w)

    final_max = max_word_seen

    measures = []
    for word_idx in range(n_words):
        # All fixations on this word
        all_fix = [(i, fixation_durations[i])
                    for i in range(len(fixation_word_indices))
                    if fixation_word_indices[i] == word_idx]
        # First-pass fixations
        fp_fix = [(i, d) for i, d in all_fix if is_first_pass[i]]
        # Second-pass fixations
        sp_fix = [(i, d) for i, d in all_fix if not is_first_pass[i]]

        ffd = fp_fix[0][1] if fp_fix else 0
        gd = sum(d for _, d in fp_fix)
        trt = sum(d for _, d in all_fix)
        was_skipped = 1 if (not fp_fix and final_max > word_idx) else 0
        was_regressed_to = 1 if sp_fix else 0

        # Go-past time (regression-path duration):
        # Sum of all fixation durations from the first first-pass fixation
        # on this word until the reader first fixates a word with index
        # greater than this word.
        if fp_fix:
            first_fp_idx = fp_fix[0][0]
            gpt = 0
            for j in range(first_fp_idx, len(fixation_word_indices)):
                if j > first_fp_idx and fixation_word_indices[j] > word_idx:
                    break
                gpt += fixation_durations[j]
        else:
            gpt = 0

        # First fixation landing position
        if fp_fix:
            fx_x = fixation_x_centers[fp_fix[0][0]]
            ffl = compute_landing_position(fx_x, word_idx, aoi_map)
        else:
            ffl = -1.0

        measures.append({
            'word_idx': word_idx,
            'first_fixation_duration': ffd,
            'gaze_duration': gd,
            'go_past_time': gpt,
            'total_reading_time': trt,
            'was_skipped': was_skipped,
            'was_regressed_to': was_regressed_to,
            'first_fixation_landing': ffl,
        })

    return measures


def main():
    parser = argparse.ArgumentParser(
        description='Gaze-during-reading analysis pipeline')
    parser.add_argument('--data-dir', default='/app/data',
                        help='Path to data directory')
    parser.add_argument('--output-dir', default='/app/output',
                        help='Path to output directory')
    args = parser.parse_args()

    data_dir = args.data_dir
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # Load AOIs
    aois = load_aois(os.path.join(data_dir, 'aois.csv'))

    # Process each trial
    all_fixations = []
    all_saccades = []
    all_measures = []

    gaze_dir = os.path.join(data_dir, 'gaze')
    for fname in sorted(os.listdir(gaze_dir)):
        if not fname.endswith('.csv'):
            continue

        trial_id = fname.replace('.csv', '')
        parts = trial_id.split('_')
        passage_id = '_'.join(parts[1:]) if len(parts) > 1 else parts[0]

        filepath = os.path.join(gaze_dir, fname)
        timestamps, x, y = load_gaze_data(filepath)

        # Apply blink-margin filtering
        x, y = apply_blink_margin(x, y, margin_ms=50)

        vx, vy = compute_velocity(timestamps, x, y)

        fixations = detect_fixations_ivt(timestamps, x, y, vx, vy)
        saccades = detect_saccades_engbert(timestamps, vx, vy)

        trial_aois = aois.get(passage_id, [])
        n_words = len(trial_aois)
        aoi_map = {a['word_idx']: a for a in trial_aois}

        word_indices = []
        word_durations = []
        word_x_centers = []
        for fix in fixations:
            fix['trial_id'] = trial_id
            w = map_fixation_to_word(fix['x_center'], fix['y_center'],
                                     trial_aois)
            fix['word_idx'] = w
            fix['landing_position'] = compute_landing_position(
                fix['x_center'], w, aoi_map)
            word_indices.append(w)
            word_durations.append(fix['duration_ms'])
            word_x_centers.append(fix['x_center'])
            all_fixations.append(fix)

        for sac in saccades:
            sac['trial_id'] = trial_id
            all_saccades.append(sac)

        if n_words > 0:
            measures = compute_reading_measures(
                word_indices, word_durations, word_x_centers,
                aoi_map, n_words)
            for m in measures:
                m['trial_id'] = trial_id
                all_measures.append(m)

    # Write fixations
    fix_cols = ['trial_id', 'onset_ms', 'offset_ms', 'duration_ms',
                'x_center', 'y_center', 'word_idx', 'landing_position']
    with open(os.path.join(output_dir, 'fixations.csv'), 'w',
              newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fix_cols)
        writer.writeheader()
        for fix in all_fixations:
            writer.writerow(fix)

    # Write saccades
    sac_cols = ['trial_id', 'onset_ms', 'offset_ms', 'duration_ms']
    with open(os.path.join(output_dir, 'saccades.csv'), 'w',
              newline='') as f:
        writer = csv.DictWriter(f, fieldnames=sac_cols)
        writer.writeheader()
        for sac in all_saccades:
            writer.writerow(sac)

    # Write reading measures
    rm_cols = ['trial_id', 'word_idx', 'first_fixation_duration',
               'gaze_duration', 'go_past_time', 'total_reading_time',
               'was_skipped', 'was_regressed_to', 'first_fixation_landing']
    with open(os.path.join(output_dir, 'reading_measures.csv'), 'w',
              newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rm_cols)
        writer.writeheader()
        for m in all_measures:
            writer.writerow(m)

    print(f'Pipeline complete. {len(all_fixations)} fixations, '
          f'{len(all_saccades)} saccades detected across '
          f'{len(set(f["trial_id"] for f in all_fixations))} trials.')


if __name__ == '__main__':
    main()
