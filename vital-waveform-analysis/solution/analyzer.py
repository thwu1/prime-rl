
"""Perioperative biosignal analyzer using VitalDB open-dataset cases.

Downloads .vital files from the VitalDB API, parses them with the custom
vital_parser module, derives heart rate from raw ECG waveforms, computes
HRV metrics, detects hemodynamic events, and produces a structured JSON report.
"""

import argparse
import json
import os
import sys

import numpy as np

# Ensure /app is on the path so vital_parser is importable
sys.path.insert(0, '/app')
import vital_parser


# ---------------------------------------------------------------------------
# Signal processing: ECG heart rate derivation
# ---------------------------------------------------------------------------

def derive_hr_from_ecg(ecg_500hz):
    """Derive beat-to-beat heart rate from a 500 Hz ECG waveform.

    Uses bandpass filtering to isolate the QRS complex, then peak detection
    with adaptive per-segment thresholding.

    Returns a dict with:
      'hr_1sec': float32 array of HR at 1-second resolution (bpm)
      'rr_intervals_sec': float64 array of valid R-R intervals (seconds)
    or None if insufficient valid data.
    """
    from scipy.signal import butter, filtfilt, find_peaks

    srate = 500.0
    n = len(ecg_500hz)
    duration = n / srate

    if duration < 30:
        return None

    ecg = ecg_500hz.copy().astype(np.float64)

    # Interpolate NaN gaps so filtering doesn't blow up
    nan_mask = np.isnan(ecg)
    if np.sum(~nan_mask) < srate * 10:
        return None
    if np.any(nan_mask):
        valid_idx = np.where(~nan_mask)[0]
        ecg[nan_mask] = np.interp(np.where(nan_mask)[0], valid_idx, ecg[valid_idx])

    # Bandpass filter 5-15 Hz (isolates QRS energy)
    nyq = srate / 2.0
    lo, hi = 5.0 / nyq, 15.0 / nyq
    b, a = butter(2, [lo, hi], btype='band')
    filtered = filtfilt(b, a, ecg)

    # Square to emphasise peaks
    squared = filtered ** 2

    # Moving-window integration (150 ms)
    win = int(0.15 * srate)
    kernel = np.ones(win, dtype=np.float64) / win
    integrated = np.convolve(squared, kernel, mode='same')

    # Peak detection in 60-second segments with adaptive thresholding
    seg_len = int(60 * srate)
    min_dist = int(0.3 * srate)  # max ~200 bpm
    all_peaks = []

    for start in range(0, n, seg_len):
        end = min(start + seg_len, n)
        seg = integrated[start:end]
        if len(seg) < min_dist * 3:
            continue

        # Adaptive height threshold: well above the baseline
        seg_sorted = np.sort(seg)
        threshold = seg_sorted[int(len(seg_sorted) * 0.7)] * 0.5
        if threshold <= 0:
            threshold = np.mean(seg) + np.std(seg)

        seg_peaks, _ = find_peaks(seg, height=threshold, distance=min_dist)
        for p in seg_peaks:
            all_peaks.append(p + start)

    if len(all_peaks) < 3:
        return None

    peaks = np.array(sorted(set(all_peaks)))

    # Instantaneous HR from R-R intervals
    rr = np.diff(peaks) / srate
    hr_inst = 60.0 / rr
    peak_times = peaks[:-1] / srate

    # Filter physiologically implausible values
    valid = (hr_inst > 25) & (hr_inst < 250)
    peak_times = peak_times[valid]
    hr_inst = hr_inst[valid]
    rr_valid = rr[valid]

    if len(hr_inst) < 3:
        return None

    # Resample to 1-second bins
    n_sec = int(duration)
    hr_1sec = np.full(n_sec, np.nan, dtype=np.float32)
    for i in range(len(peak_times)):
        idx = int(peak_times[i])
        if 0 <= idx < n_sec:
            if np.isnan(hr_1sec[idx]):
                hr_1sec[idx] = hr_inst[i]
            else:
                hr_1sec[idx] = (hr_1sec[idx] + hr_inst[i]) / 2.0

    return {
        'hr_1sec': hr_1sec,
        'rr_intervals_sec': rr_valid,
    }


# ---------------------------------------------------------------------------
# Heart rate variability
# ---------------------------------------------------------------------------

