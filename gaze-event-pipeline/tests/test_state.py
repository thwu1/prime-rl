#!/usr/bin/env python3
"""Tests for BIDS eye-tracking gaze event pipeline."""

import os
import json
import gzip
import math
import sqlite3
import pytest

OUTPUT_DIR = '/app/output'

RECORDINGS = [
    'sub-01_task-gaze_run-01_recording-eye1',
    'sub-01_task-gaze_run-02_recording-eye1',
    'sub-02_task-gaze_run-01_recording-eye1',
    'sub-03_task-gaze_run-02_recording-eye1',
]

# Ground truth screen configs for amplitude verification
SCREEN_A = {
    "ScreenDistance": 0.6,
    "ScreenSize": [0.531, 0.299],
    "ScreenResolution": [1920, 1080],
}
SCREEN_B = {
    "ScreenDistance": 0.7,
    "ScreenSize": [0.597, 0.336],
    "ScreenResolution": [2560, 1440],
}

# Expected recording metadata (resolved from BIDS inheritance)
RECORDING_META = {
    'sub-01_task-gaze_run-01_recording-eye1': {
        'subject': '01', 'task': 'gaze', 'run': '01', 'recording': 'eye1',
        'sampling_freq': 1000.0, 'screen_distance': 0.6,
        'screen_width_m': 0.531, 'screen_height_m': 0.299,
        'screen_res_x': 1920, 'screen_res_y': 1080,
        'recorded_eye': 'left',
    },
    'sub-01_task-gaze_run-02_recording-eye1': {
        'subject': '01', 'task': 'gaze', 'run': '02', 'recording': 'eye1',
        'sampling_freq': 1000.0, 'screen_distance': 0.6,
        'screen_width_m': 0.531, 'screen_height_m': 0.299,
        'screen_res_x': 1920, 'screen_res_y': 1080,
        'recorded_eye': 'left',
    },
    'sub-02_task-gaze_run-01_recording-eye1': {
        'subject': '02', 'task': 'gaze', 'run': '01', 'recording': 'eye1',
        'sampling_freq': 500.0, 'screen_distance': 0.7,
        'screen_width_m': 0.597, 'screen_height_m': 0.336,
        'screen_res_x': 2560, 'screen_res_y': 1440,
        'recorded_eye': 'right',
    },
    'sub-03_task-gaze_run-02_recording-eye1': {
        'subject': '03', 'task': 'gaze', 'run': '02', 'recording': 'eye1',
        'sampling_freq': 1000.0, 'screen_distance': 0.6,
        'screen_width_m': 0.531, 'screen_height_m': 0.299,
        'screen_res_x': 1920, 'screen_res_y': 1080,
        'recorded_eye': 'right',
    },
}


def _dva(x1, y1, x2, y2, scr):
    sw, sh = scr["ScreenSize"]
    rw, rh = scr["ScreenResolution"]
    d = scr["ScreenDistance"]
    dx = (x2 - x1) * (sw / rw)
    dy = (y2 - y1) * (sh / rh)
    disp = math.sqrt(dx ** 2 + dy ** 2)
    return math.degrees(2.0 * math.atan2(disp, 2.0 * d))


