#!/usr/bin/env python3
"""
Crash simulation post-processing pipeline.

Implements:
  - Energy balance analysis for explicit dynamics FEM output
  - SAE J211/1 Channel Frequency Class (CFC) filtering
  - Head Injury Criterion (HIC15 / HIC36) computation
"""

import json
import os

import numpy as np
from scipy.signal import butter, filtfilt

G = 9.81  # m/s^2


# ─────────────────────── File parsing ────────────────────────────

def parse_th_file(filepath):
    """Parse an OpenRadioss-style time-history CSV.

    Skips comment lines (starting with #) and blank lines.
    Returns an (N, M) numpy array of floats.
    """
    rows = []
    with open(filepath) as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            rows.append([float(tok) for tok in stripped.split()])
    return np.array(rows)


# ─────────────────────── Energy balance ──────────────────────────

def energy_balance_analysis(data):
    """Compute energy balance error and diagnose the dominant error source.

    Columns: time, KE, IE, contact, hourglass, damping.

    Returns (max_error_pct, first_violation_time, error_source).
    """
    time = data[:, 0]
    total = np.sum(data[:, 1:], axis=1)
    e0 = total[0]

    error_pct = (total - e0) / e0 * 100.0
    max_error_pct = float(np.max(np.abs(error_pct)))

    # First timestep where |error| > 2%
    violation = np.abs(error_pct) > 2.0
    if np.any(violation):
        first_violation_time = float(time[int(np.argmax(violation))])
    else:
        first_violation_time = None

    # Diagnose error source by comparing component growth in the second half.
    mid = len(time) // 2
    hg = data[:, 4]
    contact = data[:, 3]

    hg_growth = float(hg[-1] - hg[mid])
    contact_change = float(abs(contact[-1] - contact[mid]))
    total_change = float(abs(total[-1] - total[0]))

    if total_change < 1e-6:
        source = "numerical"
    elif hg_growth > contact_change * 2 and hg_growth > total_change * 0.3:
        source = "hourglass"
    elif contact_change > hg_growth * 2:
        source = "contact"
    else:
        source = "numerical"

    return max_error_pct, first_violation_time, source


# ─────────────────────── SAE J211/1 CFC filter ───────────────────

def sae_j211_filter(signal, fs, cfc_class):
    """Apply SAE J211/1 Channel Frequency Class filter.

    CFC to -3 dB frequency:  f_3dB = CFC * 5 / 3

    Implementation: 2nd-order Butterworth low-pass, applied forward and
    backward (zero-phase via filtfilt, effective 4th-order).
    """
    f_3db = cfc_class * 5.0 / 3.0
    nyquist = fs / 2.0
    wn = f_3db / nyquist
    if wn >= 1.0:
        return signal.copy()
    b, a = butter(2, wn, btype='low')
    return filtfilt(b, a, signal)


# ─────────────────────── HIC computation ─────────────────────────

def compute_hic(resultant_g, time, max_duration_s):
    """Compute the Head Injury Criterion.

    HIC_d = max over (t1, t2) with t2-t1 <= d of:
        (t2 - t1) * [ 1/(t2-t1) * integral_{t1}^{t2} a(tau) dtau ]^{2.5}

    Uses a prefix-sum approach for O(W*N) efficiency where W = max
    window samples.
    """
    dt = float(time[1] - time[0])
    n = len(time)

    # Trapezoidal prefix sum
    trapz_increments = 0.5 * (resultant_g[1:] + resultant_g[:-1]) * dt
    prefix = np.concatenate([[0.0], np.cumsum(trapz_increments)])

    max_w = min(int(round(max_duration_s / dt)), n - 1)
    best = 0.0

    for w in range(1, max_w + 1):
        dt_w = w * dt
        avg_a = (prefix[w:] - prefix[:-w]) / dt_w
        hic_vals = dt_w * np.abs(avg_a) ** 2.5
        candidate = float(np.max(hic_vals))
        if candidate > best:
            best = candidate

    return best


# ─────────────────────── Main pipeline ────────────────────────────

def main():
    # Load metadata
    with open('/sim_output/metadata.json') as fh:
        meta = json.load(fh)
    fs = meta['accel_sampling_rate_Hz']

    # Parse data files
    energy_data = parse_th_file('/sim_output/energy_th.csv')
    accel_data = parse_th_file('/sim_output/accel_node42_th.csv')

    # ── Energy balance ──
    max_err, fvt, err_src = energy_balance_analysis(energy_data)

    # ── Acceleration processing ──
    t = accel_data[:, 0]
    ax_g = accel_data[:, 1] / G
    ay_g = accel_data[:, 2] / G
    az_g = accel_data[:, 3] / G

    # SAE J211 CFC filtering at four standard classes
    cfc_classes = [60, 180, 600, 1000]
    peak_accelerations = {}
    res180 = None

    for cfc in cfc_classes:
        axf = sae_j211_filter(ax_g, fs, cfc)
        ayf = sae_j211_filter(ay_g, fs, cfc)
        azf = sae_j211_filter(az_g, fs, cfc)
        resultant = np.sqrt(axf ** 2 + ayf ** 2 + azf ** 2)
        peak_accelerations[f'CFC{cfc}'] = round(float(np.max(resultant)), 2)
        if cfc == 180:
            res180 = resultant

    # ── HIC computation from CFC180-filtered resultant ──
    hic15 = compute_hic(res180, t, 0.015)
    hic36 = compute_hic(res180, t, 0.036)

    # ── Assessment ──
    passes = (hic15 < 700) and (hic36 < 1000) and (max_err < 5.0)

    report = {
        'energy_balance': {
            'max_error_pct': round(max_err, 2),
            'first_violation_time': round(fvt, 4) if fvt is not None else None,
            'error_source': err_src,
        },
        'peak_accelerations': peak_accelerations,
        'hic': {
            'hic15': round(hic15, 1),
            'hic36': round(hic36, 1),
        },
        'assessment': 'PASS' if passes else 'FAIL',
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/report.json', 'w') as fh:
        json.dump(report, fh, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