def compute_hrv(rr_intervals_sec):
    """Compute time-domain HRV metrics from R-R intervals.

    Returns (sdnn_ms, rmssd_ms) or (None, None) if insufficient data.
    SDNN = standard deviation of NN intervals.
    RMSSD = root mean square of successive NN interval differences.
    """
    if len(rr_intervals_sec) < 10:
        return None, None

    rr = rr_intervals_sec.copy()

    # Filter ectopic beats: keep intervals within 20% of local median
    median_rr = np.median(rr)
    nn = rr[np.abs(rr - median_rr) < 0.2 * median_rr]

    if len(nn) < 10:
        # Fallback: use wider tolerance
        nn = rr[(rr > 0.3) & (rr < 2.0)]

    if len(nn) < 10:
        return None, None

    sdnn = float(np.std(nn) * 1000.0)  # Convert seconds to ms
    successive_diff = np.diff(nn)
    rmssd = float(np.sqrt(np.mean(successive_diff ** 2)) * 1000.0)

    return sdnn, rmssd


# ---------------------------------------------------------------------------
# Hemodynamic event detection
# ---------------------------------------------------------------------------

def detect_hypotension(mbp_1sec, threshold=65.0, min_duration=60):
    """Detect episodes where MBP < threshold for >= min_duration seconds.

    Returns (num_episodes, total_seconds).
    """
    episodes = 0
    total_sec = 0
    run = 0

    for i in range(len(mbp_1sec)):
        if not np.isnan(mbp_1sec[i]) and mbp_1sec[i] < threshold:
            run += 1
        else:
            if run >= min_duration:
                episodes += 1
                total_sec += run
            run = 0

    # Final run
    if run >= min_duration:
        episodes += 1
        total_sec += run

    return episodes, total_sec