# Pre-computed expected values from the synthetic data generator
EXPECTED = {
    'sub-01_task-gaze_run-01_recording-eye1': {
        'n_saccades': 3,
        'n_blinks': 1,
        'n_fixations': 5,
        'total_samples': 5000,
        'fs': 1000,
        'total_duration_sec': 5.0,
        # Saccade onsets (ms timestamps): sample_idx * 1 + 5000000
        'saccade_onsets': [5001000.0, 5002690.0, 5003750.0],
        # Amplitudes computed from known start/end positions with SCREEN_A
        'saccade_amplitudes': [
            _dva(960, 540, 460, 290, SCREEN_A),   # ~14.7
            _dva(460, 290, 1400, 750, SCREEN_A),   # ~27.1
            _dva(1400, 750, 960, 540, SCREEN_A),   # ~12.8
        ],
        'blink_total_ms': 150.0,
    },
    'sub-01_task-gaze_run-02_recording-eye1': {
        'n_saccades': 3,
        'n_blinks': 1,
        'n_fixations': 5,
        'total_samples': 4000,
        'fs': 1000,
        'total_duration_sec': 4.0,
        'saccade_onsets': [6000800.0, 6001860.0, 6002900.0],
        'saccade_amplitudes': [
            _dva(300, 200, 1600, 900, SCREEN_A),   # ~37.6
            _dva(1600, 900, 800, 400, SCREEN_A),    # ~24.6
            _dva(800, 400, 300, 200, SCREEN_A),     # ~14.2
        ],
        'blink_total_ms': 100.0,
    },
    'sub-02_task-gaze_run-01_recording-eye1': {
        'n_saccades': 3,
        'n_blinks': 2,
        'n_fixations': 6,
        'total_samples': 3000,
        'fs': 500,
        'total_duration_sec': 6.0,
        # At 500 Hz, dt=2ms: onset = sample_idx * 2 + 8000000
        'saccade_onsets': [8001000.0, 8003250.0, 8005310.0],
        'saccade_amplitudes': [
            _dva(1280, 720, 600, 300, SCREEN_B),    # ~15.2
            _dva(600, 300, 2000, 1100, SCREEN_B),   # ~30.1
            _dva(2000, 1100, 1280, 720, SCREEN_B),  # ~15.4
        ],
        'blink_total_ms': 350.0,
    },
    'sub-03_task-gaze_run-02_recording-eye1': {
        'n_saccades': 2,
        'n_blinks': 1,
        'n_fixations': 4,  # dropout merges with surrounding fixations
        'total_samples': 3000,
        'fs': 1000,
        'total_duration_sec': 3.0,
        # Saccade 1 at sample 800, saccade 2 at sample 1870
        'saccade_onsets': [9000800.0, 9001870.0],
        'saccade_amplitudes': [
            _dva(960, 540, 400, 200, SCREEN_A),
            _dva(400, 200, 1500, 800, SCREEN_A),
        ],
        'blink_total_ms': 100.0,
    },
}

# Tolerances
ONSET_TOLERANCE_MS = 15.0
AMPLITUDE_TOLERANCE_DVA = 1.5
DURATION_TOLERANCE_SEC = 0.2


def read_output_events(rec_id):
    """Read output physioevents.tsv.gz file and return list of event dicts."""
    path = os.path.join(OUTPUT_DIR, f'{rec_id}_physioevents.tsv.gz')
    events = []
    with gzip.open(path, 'rt') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t')
            assert len(parts) >= 5, (
                f"Expected 5 columns, got {len(parts)}: {line!r}")
            events.append({
                'onset': float(parts[0]),
                'duration': float(parts[1]),
                'trial_type': parts[2],
                'blink': int(parts[3]),
                'amplitude_dva': (
                    float(parts[4]) if parts[4] not in ('n/a', 'None', 'nan')
                    else None),
            })
    return events


def get_db():
    """Open the SQLite database with foreign keys enabled."""
    path = os.path.join(OUTPUT_DIR, 'pipeline.db')
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ======================================================================
# Test: output files exist
# ======================================================================
class TestOutputFilesExist:
    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_physioevents_exists(self, rec_id):
        path = os.path.join(OUTPUT_DIR, f'{rec_id}_physioevents.tsv.gz')
        assert os.path.exists(path), f"Missing output file: {path}"

    def test_quality_report_exists(self):
        path = os.path.join(OUTPUT_DIR, 'quality_report.json')
        assert os.path.exists(path), "Missing quality_report.json"

    def test_database_exists(self):
        path = os.path.join(OUTPUT_DIR, 'pipeline.db')
        assert os.path.exists(path), "Missing pipeline.db"


