#!/usr/bin/env python3
"""Gaze-during-reading analysis pipeline.

Processes raw gaze data to extract fixations, compute word-level reading
measures, and evaluate cross-validated prediction of reading skill.

"""
import csv
import json
import math
import os
import sys

import numpy as np


def load_csv(path):
    """Load a CSV file as a list of dicts."""
    with open(path) as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Fixation detection
# ---------------------------------------------------------------------------

def detect_fixations_ivt(timestamps, x_pos, y_pos, pupil_diam,
                         velocity_threshold=100.0, min_duration_ms=80):
    """Velocity-threshold fixation detection (I-VT).

    Parameters
    ----------
    timestamps : list[float]
        Per-sample timestamps in milliseconds.
    x_pos, y_pos : list[float]
        Horizontal and vertical gaze position in pixels.
    pupil_diam : list[float]
        Pupil diameter values (0 indicates blink).
    velocity_threshold : float
        Velocity cutoff in px/s for fixation classification.
    min_duration_ms : float
        Minimum fixation duration in milliseconds.

    Returns
    -------
    list[dict]
        Each dict has keys: onset_ms, offset_ms, duration_ms,
        centroid_x, centroid_y.
    """
    n = len(timestamps)
    if n < 2:
        return []

    # Compute sample-to-sample velocity in px/s
    velocities = []
    for i in range(n - 1):
        dt = timestamps[i + 1] - timestamps[i]
        if dt <= 0:
            velocities.append(float('inf'))
            continue
        dx = x_pos[i + 1] - x_pos[i]
        dy = y_pos[i + 1] - y_pos[i]
        displacement = math.sqrt(dx * dx + dy * dy)
        speed = displacement / dt * 1000.0
        velocities.append(speed)
    velocities.append(float('inf'))

    # Classify each sample as fixation or saccade
    is_fixation = [velocities[i] <= velocity_threshold for i in range(n)]

    # Group consecutive fixation samples
    groups = []
    current = []
    for i in range(n):
        if is_fixation[i]:
            current.append(i)
        else:
            if current:
                groups.append(current)
                current = []
    if current:
        groups.append(current)

    # Filter by minimum duration and compute centroids
    fixations = []
    for g in groups:
        onset = timestamps[g[0]]
        offset = timestamps[g[-1]]
        dur = offset - onset
        if dur < min_duration_ms:
            continue
        cx = sum(x_pos[j] for j in g) / len(g)
        cy = sum(y_pos[j] for j in g) / len(g)
        fixations.append({
            'onset_ms': onset,
            'offset_ms': offset,
            'duration_ms': dur,
            'centroid_x': cx,
            'centroid_y': cy,
        })

    return fixations


# ---------------------------------------------------------------------------
# Fixation-to-word mapping
# ---------------------------------------------------------------------------

def map_to_nearest_word(fixations, word_aois):
    """Map each fixation to the nearest word AOI by Euclidean distance."""
    result = []
    for fix in fixations:
        best_idx = -1
        best_dist = float('inf')
        for aoi in word_aois:
            cx = (float(aoi['x_min']) + float(aoi['x_max'])) / 2.0
            cy = (float(aoi['y_min']) + float(aoi['y_max'])) / 2.0
            d = math.sqrt((fix['centroid_x'] - cx) ** 2 +
                          (fix['centroid_y'] - cy) ** 2)
            if d < best_dist:
                best_dist = d
                best_idx = int(aoi['word_index'])
        result.append({**fix, 'word_index': best_idx})
    return result


# ---------------------------------------------------------------------------
# Reading measures
# ---------------------------------------------------------------------------

