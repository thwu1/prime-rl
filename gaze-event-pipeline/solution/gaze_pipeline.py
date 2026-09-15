#!/usr/bin/env python3
"""BIDS eye-tracking event classifier — reference solution.

Reads BIDS-formatted eye-tracking data, classifies gaze samples into
fixation/saccade/blink events using velocity-threshold identification,
writes BIDS-compliant physioevents output files, and persists all results
in a normalized SQLite database.
"""

import sys
import os
import json
import gzip
import math
import glob as globmod
import sqlite3


VELOCITY_THRESHOLD_DVA_S = 30.0  # degrees/second


def find_recordings(bids_dir):
    """Discover all eyetrack physio recordings in the BIDS dataset."""
    pattern = os.path.join(bids_dir, '**', '*_recording-*_physio.tsv.gz')
    physio_files = sorted(globmod.glob(pattern, recursive=True))
    recordings = []
    for pf in physio_files:
        meta = resolve_physio_metadata(bids_dir, pf)
        if meta.get('PhysioType') == 'eyetrack':
            screen = resolve_screen_geometry(bids_dir, pf)
            rec_id = extract_recording_id(pf)
            recordings.append({
                'path': pf,
                'metadata': meta,
                'screen': screen,
                'rec_id': rec_id,
            })
    return recordings


def extract_recording_id(physio_path):
    """Extract BIDS entity string without the _physio suffix."""
    basename = os.path.basename(physio_path)
    return basename.replace('_physio.tsv.gz', '')


def parse_bids_entities(rec_id):
    """Parse BIDS entity key-value pairs from a recording identifier."""
    parts = rec_id.split('_')
    entities = {}
    for p in parts:
        if '-' in p:
            key, val = p.split('-', 1)
            entities[key] = val
    return entities


def resolve_physio_metadata(bids_dir, physio_path):
    """Resolve JSON metadata with BIDS inheritance (task-level + run-level)."""
    basename = os.path.basename(physio_path)
    parts = basename.split('_')
    task_part = [p for p in parts if p.startswith('task-')]

    merged = {}

    # Task-level sidecar
    if task_part:
        task_json = os.path.join(bids_dir, f'{task_part[0]}_physio.json')
        if os.path.exists(task_json):
            with open(task_json) as f:
                merged.update(json.load(f))

    # Run-level sidecar (same directory, same entities)
    run_json = physio_path.replace('.tsv.gz', '.json')
    if os.path.exists(run_json):
        with open(run_json) as f:
            merged.update(json.load(f))

    return merged


def resolve_screen_geometry(bids_dir, physio_path):
    """Resolve screen geometry from events.json with BIDS inheritance."""
    basename = os.path.basename(physio_path)
    parts = basename.split('_')
    task_part = [p for p in parts if p.startswith('task-')]

    merged = {}

    # Task-level events.json
    if task_part:
        task_events = os.path.join(bids_dir, f'{task_part[0]}_events.json')
        if os.path.exists(task_events):
            with open(task_events) as f:
                data = json.load(f)
                merged.update(data)

    # Run-level events.json: strip recording-* entity, change suffix
    non_rec = [p for p in parts if not p.startswith('recording-')]
    events_name = '_'.join(non_rec).replace('_physio.tsv.gz', '_events.json')
    events_path = os.path.join(os.path.dirname(physio_path), events_name)
    if os.path.exists(events_path):
        with open(events_path) as f:
            data = json.load(f)
            merged.update(data)

    return merged.get('StimulusPresentation', {})


def read_physio_data(physio_path, columns):
    """Read headerless gzip'd TSV with n/a handling."""
    data = {col: [] for col in columns}
    with gzip.open(physio_path, 'rt') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            values = line.split('\t')
            for i, col in enumerate(columns):
                if i < len(values):
                    val = values[i]
                    if val in ('n/a', 'nan', 'NaN', ''):
                        data[col].append(float('nan'))
                    else:
                        data[col].append(float(val))
                else:
                    data[col].append(float('nan'))
    return data


def pixel_displacement_to_dva(dx_px, dy_px, screen):
    """Convert pixel displacement to degrees of visual angle."""
    sw, sh = screen['ScreenSize']
    rw, rh = screen['ScreenResolution']
    dist = screen['ScreenDistance']
    dx_m = dx_px * (sw / rw)
    dy_m = dy_px * (sh / rh)
    disp_m = math.sqrt(dx_m ** 2 + dy_m ** 2)
    return math.degrees(2.0 * math.atan2(disp_m, 2.0 * dist))