# ======================================================================
# Test: output file format
# ======================================================================
class TestOutputFormat:
    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_valid_gzip(self, rec_id):
        """File must be valid gzip."""
        path = os.path.join(OUTPUT_DIR, f'{rec_id}_physioevents.tsv.gz')
        with gzip.open(path, 'rt') as f:
            content = f.read()
        assert len(content) > 0, "Output file is empty"

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_columns_and_types(self, rec_id):
        """Each line must have 5 tab-separated fields with correct types."""
        events = read_output_events(rec_id)
        assert len(events) > 0, "No events in output"
        for e in events:
            assert isinstance(e['onset'], float)
            assert isinstance(e['duration'], float)
            assert e['trial_type'] in ('fixation', 'saccade', 'blink'), (
                f"Invalid trial_type: {e['trial_type']}")
            assert e['blink'] in (0, 1)
            if e['trial_type'] == 'saccade':
                assert e['amplitude_dva'] is not None, (
                    "Saccade missing amplitude_dva")
            else:
                assert e['amplitude_dva'] is None, (
                    f"Non-saccade should have n/a amplitude, got "
                    f"{e['amplitude_dva']}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_events_sorted(self, rec_id):
        """Events must be sorted by onset."""
        events = read_output_events(rec_id)
        onsets = [e['onset'] for e in events]
        assert onsets == sorted(onsets), "Events not sorted by onset"

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_positive_durations(self, rec_id):
        """All durations must be positive."""
        events = read_output_events(rec_id)
        for e in events:
            assert e['duration'] > 0, (
                f"Non-positive duration: {e['duration']} at onset {e['onset']}")


# ======================================================================
# Test: event counts
# ======================================================================
class TestEventCounts:
    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_saccade_count(self, rec_id):
        events = read_output_events(rec_id)
        saccades = [e for e in events if e['trial_type'] == 'saccade']
        expected = EXPECTED[rec_id]['n_saccades']
        assert len(saccades) == expected, (
            f"Expected {expected} saccades, got {len(saccades)}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_blink_count(self, rec_id):
        events = read_output_events(rec_id)
        blinks = [e for e in events if e['trial_type'] == 'blink']
        expected = EXPECTED[rec_id]['n_blinks']
        assert len(blinks) == expected, (
            f"Expected {expected} blinks, got {len(blinks)}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_fixation_count(self, rec_id):
        events = read_output_events(rec_id)
        fixations = [e for e in events if e['trial_type'] == 'fixation']
        expected = EXPECTED[rec_id]['n_fixations']
        assert len(fixations) == expected, (
            f"Expected {expected} fixations, got {len(fixations)}")


# ======================================================================
# Test: saccade detection accuracy
# ======================================================================
class TestSaccadeDetection:
    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_saccade_onsets(self, rec_id):
        """Saccade onsets must be within tolerance of ground truth."""
        events = read_output_events(rec_id)
        saccades = sorted(
            [e for e in events if e['trial_type'] == 'saccade'],
            key=lambda e: e['onset'])
        expected_onsets = EXPECTED[rec_id]['saccade_onsets']

        assert len(saccades) == len(expected_onsets)
        for i, (sac, exp_onset) in enumerate(zip(saccades, expected_onsets)):
            diff = abs(sac['onset'] - exp_onset)
            assert diff <= ONSET_TOLERANCE_MS, (
                f"Saccade {i} onset {sac['onset']} differs from expected "
                f"{exp_onset} by {diff}ms (tolerance {ONSET_TOLERANCE_MS}ms)")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_saccade_amplitudes(self, rec_id):
        """Saccade amplitudes must be within tolerance of ground truth."""
        events = read_output_events(rec_id)
        saccades = sorted(
            [e for e in events if e['trial_type'] == 'saccade'],
            key=lambda e: e['onset'])
        expected_amps = EXPECTED[rec_id]['saccade_amplitudes']

        assert len(saccades) == len(expected_amps)
        for i, (sac, exp_amp) in enumerate(zip(saccades, expected_amps)):
            assert sac['amplitude_dva'] is not None
            diff = abs(sac['amplitude_dva'] - exp_amp)
            assert diff <= AMPLITUDE_TOLERANCE_DVA, (
                f"Saccade {i} amplitude {sac['amplitude_dva']:.3f} differs "
                f"from expected {exp_amp:.3f} by {diff:.3f} DVA "
                f"(tolerance {AMPLITUDE_TOLERANCE_DVA})")


# ======================================================================
# Test: blink detection
# ======================================================================
class TestBlinkDetection:
    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_blink_flag_consistency(self, rec_id):
        """Blink events must have blink=1, others blink=0."""
        events = read_output_events(rec_id)
        for e in events:
            if e['trial_type'] == 'blink':
                assert e['blink'] == 1, (
                    f"Blink event at onset {e['onset']} has blink=0")
            else:
                assert e['blink'] == 0, (
                    f"{e['trial_type']} event at onset {e['onset']} "
                    f"has blink=1")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_blink_total_duration(self, rec_id):
        """Total blink duration must be close to ground truth."""
        events = read_output_events(rec_id)
        blinks = [e for e in events if e['trial_type'] == 'blink']
        total_blink = sum(e['duration'] for e in blinks)
        expected = EXPECTED[rec_id]['blink_total_ms']
        # Allow +/-20ms tolerance (boundary detection differences)
        assert abs(total_blink - expected) <= 20.0, (
            f"Total blink duration {total_blink}ms differs from expected "
            f"{expected}ms by {abs(total_blink - expected)}ms")


# ======================================================================
# Test: event coverage
# ======================================================================
class TestEventCoverage:
    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_total_duration(self, rec_id):
        """Sum of event durations must approximate recording duration."""
        events = read_output_events(rec_id)
        total_ms = sum(e['duration'] for e in events)
        expected_sec = EXPECTED[rec_id]['total_duration_sec']
        expected_ms = expected_sec * 1000.0
        # Allow some tolerance for duration computation differences
        assert abs(total_ms - expected_ms) <= 50.0, (
            f"Total event duration {total_ms}ms differs from expected "
            f"{expected_ms}ms by {abs(total_ms - expected_ms)}ms")


# ======================================================================
# Test: quality report
# ======================================================================
class TestQualityReport:
    def _load_report(self):
        path = os.path.join(OUTPUT_DIR, 'quality_report.json')
        with open(path) as f:
            return json.load(f)

    def test_all_recordings_present(self):
        report = self._load_report()
        for rec_id in RECORDINGS:
            assert rec_id in report, (
                f"Recording {rec_id} missing from quality report")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_required_keys(self, rec_id):
        report = self._load_report()
        rec = report[rec_id]
        required = [
            'n_fixations', 'n_saccades', 'n_blinks',
            'total_duration_sec', 'mean_saccade_amplitude_dva',
            'mean_fixation_duration_ms', 'pct_blink',
        ]
        for key in required:
            assert key in rec, (
                f"Missing key '{key}' in report for {rec_id}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_report_event_counts(self, rec_id):
        report = self._load_report()
        rec = report[rec_id]
        exp = EXPECTED[rec_id]
        assert rec['n_saccades'] == exp['n_saccades']
        assert rec['n_blinks'] == exp['n_blinks']
        assert rec['n_fixations'] == exp['n_fixations']

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_report_total_duration(self, rec_id):
        report = self._load_report()
        rec = report[rec_id]
        exp = EXPECTED[rec_id]
        assert abs(rec['total_duration_sec'] - exp['total_duration_sec']) <= \
            DURATION_TOLERANCE_SEC, (
            f"total_duration_sec: {rec['total_duration_sec']} vs "
            f"expected {exp['total_duration_sec']}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_report_pct_blink_reasonable(self, rec_id):
        """pct_blink should be between 0 and 100 and approximately correct."""
        report = self._load_report()
        rec = report[rec_id]
        exp = EXPECTED[rec_id]
        exp_pct = exp['blink_total_ms'] / (exp['total_duration_sec'] * 1000) \
            * 100.0
        assert 0 <= rec['pct_blink'] <= 100
        assert abs(rec['pct_blink'] - exp_pct) <= 2.0, (
            f"pct_blink: {rec['pct_blink']:.2f} vs expected {exp_pct:.2f}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_report_mean_saccade_amplitude(self, rec_id):
        """Mean saccade amplitude should be close to expected."""
        report = self._load_report()
        rec = report[rec_id]
        exp_amps = EXPECTED[rec_id]['saccade_amplitudes']
        exp_mean = sum(exp_amps) / len(exp_amps)
        assert abs(rec['mean_saccade_amplitude_dva'] - exp_mean) <= 2.0, (
            f"mean_saccade_amplitude_dva: "
            f"{rec['mean_saccade_amplitude_dva']:.3f} vs "
            f"expected {exp_mean:.3f}")


# ======================================================================
# Test: multi-frequency and multi-geometry
# ======================================================================
class TestMultiFrequency:
    def test_500hz_recording_detected(self):
        """The 500 Hz recording (sub-02) must be correctly processed."""
        rec_id = 'sub-02_task-gaze_run-01_recording-eye1'
        events = read_output_events(rec_id)
        saccades = [e for e in events if e['trial_type'] == 'saccade']
        assert len(saccades) == 3, (
            f"Expected 3 saccades in 500Hz recording, got {len(saccades)}")

    def test_different_screen_geometry(self):
        """sub-02 must use SCREEN_B geometry (run-level override)."""
        rec_id = 'sub-02_task-gaze_run-01_recording-eye1'
        events = read_output_events(rec_id)
        saccades = sorted(
            [e for e in events if e['trial_type'] == 'saccade'],
            key=lambda e: e['onset'])
        # The first saccade amplitude with SCREEN_B should be ~15.2 deg
        # With SCREEN_A it would be ~14.4 deg (different geometry)
        exp_amp = EXPECTED[rec_id]['saccade_amplitudes'][0]
        diff = abs(saccades[0]['amplitude_dva'] - exp_amp)
        assert diff <= AMPLITUDE_TOLERANCE_DVA, (
            f"First saccade amplitude {saccades[0]['amplitude_dva']:.3f} "
            f"suggests wrong screen geometry (expected ~{exp_amp:.1f} with "
            f"SCREEN_B)")


# ======================================================================
# Test: edge cases (cardiac decoy, signal dropout, column reorder)
# ======================================================================
class TestEdgeCases:
    def test_cardiac_not_in_output(self):
        """Cardiac recording (non-eyetrack) must not produce output files."""
        cardiac_path = os.path.join(
            OUTPUT_DIR,
            'sub-03_task-gaze_run-01_recording-cardiac1_physioevents.tsv.gz')
        assert not os.path.exists(cardiac_path), (
            "Pipeline should not produce output for non-eyetrack recordings")

    def test_cardiac_not_in_quality_report(self):
        """Cardiac recording must not appear in quality report."""
        with open(os.path.join(OUTPUT_DIR, 'quality_report.json')) as f:
            report = json.load(f)
        cardiac_id = 'sub-03_task-gaze_run-01_recording-cardiac1'
        assert cardiac_id not in report, (
            f"Non-eyetrack recording {cardiac_id} should not be in "
            f"quality report")

    def test_signal_dropout_classified_as_fixation(self):
        """Signal dropout (NaN coords, non-zero pupil) must not create blinks."""
        rec_id = 'sub-03_task-gaze_run-02_recording-eye1'
        events = read_output_events(rec_id)
        blinks = [e for e in events if e['trial_type'] == 'blink']
        # Only 1 real blink, dropout should not create extra blinks
        assert len(blinks) == 1, (
            f"Expected 1 blink (dropout is not a blink), got {len(blinks)}")

    def test_dropout_merged_with_fixation(self):
        """Dropout region should merge with surrounding fixations."""
        rec_id = 'sub-03_task-gaze_run-02_recording-eye1'
        events = read_output_events(rec_id)
        fixations = [e for e in events if e['trial_type'] == 'fixation']
        # Without merging: 5 fixation segments
        # With dropout merging: 4 fixation events
        assert len(fixations) == 4, (
            f"Expected 4 fixations (dropout merged), got {len(fixations)}")

    def test_column_reorder_handled(self):
        """Recording with swapped column order must be correctly classified."""
        rec_id = 'sub-03_task-gaze_run-02_recording-eye1'
        events = read_output_events(rec_id)
        saccades = sorted(
            [e for e in events if e['trial_type'] == 'saccade'],
            key=lambda e: e['onset'])
        assert len(saccades) == 2, (
            f"Expected 2 saccades in reordered-column recording, "
            f"got {len(saccades)}")
        # Check amplitude is computed with correct geometry (SCREEN_A)
        exp_amp = _dva(960, 540, 400, 200, SCREEN_A)
        diff = abs(saccades[0]['amplitude_dva'] - exp_amp)
        assert diff <= AMPLITUDE_TOLERANCE_DVA, (
            f"Saccade amplitude {saccades[0]['amplitude_dva']:.3f} differs "
            f"from expected {exp_amp:.3f} — column reorder may not be handled")


# ======================================================================
# Test: SQLite database schema
# ======================================================================
class TestSQLiteSchema:
    def test_valid_sqlite(self):
        """pipeline.db must be a valid SQLite database."""
        conn = get_db()
        cur = conn.execute("SELECT sqlite_version()")
        assert cur.fetchone() is not None
        conn.close()

    def test_recordings_table_exists(self):
        conn = get_db()
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='recordings'")
        assert cur.fetchone() is not None, "Missing 'recordings' table"
        conn.close()

    def test_events_table_exists(self):
        conn = get_db()
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='events'")
        assert cur.fetchone() is not None, "Missing 'events' table"
        conn.close()

    def test_quality_metrics_table_exists(self):
        conn = get_db()
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='quality_metrics'")
        assert cur.fetchone() is not None, "Missing 'quality_metrics' table"
        conn.close()

    def test_recordings_columns(self):
        """Recordings table must have all required columns."""
        conn = get_db()
        cur = conn.execute("PRAGMA table_info(recordings)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {
            'recording_id', 'subject', 'task', 'run', 'recording',
            'sampling_freq', 'screen_distance', 'screen_width_m',
            'screen_height_m', 'screen_res_x', 'screen_res_y',
            'recorded_eye',
        }
        missing = required - cols
        assert not missing, f"Recordings table missing columns: {missing}"

    def test_events_columns(self):
        """Events table must have all required columns."""
        conn = get_db()
        cur = conn.execute("PRAGMA table_info(events)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {
            'event_id', 'recording_id', 'onset', 'duration',
            'trial_type', 'blink', 'amplitude_dva',
        }
        missing = required - cols
        assert not missing, f"Events table missing columns: {missing}"

    def test_quality_metrics_columns(self):
        """Quality_metrics table must have all required columns."""
        conn = get_db()
        cur = conn.execute("PRAGMA table_info(quality_metrics)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {
            'recording_id', 'n_fixations', 'n_saccades', 'n_blinks',
            'total_duration_sec', 'mean_saccade_amplitude_dva',
            'mean_fixation_duration_ms', 'pct_blink',
        }
        missing = required - cols
        assert not missing, f"Quality_metrics table missing columns: {missing}"

    def test_events_has_foreign_key(self):
        """Events table must have a foreign key to recordings."""
        conn = get_db()
        cur = conn.execute("PRAGMA foreign_key_list(events)")
        fks = cur.fetchall()
        conn.close()
        fk_tables = [fk[2] for fk in fks]
        assert 'recordings' in fk_tables, (
            "Events table must have a FOREIGN KEY to recordings")

    def test_quality_metrics_has_foreign_key(self):
        """Quality_metrics table must have a foreign key to recordings."""
        conn = get_db()
        cur = conn.execute("PRAGMA foreign_key_list(quality_metrics)")
        fks = cur.fetchall()
        conn.close()
        fk_tables = [fk[2] for fk in fks]
        assert 'recordings' in fk_tables, (
            "Quality_metrics table must have a FOREIGN KEY to recordings")

    def test_events_autoincrement(self):
        """Events table must use AUTOINCREMENT for event_id."""
        conn = get_db()
        cur = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='events'")
        sql = cur.fetchone()[0].upper()
        conn.close()
        assert 'AUTOINCREMENT' in sql, (
            "Events table must use AUTOINCREMENT for event_id")


# ======================================================================
# Test: SQLite database contents
# ======================================================================
class TestSQLiteData:
    def test_recording_count(self):
        """Database must contain exactly 4 recordings (no cardiac)."""
        conn = get_db()
        cur = conn.execute("SELECT COUNT(*) FROM recordings")
        count = cur.fetchone()[0]
        conn.close()
        assert count == len(RECORDINGS), (
            f"Expected {len(RECORDINGS)} recordings, got {count}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_recording_present(self, rec_id):
        conn = get_db()
        cur = conn.execute(
            "SELECT recording_id FROM recordings WHERE recording_id=?",
            (rec_id,))
        row = cur.fetchone()
        conn.close()
        assert row is not None, f"Recording {rec_id} not in database"

    def test_cardiac_not_in_recordings(self):
        """Cardiac recording must not be in recordings table."""
        conn = get_db()
        cur = conn.execute(
            "SELECT recording_id FROM recordings "
            "WHERE recording_id LIKE '%cardiac%'")
        row = cur.fetchone()
        conn.close()
        assert row is None, "Cardiac recording should not be in database"

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_recording_metadata_values(self, rec_id):
        """Recording metadata must match resolved BIDS inheritance."""
        conn = get_db()
        cur = conn.execute(
            "SELECT subject, task, run, recording, sampling_freq, "
            "screen_distance, screen_width_m, screen_height_m, "
            "screen_res_x, screen_res_y, recorded_eye "
            "FROM recordings WHERE recording_id=?",
            (rec_id,))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        exp = RECORDING_META[rec_id]
        assert row[0] == exp['subject'], (
            f"subject: got {row[0]}, expected {exp['subject']}")
        assert row[1] == exp['task'], (
            f"task: got {row[1]}, expected {exp['task']}")
        assert row[2] == exp['run'], (
            f"run: got {row[2]}, expected {exp['run']}")
        assert row[3] == exp['recording'], (
            f"recording: got {row[3]}, expected {exp['recording']}")
        assert abs(row[4] - exp['sampling_freq']) < 0.1, (
            f"sampling_freq: got {row[4]}, expected {exp['sampling_freq']}")
        assert abs(row[5] - exp['screen_distance']) < 0.01, (
            f"screen_distance: got {row[5]}, expected {exp['screen_distance']}")
        assert abs(row[6] - exp['screen_width_m']) < 0.01, (
            f"screen_width_m: got {row[6]}, expected {exp['screen_width_m']}")
        assert abs(row[7] - exp['screen_height_m']) < 0.01, (
            f"screen_height_m: got {row[7]}, expected {exp['screen_height_m']}")
        assert row[8] == exp['screen_res_x'], (
            f"screen_res_x: got {row[8]}, expected {exp['screen_res_x']}")
        assert row[9] == exp['screen_res_y'], (
            f"screen_res_y: got {row[9]}, expected {exp['screen_res_y']}")
        assert row[10] == exp['recorded_eye'], (
            f"recorded_eye: got {row[10]}, expected {exp['recorded_eye']}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_events_match_tsv(self, rec_id):
        """Events in SQLite must match the TSV output row-for-row."""
        conn = get_db()
        cur = conn.execute(
            "SELECT onset, duration, trial_type, blink, amplitude_dva "
            "FROM events WHERE recording_id=? ORDER BY onset",
            (rec_id,))
        db_events = cur.fetchall()
        conn.close()

        tsv_events = read_output_events(rec_id)
        assert len(db_events) == len(tsv_events), (
            f"Event count mismatch for {rec_id}: "
            f"DB={len(db_events)}, TSV={len(tsv_events)}")

        for i, (db_row, tsv_evt) in enumerate(zip(db_events, tsv_events)):
            assert abs(db_row[0] - tsv_evt['onset']) < 0.1, (
                f"Event {i} onset mismatch: DB={db_row[0]}, "
                f"TSV={tsv_evt['onset']}")
            assert abs(db_row[1] - tsv_evt['duration']) < 0.1, (
                f"Event {i} duration mismatch: DB={db_row[1]}, "
                f"TSV={tsv_evt['duration']}")
            assert db_row[2] == tsv_evt['trial_type'], (
                f"Event {i} trial_type mismatch: DB={db_row[2]}, "
                f"TSV={tsv_evt['trial_type']}")
            assert db_row[3] == tsv_evt['blink'], (
                f"Event {i} blink mismatch: DB={db_row[3]}, "
                f"TSV={tsv_evt['blink']}")
            # amplitude_dva: DB NULL == TSV None
            if tsv_evt['amplitude_dva'] is None:
                assert db_row[4] is None, (
                    f"Event {i}: TSV has n/a but DB has {db_row[4]}")
            else:
                assert db_row[4] is not None, (
                    f"Event {i}: TSV has {tsv_evt['amplitude_dva']} "
                    f"but DB has NULL")
                assert abs(db_row[4] - tsv_evt['amplitude_dva']) < 0.01, (
                    f"Event {i} amplitude mismatch: DB={db_row[4]}, "
                    f"TSV={tsv_evt['amplitude_dva']}")

    @pytest.mark.parametrize('rec_id', RECORDINGS)
    def test_quality_metrics_match_json(self, rec_id):
        """Quality metrics in SQLite must match the JSON report."""
        conn = get_db()
        cur = conn.execute(
            "SELECT n_fixations, n_saccades, n_blinks, total_duration_sec, "
            "mean_saccade_amplitude_dva, mean_fixation_duration_ms, pct_blink "
            "FROM quality_metrics WHERE recording_id=?",
            (rec_id,))
        row = cur.fetchone()
        conn.close()
        assert row is not None, (
            f"No quality_metrics row for {rec_id}")

        with open(os.path.join(OUTPUT_DIR, 'quality_report.json')) as f:
            report = json.load(f)
        rec = report[rec_id]

        assert row[0] == rec['n_fixations'], (
            f"n_fixations: DB={row[0]}, JSON={rec['n_fixations']}")
        assert row[1] == rec['n_saccades'], (
            f"n_saccades: DB={row[1]}, JSON={rec['n_saccades']}")
        assert row[2] == rec['n_blinks'], (
            f"n_blinks: DB={row[2]}, JSON={rec['n_blinks']}")
        assert abs(row[3] - rec['total_duration_sec']) < 0.01, (
            f"total_duration_sec: DB={row[3]}, "
            f"JSON={rec['total_duration_sec']}")
        assert abs(row[4] - rec['mean_saccade_amplitude_dva']) < 0.1, (
            f"mean_saccade_amplitude_dva: DB={row[4]}, "
            f"JSON={rec['mean_saccade_amplitude_dva']}")
        assert abs(row[5] - rec['mean_fixation_duration_ms']) < 1.0, (
            f"mean_fixation_duration_ms: DB={row[5]}, "
            f"JSON={rec['mean_fixation_duration_ms']}")
        assert abs(row[6] - rec['pct_blink']) < 0.1, (
            f"pct_blink: DB={row[6]}, JSON={rec['pct_blink']}")

    def test_no_orphan_events(self):
        """All events must reference a valid recording."""
        conn = get_db()
        cur = conn.execute(
            "SELECT COUNT(*) FROM events e "
            "LEFT JOIN recordings r ON e.recording_id = r.recording_id "
            "WHERE r.recording_id IS NULL")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, f"{count} orphan event(s) with invalid recording_id"

    def test_no_orphan_quality_metrics(self):
        """All quality_metrics must reference a valid recording."""
        conn = get_db()
        cur = conn.execute(
            "SELECT COUNT(*) FROM quality_metrics q "
            "LEFT JOIN recordings r ON q.recording_id = r.recording_id "
            "WHERE r.recording_id IS NULL")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, (
            f"{count} orphan quality_metrics row(s) with invalid recording_id")

    def test_saccade_amplitude_not_null_in_db(self):
        """Saccade events in DB must have non-NULL amplitude_dva."""
        conn = get_db()
        cur = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE trial_type='saccade' AND amplitude_dva IS NULL")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, f"{count} saccade(s) with NULL amplitude_dva"

    def test_non_saccade_amplitude_null_in_db(self):
        """Non-saccade events in DB must have NULL amplitude_dva."""
        conn = get_db()
        cur = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE trial_type != 'saccade' AND amplitude_dva IS NOT NULL")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, (
            f"{count} non-saccade event(s) with non-NULL amplitude_dva")

    def test_event_count_per_recording_via_sql(self):
        """SQL aggregate query must return correct event counts."""
        conn = get_db()
        cur = conn.execute(
            "SELECT recording_id, "
            "SUM(CASE WHEN trial_type='saccade' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN trial_type='blink' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN trial_type='fixation' THEN 1 ELSE 0 END) "
            "FROM events GROUP BY recording_id")
        results = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}
        conn.close()

        for rec_id in RECORDINGS:
            assert rec_id in results, (
                f"No events for {rec_id} in SQL aggregate")
            n_sac, n_blink, n_fix = results[rec_id]
            exp = EXPECTED[rec_id]
            assert n_sac == exp['n_saccades'], (
                f"{rec_id}: SQL saccade count {n_sac} != {exp['n_saccades']}")
            assert n_blink == exp['n_blinks'], (
                f"{rec_id}: SQL blink count {n_blink} != {exp['n_blinks']}")
            assert n_fix == exp['n_fixations'], (
                f"{rec_id}: SQL fixation count {n_fix} != {exp['n_fixations']}")

    def test_screen_geometry_inheritance_in_db(self):
        """sub-02 must have SCREEN_B geometry in DB (run-level override)."""
        conn = get_db()
        cur = conn.execute(
            "SELECT screen_distance, screen_width_m, screen_res_x "
            "FROM recordings "
            "WHERE recording_id='sub-02_task-gaze_run-01_recording-eye1'")
        row = cur.fetchone()
        conn.close()
        assert row is not None
        # SCREEN_B values
        assert abs(row[0] - 0.7) < 0.01, (
            f"screen_distance should be 0.7 (SCREEN_B), got {row[0]}")
        assert abs(row[1] - 0.597) < 0.01, (
            f"screen_width_m should be 0.597 (SCREEN_B), got {row[1]}")
        assert row[2] == 2560, (
            f"screen_res_x should be 2560 (SCREEN_B), got {row[2]}")