def compute_word_measures(mapped_fixations, n_words):
    """Compute per-word reading measures from temporally ordered fixations.

    Parameters
    ----------
    mapped_fixations : list[dict]
        Fixation dicts with at least 'word_index' and 'duration_ms',
        in temporal order.
    n_words : int
        Number of words in the text.

    Returns
    -------
    dict
        Mapping word_index -> {FFD, GD, TRT, skip, regression}.
    """
    measures = {}
    for w in range(n_words):
        measures[w] = {
            'FFD': 0.0, 'GD': 0.0, 'TRT': 0.0,
            'skip': True, 'regression': False,
        }

    # Track whether first-pass reading has concluded
    first_pass_ended = False
    prev_word = None

    for fix in mapped_fixations:
        w = fix['word_index']
        dur = fix['duration_ms']

        measures[w]['TRT'] += dur
        measures[w]['skip'] = False

        # A backward saccade indicates a regression
        if prev_word is not None and w < prev_word:
            first_pass_ended = True

        if not first_pass_ended:
            if measures[w]['FFD'] == 0:
                measures[w]['FFD'] = dur
            measures[w]['GD'] += dur
        else:
            measures[w]['regression'] = True

        prev_word = w

    return measures


# ---------------------------------------------------------------------------
# Trial-level feature aggregation
# ---------------------------------------------------------------------------

def aggregate_trial(measures):
    """Compute trial-level feature vector from word-level measures."""
    words = list(measures.values())
    n = len(words)

    ffds = [w['FFD'] for w in words if w['FFD'] > 0]
    gds = [w['GD'] for w in words if w['GD'] > 0]
    trts = [w['TRT'] for w in words if w['TRT'] > 0]

    return {
        'mean_FFD': float(np.mean(ffds)) if ffds else 0.0,
        'mean_GD': float(np.mean(gds)) if gds else 0.0,
        'mean_TRT': float(np.mean(trts)) if trts else 0.0,
        'skip_rate': sum(1 for w in words if w['skip']) / n,
        'regression_rate': sum(1 for w in words if w['regression']) / n,
        'total_fixation_count': sum(1 for w in words if w['TRT'] > 0),
        'total_reading_time_ms': sum(w['TRT'] for w in words),
    }


# ---------------------------------------------------------------------------
# Ridge regression
# ---------------------------------------------------------------------------

def ridge_predict(X_train, y_train, X_test, alpha=1.0):
    """Ridge regression: w = (X^T X + alpha I)^{-1} X^T y."""
    X = np.array(X_train, dtype=float)
    y = np.array(y_train, dtype=float)
    Xt = np.array(X_test, dtype=float)
    XtX = X.T @ X + alpha * np.eye(X.shape[1])
    w = np.linalg.solve(XtX, X.T @ y)
    return Xt @ w


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------

def make_cv_splits(trials, regime):
    """Generate cross-validation folds for a given regime."""
    readers = sorted(set(t['reader'] for t in trials))
    texts = sorted(set(t['text'] for t in trials))

    folds = []
    if regime == 'unseen_reader':
        for r in readers:
            train = [t for t in trials if t['reader'] != r]
            test = [t for t in trials if t['reader'] == r]
            folds.append((train, test))

    elif regime == 'unseen_text':
        for tx in texts:
            train = [t for t in trials if t['text'] != tx]
            test = [t for t in trials if t['text'] == tx]
            folds.append((train, test))

    elif regime == 'unseen_both':
        for r in readers:
            for tx in texts:
                # Hold out the specific reader-text pair
                train = [t for t in trials
                         if not (t['reader'] == r and t['text'] == tx)]
                test = [t for t in trials
                        if t['reader'] == r and t['text'] == tx]
                folds.append((train, test))

    return folds