def classify_events(data, metadata, screen):
    """Classify gaze samples into fixation/saccade/blink events."""
    timestamps = data['timestamp']
    x = data['x_coordinate']
    y = data['y_coordinate']
    pupil = data['pupil_size']
    n = len(timestamps)
    fs = metadata['SamplingFrequency']
    dt = 1.0 / fs

    # Step 1: label each sample
    labels = ['fixation'] * n

    # Detect blinks: pupil_size == 0
    for i in range(n):
        if pupil[i] == 0.0:
            labels[i] = 'blink'

    # Step 2: compute velocity for non-blink samples
    velocity = [0.0] * n
    for i in range(n - 1):
        if labels[i] == 'blink' or labels[i + 1] == 'blink':
            velocity[i] = 0.0
            continue
        if math.isnan(x[i]) or math.isnan(x[i + 1]) or \
           math.isnan(y[i]) or math.isnan(y[i + 1]):
            velocity[i] = 0.0
            continue
        dx = x[i + 1] - x[i]
        dy = y[i + 1] - y[i]
        dva_disp = pixel_displacement_to_dva(dx, dy, screen)
        velocity[i] = dva_disp / dt

    # Step 3: classify saccades based on velocity threshold
    for i in range(n):
        if labels[i] != 'blink' and velocity[i] > VELOCITY_THRESHOLD_DVA_S:
            labels[i] = 'saccade'

    # Backward velocity check for saccade boundary extension
    for i in range(1, n):
        if labels[i] == 'fixation' and labels[i - 1] == 'saccade':
            if i > 0 and not math.isnan(x[i]) and not math.isnan(x[i - 1]):
                dx = x[i] - x[i - 1]
                dy = y[i] - y[i - 1]
                dva_disp = pixel_displacement_to_dva(dx, dy, screen)
                back_vel = dva_disp / dt
                if back_vel > VELOCITY_THRESHOLD_DVA_S:
                    labels[i] = 'saccade'

    # Step 4: group contiguous same-label samples into events
    events = []
    current_type = labels[0]
    current_start = 0

    for i in range(1, n):
        if labels[i] != current_type:
            onset = timestamps[current_start]
            n_samp = i - current_start
            duration = n_samp * (1000.0 / fs)
            evt = {
                'onset': onset,
                'duration': duration,
                'trial_type': current_type,
                'blink': 1 if current_type == 'blink' else 0,
                'start_idx': current_start,
                'end_idx': i - 1,
            }
            events.append(evt)
            current_type = labels[i]
            current_start = i

    # Last event
    onset = timestamps[current_start]
    n_samp = n - current_start
    duration = n_samp * (1000.0 / fs)
    events.append({
        'onset': onset,
        'duration': duration,
        'trial_type': current_type,
        'blink': 1 if current_type == 'blink' else 0,
        'start_idx': current_start,
        'end_idx': n - 1,
    })

    # Step 5: compute saccade amplitudes
    for evt in events:
        if evt['trial_type'] == 'saccade':
            si, ei = evt['start_idx'], evt['end_idx']
            sx, sy = x[si], y[si]
            ex, ey = x[ei], y[ei]
            if not (math.isnan(sx) or math.isnan(sy) or
                    math.isnan(ex) or math.isnan(ey)):
                evt['amplitude_dva'] = pixel_displacement_to_dva(
                    ex - sx, ey - sy, screen)
            else:
                evt['amplitude_dva'] = None
        else:
            evt['amplitude_dva'] = None

    return events


def write_physioevents(output_path, events):
    """Write events as headerless gzip'd TSV."""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with gzip.open(output_path, 'wt') as f:
        for evt in events:
            onset_s = f"{evt['onset']:.1f}"
            dur_s = f"{evt['duration']:.1f}"
            tt = evt['trial_type']
            blink = str(evt['blink'])
            amp = (f"{evt['amplitude_dva']:.3f}"
                   if evt['amplitude_dva'] is not None else 'n/a')
            f.write(f"{onset_s}\t{dur_s}\t{tt}\t{blink}\t{amp}\n")


def compute_quality_metrics(events, metadata):
    """Compute quality report metrics for a recording."""
    fs = metadata['SamplingFrequency']
    fixations = [e for e in events if e['trial_type'] == 'fixation']
    saccades = [e for e in events if e['trial_type'] == 'saccade']
    blinks = [e for e in events if e['trial_type'] == 'blink']

    total_duration_ms = sum(e['duration'] for e in events)
    total_duration_sec = total_duration_ms / 1000.0

    total_samples = sum(
        round(e['duration'] / (1000.0 / fs)) for e in events)
    blink_samples = sum(
        round(e['duration'] / (1000.0 / fs)) for e in blinks)

    sac_amps = [s['amplitude_dva'] for s in saccades
                if s['amplitude_dva'] is not None]
    fix_durs = [f['duration'] for f in fixations]

    return {
        'n_fixations': len(fixations),
        'n_saccades': len(saccades),
        'n_blinks': len(blinks),
        'total_duration_sec': round(total_duration_sec, 3),
        'mean_saccade_amplitude_dva': (
            round(sum(sac_amps) / len(sac_amps), 3) if sac_amps else 0.0),
        'mean_fixation_duration_ms': (
            round(sum(fix_durs) / len(fix_durs), 3) if fix_durs else 0.0),
        'pct_blink': (
            round(blink_samples / total_samples * 100.0, 3)
            if total_samples > 0 else 0.0),
    }