def detect_tachycardia(hr_1sec, threshold=100.0, min_duration=30):
    """Detect episodes where HR > threshold for >= min_duration seconds.

    Returns (num_episodes, total_seconds).
    """
    episodes = 0
    total_sec = 0
    run = 0

    for i in range(len(hr_1sec)):
        if not np.isnan(hr_1sec[i]) and hr_1sec[i] > threshold:
            run += 1
        else:
            if run >= min_duration:
                episodes += 1
                total_sec += run
            run = 0

    # Final run
    if run >= min_duration:
        episodes += 1
        total_sec += run

    return episodes, total_sec


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Perioperative biosignal analyzer (VitalDB)')
    parser.add_argument('--case-id', type=int, required=True,
                        help='VitalDB open-dataset case ID (1-6388)')
    parser.add_argument('--output', type=str, required=True,
                        help='Path for JSON output report')
    args = parser.parse_args()

    # Download the .vital file (with simple caching)
    url = f'https://api.vitaldb.net/1.0.1/{args.case_id}.vital'
    tmpfile = f'/tmp/case_{args.case_id}.vital'
    if not os.path.exists(tmpfile):
        print(f'Downloading case {args.case_id} from {url} ...')
        from urllib import request
        request.urlretrieve(url, tmpfile)
        print(f'  saved to {tmpfile}')

    # Parse metadata
    meta = vital_parser.parse(tmpfile)
    track_names = [t['name'] for t in meta['tracks']]
    print(f'Parsed {len(meta["tracks"])} tracks, '
          f'duration={meta["duration_sec"]:.0f}s')

    # Initialise report
    report = {
        'case_id': args.case_id,
        'duration_sec': meta['duration_sec'],
        'num_tracks': len(meta['tracks']),
        'tracks': [{'name': t['name'], 'type': t['type'],
                     'unit': t['unit'], 'srate': t['srate']}
                    for t in meta['tracks']],
        'derived_hr': None,
        'device_hr': None,
        'hr_correlation': None,
        'hr_mae_bpm': None,
        'hrv_sdnn_ms': None,
        'hrv_rmssd_ms': None,
        'hypotension_episodes': None,
        'hypotension_total_sec': None,
        'tachycardia_episodes': None,
        'tachycardia_total_sec': None,
    }

    # ------------------------------------------------------------------
    # ECG-derived heart rate and HRV
    # ------------------------------------------------------------------
    ecg_name = next((n for n in track_names
                     if 'ECG_II' in n and ('SNUADC' in n or 'SNUADCM' in n)),
                    None)
    hr_result = None
    hr_derived = None
    if ecg_name:
        print(f'Extracting ECG from {ecg_name} ...')
        ecg = vital_parser.get_track_samples(tmpfile, ecg_name, 1.0 / 500.0)
        print(f'  ECG samples: {len(ecg)}, '
              f'valid: {np.sum(~np.isnan(ecg))}')
        hr_result = derive_hr_from_ecg(ecg)
        if hr_result is not None:
            hr_derived = hr_result['hr_1sec']
            valid = ~np.isnan(hr_derived)
            if np.sum(valid) > 0:
                report['derived_hr'] = {
                    'mean': float(np.nanmean(hr_derived)),
                    'std': float(np.nanstd(hr_derived)),
                    'median': float(np.nanmedian(hr_derived)),
                }
                print(f'  Derived HR: mean={report["derived_hr"]["mean"]:.1f}, '
                      f'median={report["derived_hr"]["median"]:.1f}')

            # HRV from R-R intervals
            rr = hr_result['rr_intervals_sec']
            sdnn, rmssd = compute_hrv(rr)
            report['hrv_sdnn_ms'] = sdnn
            report['hrv_rmssd_ms'] = rmssd
            if sdnn is not None:
                print(f'  HRV: SDNN={sdnn:.1f}ms, RMSSD={rmssd:.1f}ms')

    # ------------------------------------------------------------------
    # Device-reported heart rate
    # ------------------------------------------------------------------
    hr_name = next((n for n in track_names
                    if n == 'Solar8000/HR' or
                    (n.endswith('/HR') and 'Solar' in n)), None)
    hr_device = None
    if hr_name:
        print(f'Extracting device HR from {hr_name} ...')
        hr_device = vital_parser.get_track_samples(tmpfile, hr_name, 1.0)
        valid = ~np.isnan(hr_device)
        if np.sum(valid) > 0:
            report['device_hr'] = {
                'mean': float(np.nanmean(hr_device)),
                'std': float(np.nanstd(hr_device)),
                'median': float(np.nanmedian(hr_device)),
            }
            print(f'  Device HR: mean={report["device_hr"]["mean"]:.1f}')

    # ------------------------------------------------------------------
    # HR correlation
    # ------------------------------------------------------------------
    if hr_derived is not None and hr_device is not None:
        min_len = min(len(hr_derived), len(hr_device))
        d = hr_derived[:min_len]
        dv = hr_device[:min_len]
        both_valid = ~np.isnan(d) & ~np.isnan(dv)
        n_valid = int(np.sum(both_valid))
        print(f'  Overlapping valid HR samples: {n_valid}')

        if n_valid > 30:
            from scipy.stats import pearsonr
            r, _ = pearsonr(d[both_valid], dv[both_valid])
            mae = float(np.mean(np.abs(d[both_valid] - dv[both_valid])))
            report['hr_correlation'] = float(r)
            report['hr_mae_bpm'] = mae
            print(f'  Correlation: r={r:.3f}, MAE={mae:.1f} bpm')

    # ------------------------------------------------------------------
    # Tachycardia detection (from derived HR)
    # ------------------------------------------------------------------
    if hr_derived is not None:
        tachy_episodes, tachy_sec = detect_tachycardia(hr_derived)
        report['tachycardia_episodes'] = tachy_episodes
        report['tachycardia_total_sec'] = float(tachy_sec)
        print(f'  Tachycardia: {tachy_episodes} episodes, {tachy_sec}s total')

    # ------------------------------------------------------------------
    # Hypotension detection
    # ------------------------------------------------------------------
    mbp_name = next((n for n in track_names if 'ART_MBP' in n), None)
    if mbp_name:
        print(f'Extracting MBP from {mbp_name} ...')
        mbp = vital_parser.get_track_samples(tmpfile, mbp_name, 1.0)
        episodes, total_sec = detect_hypotension(mbp)
        report['hypotension_episodes'] = episodes
        report['hypotension_total_sec'] = float(total_sec)
        print(f'  Hypotension: {episodes} episodes, {total_sec}s total')

    # ------------------------------------------------------------------
    # Write report
    # ------------------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w') as fout:
        json.dump(report, fout, indent=2)
    print(f'Report written to {args.output}')


if __name__ == '__main__':
    main()