def evaluate_regime(folds, feature_keys):
    """Run cross-validation folds and return pooled RMSE and R-squared."""
    all_true = []
    all_pred = []

    for train, test in folds:
        X_tr = [[t['features'][k] for k in feature_keys] for t in train]
        y_tr = [t['skill'] for t in train]
        X_te = [[t['features'][k] for k in feature_keys] for t in test]
        y_te = [t['skill'] for t in test]

        preds = ridge_predict(X_tr, y_tr, X_te)
        all_true.extend(y_te)
        all_pred.extend(preds.tolist())

    true_arr = np.array(all_true)
    pred_arr = np.array(all_pred)
    rmse = float(np.sqrt(np.mean((true_arr - pred_arr) ** 2)))
    ss_res = float(np.sum((true_arr - pred_arr) ** 2))
    ss_tot = float(np.sum((true_arr - np.mean(true_arr)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return rmse, r2


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data_dir = '/app/data'

    # Load data
    raw_gaze = load_csv(os.path.join(data_dir, 'raw_gaze.csv'))
    word_aois = load_csv(os.path.join(data_dir, 'word_aois.csv'))
    participants = load_csv(os.path.join(data_dir, 'participants.csv'))
    stimuli = load_csv(os.path.join(data_dir, 'stimuli.csv'))

    skill_map = {p['participant_id']: float(p['reading_skill_score'])
                 for p in participants}
    nwords_map = {s['text_id']: int(s['num_words']) for s in stimuli}

    # Group gaze data by (participant, text) trial
    trials_gaze = {}
    for row in raw_gaze:
        key = (row['participant_id'], row['text_id'])
        trials_gaze.setdefault(key, []).append(row)

    all_fixations = []
    trials = []

    for (pid, tid), rows in sorted(trials_gaze.items()):
        ts = [float(r['timestamp_ms']) for r in rows]
        xs = [float(r['x_px']) for r in rows]
        ys = [float(r['y_px']) for r in rows]
        pd_vals = [float(r['pupil_diameter']) for r in rows]

        fixations = detect_fixations_ivt(ts, xs, ys, pd_vals)
        text_aois = [a for a in word_aois if a['text_id'] == tid]
        mapped = map_to_nearest_word(fixations, text_aois)
        n_words = nwords_map[tid]
        wm = compute_word_measures(mapped, n_words)
        features = aggregate_trial(wm)

        all_fixations.extend(fixations)
        trials.append({
            'reader': pid,
            'text': tid,
            'skill': skill_map[pid],
            'features': features,
            'word_measures': wm,
        })

    # Fixation summary
    total_fixations = len(all_fixations)
    durations = [f['duration_ms'] for f in all_fixations]
    mean_duration = float(np.mean(durations)) if durations else 0.0

    # Saccade amplitude
    mean_saccade_amplitude = 0.0

    # Reading measures summary
    all_ffds, all_gds, all_trts = [], [], []
    all_skips, all_regs = [], []
    for t in trials:
        for w_idx, m in t['word_measures'].items():
            if m['FFD'] > 0:
                all_ffds.append(m['FFD'])
            if m['GD'] > 0:
                all_gds.append(m['GD'])
            if m['TRT'] > 0:
                all_trts.append(m['TRT'])
            all_skips.append(1 if m['skip'] else 0)
            all_regs.append(1 if m['regression'] else 0)

    # Cross-validation evaluation
    feature_keys = ['mean_FFD', 'mean_GD', 'mean_TRT', 'skip_rate',
                    'regression_rate', 'total_fixation_count',
                    'total_reading_time_ms']

    eval_results = {}
    split_sizes = {}
    for regime in ('unseen_reader', 'unseen_text', 'unseen_both'):
        folds = make_cv_splits(trials, regime)
        rmse, r2 = evaluate_regime(folds, feature_keys)
        eval_results[regime] = {'rmse': round(rmse, 6), 'r2': round(r2, 6)}
        train_sizes = [len(tr) for tr, te in folds]
        test_sizes = [len(te) for tr, te in folds]
        split_sizes[regime] = {
            'n_folds': len(folds),
            'mean_train_size': int(np.mean(train_sizes)),
            'mean_test_size': int(np.mean(test_sizes)),
        }

    results = {
        'fixation_summary': {
            'total_fixations': total_fixations,
            'mean_fixation_duration_ms': round(mean_duration, 2),
            'mean_saccade_amplitude_px': round(mean_saccade_amplitude, 2),
        },
        'reading_measures_summary': {
            'mean_FFD': round(float(np.mean(all_ffds)), 2) if all_ffds else 0.0,
            'mean_GD': round(float(np.mean(all_gds)), 2) if all_gds else 0.0,
            'mean_TRT': round(float(np.mean(all_trts)), 2) if all_trts else 0.0,
            'overall_skip_rate': round(float(np.mean(all_skips)), 4),
            'overall_regression_rate': round(float(np.mean(all_regs)), 4),
        },
        'evaluation': eval_results,
        'split_sizes': split_sizes,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print('Pipeline complete — results written to /app/results.json',
          file=sys.stderr)


if __name__ == '__main__':
    main()