def create_database(output_dir, recordings_info, all_events, quality_report):
    """Create SQLite database with normalized pipeline results."""
    db_path = os.path.join(output_dir, 'pipeline.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("""
        CREATE TABLE recordings (
            recording_id TEXT PRIMARY KEY,
            subject TEXT,
            task TEXT,
            run TEXT,
            recording TEXT,
            sampling_freq REAL,
            screen_distance REAL,
            screen_width_m REAL,
            screen_height_m REAL,
            screen_res_x INTEGER,
            screen_res_y INTEGER,
            recorded_eye TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id TEXT REFERENCES recordings(recording_id),
            onset REAL,
            duration REAL,
            trial_type TEXT,
            blink INTEGER,
            amplitude_dva REAL
        )
    """)

    conn.execute("""
        CREATE TABLE quality_metrics (
            recording_id TEXT PRIMARY KEY REFERENCES recordings(recording_id),
            n_fixations INTEGER,
            n_saccades INTEGER,
            n_blinks INTEGER,
            total_duration_sec REAL,
            mean_saccade_amplitude_dva REAL,
            mean_fixation_duration_ms REAL,
            pct_blink REAL
        )
    """)

    # Insert recordings
    for rec in recordings_info:
        rec_id = rec['rec_id']
        meta = rec['metadata']
        screen = rec['screen']
        entities = parse_bids_entities(rec_id)

        conn.execute(
            "INSERT INTO recordings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rec_id,
             entities.get('sub', ''),
             entities.get('task', ''),
             entities.get('run', ''),
             entities.get('recording', ''),
             meta['SamplingFrequency'],
             screen.get('ScreenDistance', 0.0),
             screen.get('ScreenSize', [0.0, 0.0])[0],
             screen.get('ScreenSize', [0.0, 0.0])[1],
             screen.get('ScreenResolution', [0, 0])[0],
             screen.get('ScreenResolution', [0, 0])[1],
             meta.get('RecordedEye', 'unknown')))

    # Insert events
    for rec_id, events in all_events.items():
        for evt in events:
            conn.execute(
                "INSERT INTO events "
                "(recording_id, onset, duration, trial_type, blink, amplitude_dva) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rec_id,
                 evt['onset'],
                 evt['duration'],
                 evt['trial_type'],
                 evt['blink'],
                 evt.get('amplitude_dva')))

    # Insert quality metrics
    for rec_id, metrics in quality_report.items():
        conn.execute(
            "INSERT INTO quality_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rec_id,
             metrics['n_fixations'],
             metrics['n_saccades'],
             metrics['n_blinks'],
             metrics['total_duration_sec'],
             metrics['mean_saccade_amplitude_dva'],
             metrics['mean_fixation_duration_ms'],
             metrics['pct_blink']))

    conn.commit()
    conn.close()


def main():
    if len(sys.argv) < 3:
        print("Usage: gaze_pipeline.py <input_bids_dir> <output_dir>",
              file=sys.stderr)
        sys.exit(1)

    bids_dir = sys.argv[1]
    output_dir = sys.argv[2]
    os.makedirs(output_dir, exist_ok=True)

    recordings = find_recordings(bids_dir)
    if not recordings:
        print("No eyetrack recordings found.", file=sys.stderr)
        sys.exit(1)

    quality_report = {}
    all_events = {}

    for rec in recordings:
        rec_id = rec['rec_id']
        meta = rec['metadata']
        screen = rec['screen']
        columns = meta['Columns']

        print(f"Processing {rec_id}...")
        data = read_physio_data(rec['path'], columns)
        events = classify_events(data, meta, screen)

        # Store events for database
        all_events[rec_id] = events

        # Write TSV output
        out_path = os.path.join(output_dir,
                                f'{rec_id}_physioevents.tsv.gz')
        write_physioevents(out_path, events)

        # Quality metrics
        quality_report[rec_id] = compute_quality_metrics(events, meta)

    # Write quality report JSON
    report_path = os.path.join(output_dir, 'quality_report.json')
    with open(report_path, 'w') as f:
        json.dump(quality_report, f, indent=2)

    # Write SQLite database
    create_database(output_dir, recordings, all_events, quality_report)

    print(f"Done. Processed {len(recordings)} recordings.")
    print(f"Output: {output_dir}")


if __name__ == '__main__':
    main()
