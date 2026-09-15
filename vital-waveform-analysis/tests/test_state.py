
"""Tests for VitalDB .vital binary format parser and biosignal analyzer."""

import json
import struct
import gzip
import os
import sys
import subprocess
import tempfile

import numpy as np
import pytest

sys.path.insert(0, '/app')

# ---------------------------------------------------------------------------
# Helpers: synthetic .vital file creation
# ---------------------------------------------------------------------------

def _pack_str(s):
    b = s.encode('utf-8')
    return struct.pack('<L', len(b)) + b


def create_synthetic_vital(filepath):
    """Create a valid .vital file with known data for deterministic testing.

    Contents:
      - 1 device: "TestDev" (type "TestDevice")
      - Track "TestDev/HR": numeric, float fmt, 5 records at 2-sec intervals
      - Track "TestDev/WAVE": waveform, float fmt, srate=10 Hz, 100 samples (sine)
      - Track "TestDev/SCALED": waveform, uint16 fmt, srate=10 Hz, gain=0.1, offset=0.0,
        50 samples of raw [100,200,300,400,500] repeated
    """
    dtstart = 1700000000.0
    dtend = dtstart + 10.0

    hr_values = [70.0, 72.0, 75.0, 73.0, 71.0]
    hr_times = [dtstart + i * 2.0 for i in range(5)]

    wav_srate = 10.0
    wav_data = np.sin(2 * np.pi * 1.0 * np.arange(100) / wav_srate).astype(np.float32)

    scaled_raw = np.array([100, 200, 300, 400, 500] * 10, dtype=np.uint16)
    scaled_gain = 0.1
    scaled_offset = 0.0

    with gzip.open(filepath, 'wb') as f:
        # ---- HEADER ----
        f.write(b'VITA')
        f.write(struct.pack('<L', 3))       # version
        f.write(struct.pack('<H', 27))      # header length
        header = struct.pack('<h', 0)       # dgmt
        header += struct.pack('<L', 0)      # instance id
        header += struct.pack('<L', 0)      # program version
        header += struct.pack('<d', dtstart)
        header += struct.pack('<d', dtend)
        header += struct.pack('<B', 0)      # packed = False
        f.write(header)

        # ---- DEVICE INFO (packet type 9) ----
        did = 1
        dev_data = struct.pack('<L', did)
        dev_data += _pack_str('TestDevice')
        dev_data += _pack_str('TestDev')
        dev_data += _pack_str('')
        f.write(struct.pack('<B', 9))
        f.write(struct.pack('<L', len(dev_data)))
        f.write(dev_data)

        # ---- TRACK INFO: HR (numeric, float fmt=1) ----
        tid_hr = 1
        hr_reclen = len(hr_values) * (1 + 4 + 2 + 8 + 2 + 4)
        ti = struct.pack('<H', tid_hr)
        ti += struct.pack('<B', 2)          # type = NUM
        ti += struct.pack('<B', 1)          # fmt = float
        ti += _pack_str('HR')
        ti += _pack_str('/min')
        ti += struct.pack('<f', 30.0)       # mindisp
        ti += struct.pack('<f', 150.0)      # maxdisp
        ti += struct.pack('<L', 0)          # color
        ti += struct.pack('<f', 0.0)        # srate
        ti += struct.pack('<d', 1.0)        # gain
        ti += struct.pack('<d', 0.0)        # offset
        ti += struct.pack('<B', 0)          # montype
        ti += struct.pack('<L', did)        # did
        ti += struct.pack('<L', hr_reclen)
        ti += struct.pack('<d', hr_times[0])
        ti += struct.pack('<d', hr_times[-1])
        f.write(struct.pack('<B', 0))
        f.write(struct.pack('<L', len(ti)))
        f.write(ti)

        # ---- TRACK INFO: WAVE (waveform, float fmt=1, srate=10) ----
        tid_wav = 2
        wav_reclen = 1 * (1 + 4 + 2 + 8 + 2 + 4 + len(wav_data) * 4)
        ti = struct.pack('<H', tid_wav)
        ti += struct.pack('<B', 1)          # type = WAV
        ti += struct.pack('<B', 1)          # fmt = float
        ti += _pack_str('WAVE')
        ti += _pack_str('mV')
        ti += struct.pack('<f', -1.0)
        ti += struct.pack('<f', 1.0)
        ti += struct.pack('<L', 0)
        ti += struct.pack('<f', wav_srate)
        ti += struct.pack('<d', 1.0)        # gain (unused for float)
        ti += struct.pack('<d', 0.0)        # offset (unused for float)
        ti += struct.pack('<B', 0)
        ti += struct.pack('<L', did)
        ti += struct.pack('<L', wav_reclen)
        ti += struct.pack('<d', dtstart)
        ti += struct.pack('<d', dtstart + len(wav_data) / wav_srate)
        f.write(struct.pack('<B', 0))
        f.write(struct.pack('<L', len(ti)))
        f.write(ti)

        # ---- TRACK INFO: SCALED (waveform, uint16 fmt=6, srate=10, gain/offset) ----
        tid_scaled = 3
        scaled_reclen = 1 * (1 + 4 + 2 + 8 + 2 + 4 + len(scaled_raw) * 2)
        ti = struct.pack('<H', tid_scaled)
        ti += struct.pack('<B', 1)          # type = WAV
        ti += struct.pack('<B', 6)          # fmt = unsigned short
        ti += _pack_str('SCALED')
        ti += _pack_str('au')
        ti += struct.pack('<f', 0.0)
        ti += struct.pack('<f', 100.0)
        ti += struct.pack('<L', 0)
        ti += struct.pack('<f', wav_srate)
        ti += struct.pack('<d', scaled_gain)
        ti += struct.pack('<d', scaled_offset)
        ti += struct.pack('<B', 0)
        ti += struct.pack('<L', did)
        ti += struct.pack('<L', scaled_reclen)
        ti += struct.pack('<d', dtstart)
        ti += struct.pack('<d', dtstart + len(scaled_raw) / wav_srate)
        f.write(struct.pack('<B', 0))
        f.write(struct.pack('<L', len(ti)))
        f.write(ti)

        # ---- DATA RECORDS: HR (numeric float) ----
        for t, v in zip(hr_times, hr_values):
            rd = struct.pack('<H', 10)          # infolen
            rd += struct.pack('<d', t)          # dt
            rd += struct.pack('<H', tid_hr)     # tid
            rd += struct.pack('<f', v)          # value
            f.write(struct.pack('<B', 1))
            f.write(struct.pack('<L', len(rd)))
            f.write(rd)

        # ---- DATA RECORD: WAVE (float waveform) ----
        rd = struct.pack('<H', 10)
        rd += struct.pack('<d', dtstart)
        rd += struct.pack('<H', tid_wav)
        rd += struct.pack('<L', len(wav_data))
        rd += wav_data.tobytes()
        f.write(struct.pack('<B', 1))
        f.write(struct.pack('<L', len(rd)))
        f.write(rd)

        # ---- DATA RECORD: SCALED (uint16 waveform) ----
        rd = struct.pack('<H', 10)
        rd += struct.pack('<d', dtstart)
        rd += struct.pack('<H', tid_scaled)
        rd += struct.pack('<L', len(scaled_raw))
        rd += scaled_raw.tobytes()
        f.write(struct.pack('<B', 1))
        f.write(struct.pack('<L', len(rd)))
        f.write(rd)

    return {
        'dtstart': dtstart,
        'dtend': dtend,
        'hr_times': hr_times,
        'hr_values': hr_values,
        'wav_data': wav_data,
        'wav_srate': wav_srate,
        'scaled_raw': scaled_raw,
        'scaled_gain': scaled_gain,
        'scaled_offset': scaled_offset,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SYNTH_PATH = '/tmp/test_synthetic.vital'
SYNTH_DATA = None


@pytest.fixture(scope='session')
def synth():
    global SYNTH_DATA
    if SYNTH_DATA is None:
        SYNTH_DATA = create_synthetic_vital(SYNTH_PATH)
    return SYNTH_DATA


@pytest.fixture(scope='session')
def case1_path():
    """Download VitalDB case 1 .vital file (cached)."""
    path = '/tmp/case_1.vital'
    if not os.path.exists(path):
        from urllib import request
        request.urlretrieve('https://api.vitaldb.net/1.0.1/1.vital', path)
    return path


# ---------------------------------------------------------------------------
# Tests: synthetic .vital file (deterministic, no internet)
# ---------------------------------------------------------------------------

class TestParserSynthetic:

    def test_parse_metadata(self, synth):
        """Parser returns correct tracks, devices, and timing from synthetic file."""
        import vital_parser
        result = vital_parser.parse(SYNTH_PATH)

        # Device
        assert len(result['devices']) >= 1
        dev_names = [d['name'] for d in result['devices']]
        assert 'TestDev' in dev_names

        # Tracks
        assert len(result['tracks']) == 3
        trk_names = [t['name'] for t in result['tracks']]
        assert 'TestDev/HR' in trk_names
        assert 'TestDev/WAVE' in trk_names
        assert 'TestDev/SCALED' in trk_names

        # Track metadata
        hr = next(t for t in result['tracks'] if t['name'] == 'TestDev/HR')
        assert hr['type'] == 'num'
        assert hr['unit'] == '/min'
        assert hr['num_records'] == 5

        wav = next(t for t in result['tracks'] if t['name'] == 'TestDev/WAVE')
        assert wav['type'] == 'wav'
        assert wav['unit'] == 'mV'
        assert wav['srate'] == pytest.approx(10.0)

        sc = next(t for t in result['tracks'] if t['name'] == 'TestDev/SCALED')
        assert sc['type'] == 'wav'
        assert sc['fmt'] == 6
        assert sc['gain'] == pytest.approx(0.1)

        # Duration
        assert result['duration_sec'] == pytest.approx(10.0, abs=1.0)
        assert result['dtstart'] == pytest.approx(synth['dtstart'], abs=0.1)

    def test_numeric_track_samples(self, synth):
        """get_track_samples returns correct values for numeric tracks."""
        import vital_parser
        samples = vital_parser.get_track_samples(SYNTH_PATH, 'TestDev/HR', 1.0)

        # Should have ~10 elements
        assert len(samples) >= 9

        # Values at known positions (records at t=0, 2, 4, 6, 8 relative to dtstart)
        assert samples[0] == pytest.approx(70.0, abs=0.5)
        assert samples[2] == pytest.approx(72.0, abs=0.5)
        assert samples[4] == pytest.approx(75.0, abs=0.5)
        assert samples[6] == pytest.approx(73.0, abs=0.5)
        assert samples[8] == pytest.approx(71.0, abs=0.5)

        # Odd-indexed slots should be NaN (no data between records)
        assert np.isnan(samples[1])
        assert np.isnan(samples[3])

    def test_waveform_track_samples(self, synth):
        """get_track_samples returns correct waveform values (float format)."""
        import vital_parser
        # At native rate (10 Hz => interval = 0.1)
        samples = vital_parser.get_track_samples(SYNTH_PATH, 'TestDev/WAVE', 0.1)

        assert len(samples) >= 95

        # First 10 samples should match the sine wave
        expected = np.sin(2 * np.pi * 1.0 * np.arange(10) / 10.0).astype(np.float32)
        np.testing.assert_allclose(samples[:10], expected, atol=0.02)

    def test_gain_offset_waveform(self, synth):
        """get_track_samples applies gain/offset for integer-format waveform tracks."""
        import vital_parser
        samples = vital_parser.get_track_samples(SYNTH_PATH, 'TestDev/SCALED', 0.1)

        # First 50 elements should be scaled raw values: raw * gain + offset
        expected_raw = np.array([100, 200, 300, 400, 500] * 10, dtype=np.float32)
        expected = expected_raw * synth['scaled_gain'] + synth['scaled_offset']

        np.testing.assert_allclose(samples[:50], expected, atol=0.5)

        # Elements beyond 50 should be NaN (only 50 samples = 5 sec at 10 Hz)
        assert np.all(np.isnan(samples[50:100]))

    def test_missing_track_returns_nan(self, synth):
        """get_track_samples returns NaN-filled array for nonexistent track."""
        import vital_parser
        samples = vital_parser.get_track_samples(SYNTH_PATH, 'NonExistent/Track', 1.0)
        assert len(samples) > 0
        assert np.all(np.isnan(samples))


# ---------------------------------------------------------------------------
# Tests: real VitalDB case (requires internet)
# ---------------------------------------------------------------------------

class TestParserRealCase:

    def test_parse_case1_metadata(self, case1_path):
        """Parser correctly reads metadata from a real VitalDB case."""
        import vital_parser
        result = vital_parser.parse(case1_path)

        # Case 1 should have many tracks and multiple devices
        assert len(result['tracks']) >= 20
        assert len(result['devices']) >= 3

        trk_names = [t['name'] for t in result['tracks']]

        # Expected tracks for case 1
        assert any('ECG_II' in n for n in trk_names), \
            f"ECG_II track not found in {trk_names[:10]}..."
        assert any('Solar8000/HR' == n or n.endswith('/HR') for n in trk_names), \
            f"HR track not found"
        assert any('ART_MBP' in n for n in trk_names), \
            f"ART_MBP track not found"

        # Duration should be ~11543 seconds (~3.2 hours)
        assert result['duration_sec'] > 10000, \
            f"Duration {result['duration_sec']} too short"
        assert result['duration_sec'] < 20000, \
            f"Duration {result['duration_sec']} too long"

        # Device names
        dev_names = [d['name'] for d in result['devices']]
        assert any('Solar' in n for n in dev_names)

    def test_get_hr_samples_case1(self, case1_path):
        """get_track_samples returns reasonable HR values for case 1."""
        import vital_parser
        hr = vital_parser.get_track_samples(case1_path, 'Solar8000/HR', 1.0)

        valid = hr[~np.isnan(hr)]
        assert len(valid) > 1000, "Too few valid HR samples"

        # HR should be physiological (30-200 bpm)
        assert np.min(valid) >= 20
        assert np.max(valid) <= 250

        # Mean HR for case 1 is ~77 bpm
        assert 50 < np.mean(valid) < 120


class TestAnalyzer:

    def test_analyzer_report_case1(self, case1_path):
        """Analyzer produces a valid report with HR correlation > 0.6 on case 1."""
        report_path = '/tmp/test_analyzer_report.json'

        # Run the analyzer
        result = subprocess.run(
            ['python3', '/app/analyzer.py', '--case-id', '1', '--output', report_path],
            capture_output=True, text=True, timeout=240,
            cwd='/app',
        )
        assert result.returncode == 0, \
            f"Analyzer failed: stdout={result.stdout[-500:]}, stderr={result.stderr[-500:]}"

        # Load report
        with open(report_path) as f:
            report = json.load(f)

        # Basic fields
        assert report['case_id'] == 1
        assert report['duration_sec'] > 10000
        assert report['num_tracks'] >= 20
        assert len(report['tracks']) >= 20

        # Track entries have correct fields
        for trk in report['tracks']:
            assert 'name' in trk
            assert 'type' in trk
            assert trk['type'] in ('wav', 'num', 'str')

        # Device HR stats (case 1 has Solar8000/HR)
        assert report['device_hr'] is not None
        assert 50 < report['device_hr']['mean'] < 120

        # Derived HR stats
        assert report['derived_hr'] is not None, \
            "derived_hr should not be null for case 1 (has SNUADC/ECG_II)"
        assert 30 < report['derived_hr']['mean'] < 200

        # HR correlation and MAE
        assert report['hr_correlation'] is not None
        assert report['hr_correlation'] > 0.6, \
            f"HR correlation {report['hr_correlation']} below 0.6 threshold"
        assert report['hr_mae_bpm'] is not None
        assert report['hr_mae_bpm'] < 10, \
            f"HR MAE {report['hr_mae_bpm']} above 10 bpm threshold"

        # HRV metrics (case 1 has ECG so these should be present)
        assert report['hrv_sdnn_ms'] is not None, \
            "hrv_sdnn_ms should not be null for case 1"
        assert 5 < report['hrv_sdnn_ms'] < 500, \
            f"hrv_sdnn_ms {report['hrv_sdnn_ms']} outside physiological range"
        assert report['hrv_rmssd_ms'] is not None, \
            "hrv_rmssd_ms should not be null for case 1"
        assert 2 < report['hrv_rmssd_ms'] < 300, \
            f"hrv_rmssd_ms {report['hrv_rmssd_ms']} outside physiological range"

        # Hypotension detection (case 1 has ART_MBP)
        assert report['hypotension_episodes'] is not None
        assert isinstance(report['hypotension_episodes'], int)
        assert report['hypotension_episodes'] >= 0
        assert report['hypotension_total_sec'] is not None
        assert isinstance(report['hypotension_total_sec'], (int, float))
        assert report['hypotension_total_sec'] >= 0

        # Tachycardia detection (from derived HR)
        assert report['tachycardia_episodes'] is not None
        assert isinstance(report['tachycardia_episodes'], int)
        assert report['tachycardia_episodes'] >= 0
        assert report['tachycardia_total_sec'] is not None
        assert isinstance(report['tachycardia_total_sec'], (int, float))
        assert report['tachycardia_total_sec'] >= 0

    def test_analyzer_all_fields_present(self, case1_path):
        """All required JSON fields are present in the report."""
        report_path = '/tmp/test_analyzer_report.json'
        if not os.path.exists(report_path):
            subprocess.run(
                ['python3', '/app/analyzer.py', '--case-id', '1', '--output', report_path],
                capture_output=True, text=True, timeout=240, cwd='/app',
            )

        with open(report_path) as f:
            report = json.load(f)

        required_fields = [
            'case_id', 'duration_sec', 'num_tracks', 'tracks',
            'derived_hr', 'device_hr', 'hr_correlation', 'hr_mae_bpm',
            'hrv_sdnn_ms', 'hrv_rmssd_ms',
            'hypotension_episodes', 'hypotension_total_sec',
            'tachycardia_episodes', 'tachycardia_total_sec',
        ]
        for field in required_fields:
            assert field in report, f"Missing required field: {field}"

        # derived_hr sub-fields
        assert 'mean' in report['derived_hr']
        assert 'std' in report['derived_hr']
        assert 'median' in report['derived_hr']

        # device_hr sub-fields
        assert 'mean' in report['device_hr']
        assert 'std' in report['device_hr']
        assert 'median' in report['device_hr']

        # tracks sub-fields
        for trk in report['tracks']:
            for f_name in ('name', 'type', 'unit', 'srate'):
                assert f_name in trk, f"Track missing field: {f_name}"
