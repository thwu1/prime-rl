#!/usr/bin/env python3
"""Solution: Multi-core EKF binary log forensics.

Parses an ArduPilot binary DataFlash log using pymavlink's DFReader,
extracts multi-core EKF innovation data, identifies flight phases and
anomalies, and computes corrected noise parameters.
"""

import json
import math
import os
import numpy as np
from pymavlink import mavutil

# ── Channel mapping: log field → parameter channel name ──
INNOV_TO_CHAN = {
    'IVN': 'VelN', 'IVE': 'VelE', 'IVD': 'VelD',
    'IPN': 'PosN', 'IPE': 'PosE', 'IAlt': 'Alt',
    'IMX': 'MagX', 'IMY': 'MagY', 'IMZ': 'MagZ',
    'IYaw': 'Yaw',
}
VAR_TO_CHAN = {
    'SVN': 'VelN', 'SVE': 'VelE', 'SVD': 'VelD',
    'SPN': 'PosN', 'SPE': 'PosE', 'SAlt': 'Alt',
    'SMX': 'MagX', 'SMY': 'MagY', 'SMZ': 'MagZ',
    'SYaw': 'Yaw',
}
CHAN_TO_PARAM = {
    'VelN': 'EK3_VELNE_NOISE', 'VelE': 'EK3_VELNE_NOISE',
    'VelD': 'EK3_VELD_NOISE',
    'PosN': 'EK3_POSNE_NOISE', 'PosE': 'EK3_POSNE_NOISE',
    'Alt':  'EK3_ALT_NOISE',
    'MagX': 'EK3_MAG_NOISE', 'MagY': 'EK3_MAG_NOISE',
    'MagZ': 'EK3_MAG_NOISE',
    'Yaw':  'EK3_YAW_NOISE',
}
PARAM_RANGES = {
    'EK3_VELNE_NOISE': (0.05, 5.0),
    'EK3_VELD_NOISE': (0.05, 5.0),
    'EK3_POSNE_NOISE': (0.1, 10.0),
    'EK3_ALT_NOISE': (0.1, 10.0),
    'EK3_MAG_NOISE': (0.01, 0.5),
    'EK3_YAW_NOISE': (0.01, 1.0),
}
GPS_CHANS = {'VelN', 'VelE', 'VelD', 'PosN', 'PosE'}

NIS_THRESHOLD = 0.5
BIAS_BLOCK = 100
BIAS_Z_THRESH = 3.0

LOG_PATH = '/app/flight_log/flight.bin'


def parse_log():
    """Read all messages from the binary DataFlash log."""
    mlog = mavutil.mavlink_connection(LOG_PATH)

    params = {}
    gps_msgs = []
    xkf1 = {0: [], 1: []}
    xkf2 = {0: [], 1: []}
    xkf4 = {0: [], 1: []}
    xkf5 = {0: [], 1: []}
    ctun_msgs = []
    stat_msgs = []
    msg_msgs = []

    while True:
        m = mlog.recv_msg()
        if m is None:
            break
        mt = m.get_type()
        if mt == 'PARM':
            name = m.Name
            if isinstance(name, bytes):
                name = name.decode('ascii', errors='replace')
            name = name.rstrip('\x00')
            params[name] = m.Value
        elif mt == 'GPS':
            gps_msgs.append({'TimeUS': m.TimeUS, 'Status': m.Status})
        elif mt == 'XKF1':
            core = m.C
            xkf1[core].append({
                'TimeUS': m.TimeUS,
                'IVN': m.IVN, 'IVE': m.IVE, 'IVD': m.IVD,
                'IPN': m.IPN, 'IPE': m.IPE, 'IAlt': m.IAlt,
            })
        elif mt == 'XKF2':
            core = m.C
            xkf2[core].append({
                'TimeUS': m.TimeUS,
                'IMX': m.IMX, 'IMY': m.IMY, 'IMZ': m.IMZ,
                'IYaw': m.IYaw,
            })
        elif mt == 'XKF4':
            core = m.C
            xkf4[core].append({
                'TimeUS': m.TimeUS,
                'SVN': m.SVN, 'SVE': m.SVE, 'SVD': m.SVD,
                'SPN': m.SPN, 'SPE': m.SPE, 'SAlt': m.SAlt,
            })
        elif mt == 'XKF5':
            core = m.C
            xkf5[core].append({
                'TimeUS': m.TimeUS,
                'SMX': m.SMX, 'SMY': m.SMY, 'SMZ': m.SMZ,
                'SYaw': m.SYaw,
            })
        elif mt == 'CTUN':
            ctun_msgs.append({'TimeUS': m.TimeUS, 'Alt': m.Alt})
        elif mt == 'STAT':
            stat_msgs.append({'TimeUS': m.TimeUS,
                              'MainCoreId': m.MainCoreId})
        elif mt == 'MSG':
            text = m.Message
            if isinstance(text, bytes):
                text = text.decode('ascii', errors='replace')
            msg_msgs.append({'TimeUS': m.TimeUS,
                             'Message': text.rstrip('\x00')})

    return params, gps_msgs, xkf1, xkf2, xkf4, xkf5, ctun_msgs, stat_msgs, msg_msgs


def detect_cruise_phase(ctun_msgs, n_samples):
    """Identify cruise phase from altitude data."""
    if not ctun_msgs:
        return 0, n_samples

    alts = np.array([c['Alt'] for c in ctun_msgs])
    times = np.array([c['TimeUS'] for c in ctun_msgs])

    # Cruise: stable altitude > 48m (above takeoff/landing transitions)
    threshold = 48.0
    above = alts > threshold
    if not np.any(above):
        return 0, n_samples

    indices = np.where(above)[0]
    start_time = times[indices[0]]
    end_time = times[indices[-1]]
    return int(start_time), int(end_time)


def time_to_sample(time_us, ref_times):
    """Find closest sample index for a timestamp."""
    idx = np.searchsorted(ref_times, time_us)
    return min(idx, len(ref_times) - 1)


def detect_bias(values, block_size=BIAS_BLOCK):
    """Detect systematic bias via block-mean z-test."""
    valid = ~np.isnan(values)
    vdata = values[valid]
    if len(vdata) < 2 * block_size:
        return None

    mad = np.median(np.abs(vdata - np.median(vdata)))
    robust_std = mad * 1.4826
    if robust_std < 1e-12:
        return None

    biased = []
    n = len(values)
    for s in range(0, n, block_size):
        e = min(s + block_size, n)
        block = values[s:e]
        bv = block[~np.isnan(block)]
        if len(bv) < block_size // 2:
            continue
        z = abs(np.mean(bv)) / (robust_std / np.sqrt(len(bv)))
        if z > BIAS_Z_THRESH:
            biased.append((s, e))

    if not biased:
        return None
    return biased[0][0], biased[-1][1]


def main():
    print("Parsing binary DataFlash log...")
    params, gps_msgs, xkf1, xkf2, xkf4, xkf5, ctun_msgs, stat_msgs, msg_msgs = parse_log()
    print(f"Params: {len(params)}, GPS: {len(gps_msgs)}, "
          f"XKF1[0]: {len(xkf1[0])}, XKF1[1]: {len(xkf1[1])}, "
          f"CTUN: {len(ctun_msgs)}, STAT: {len(stat_msgs)}")

    n_samples = max(len(xkf1[0]), len(xkf1[1]))

    # ── Primary core schedule from STAT messages ──
    core_switches = []
    prev_core = None
    for sm in stat_msgs:
        c = sm['MainCoreId']
        if prev_core is not None and c != prev_core:
            # Find sample index closest to this timestamp
            ref = np.array([m['TimeUS'] for m in xkf1[c]])
            idx = time_to_sample(sm['TimeUS'], ref)
            core_switches.append({
                'sample_index': idx,
                'from_core': prev_core,
                'to_core': c,
            })
        prev_core = c

    # Build per-sample primary core array
    primary_core = np.zeros(n_samples, dtype=int)
    if stat_msgs:
        ref_times_0 = np.array([m['TimeUS'] for m in xkf1[0]])
        for sm in stat_msgs:
            idx = time_to_sample(sm['TimeUS'], ref_times_0)
            primary_core[idx:] = sm['MainCoreId']

    print(f"Core switches: {core_switches}")
    print(f"Primary core at start: {primary_core[0]}, at end: {primary_core[-1]}")

    # ── Cruise phase from CTUN altitude ──
    cruise_start_t, cruise_end_t = detect_cruise_phase(ctun_msgs, n_samples)
    ref_times_0 = np.array([m['TimeUS'] for m in xkf1[0]])
    cruise_start = time_to_sample(cruise_start_t, ref_times_0)
    cruise_end = time_to_sample(cruise_end_t, ref_times_0)
    print(f"Cruise phase: samples {cruise_start}-{cruise_end}")

    # ── Build per-channel innovation/variance arrays (primary core only) ──
    inno_fields_vp = ['IVN', 'IVE', 'IVD', 'IPN', 'IPE', 'IAlt']
    var_fields_vp = ['SVN', 'SVE', 'SVD', 'SPN', 'SPE', 'SAlt']
    inno_fields_my = ['IMX', 'IMY', 'IMZ', 'IYaw']
    var_fields_my = ['SMX', 'SMY', 'SMZ', 'SYaw']

    chan_inno = {INNOV_TO_CHAN[f]: np.full(n_samples, np.nan)
                 for f in inno_fields_vp + inno_fields_my}
    chan_var = {VAR_TO_CHAN[f]: np.full(n_samples, np.nan)
                for f in var_fields_vp + var_fields_my}

    for i in range(n_samples):
        pc = primary_core[i]
        # VP channels
        if i < len(xkf1[pc]) and i < len(xkf4[pc]):
            for fi, fld in enumerate(inno_fields_vp):
                chan = INNOV_TO_CHAN[fld]
                chan_inno[chan][i] = xkf1[pc][i][fld]
            for fi, fld in enumerate(var_fields_vp):
                chan = VAR_TO_CHAN[fld]
                chan_var[chan][i] = xkf4[pc][i][fld]
        # MY channels
        if i < len(xkf2[pc]) and i < len(xkf5[pc]):
            for fi, fld in enumerate(inno_fields_my):
                chan = INNOV_TO_CHAN[fld]
                chan_inno[chan][i] = xkf2[pc][i][fld]
            for fi, fld in enumerate(var_fields_my):
                chan = VAR_TO_CHAN[fld]
                chan_var[chan][i] = xkf5[pc][i][fld]

    # ── GPS outage detection ──
    gps_outage = {'detected': False}
    vel_n = chan_inno['VelN']
    nan_mask = np.isnan(vel_n)
    if np.any(nan_mask):
        nan_idx = np.where(nan_mask)[0]
        # Only consider cruise-phase NaN runs
        cruise_nan = nan_idx[(nan_idx >= cruise_start) & (nan_idx <= cruise_end)]
        if len(cruise_nan) > 0:
            gps_outage = {
                'detected': True,
                'start_index': int(cruise_nan[0]),
                'end_index': int(cruise_nan[-1] + 1),
            }
    print(f"GPS outage: {gps_outage}")

    # ── Anomaly detection (per-channel bias) ──
    anomalies = []
    anomaly_masks = {}

    for chan_name in chan_inno:
        cruise_data = chan_inno[chan_name][cruise_start:cruise_end]
        result = detect_bias(cruise_data)
        if result is not None:
            abs_start = cruise_start + result[0]
            abs_end = cruise_start + result[1]
            anomalies.append({
                'channel': chan_name,
                'type': 'bias_shift',
                'description': (
                    f"Bias detected in {chan_name} samples "
                    f"{abs_start}-{abs_end}"
                ),
            })
            mask = np.zeros(n_samples, dtype=bool)
            mask[abs_start:abs_end] = True
            anomaly_masks[chan_name] = mask
            print(f"Anomaly: {chan_name} bias at {abs_start}-{abs_end}")

    # ── NIS analysis and parameter calibration ──
    chan_stats = {}
    per_chan_R = {}

    for chan_name in chan_inno:
        inno = chan_inno[chan_name]
        var = chan_var[chan_name]
        param_name = CHAN_TO_PARAM[chan_name]
        cfg_noise = params.get(param_name, 0.5)
        R_current = cfg_noise ** 2

        # Valid mask: cruise only, not NaN, not anomalous
        valid = np.ones(n_samples, dtype=bool)
        valid[:cruise_start] = False
        valid[cruise_end:] = False
        valid &= ~np.isnan(inno)
        valid &= ~np.isnan(var)
        if chan_name in anomaly_masks:
            valid &= ~anomaly_masks[chan_name]

        vi = inno[valid]
        vv = var[valid]
        n_valid = len(vi)

        if n_valid == 0:
            print(f"  {chan_name}: no valid samples")
            continue

        mean_inno_sq = float(np.mean(vi ** 2))
        mean_var = float(np.mean(vv))
        mean_nis = mean_inno_sq / mean_var
        hph = mean_var - R_current
        R_opt = mean_inno_sq - hph
        if R_opt < 0:
            R_opt = R_current
        consistent = abs(mean_nis - 1.0) < NIS_THRESHOLD

        chan_stats[chan_name] = {
            'mean_nis': mean_nis,
            'R_optimal': R_opt,
            'n_valid': n_valid,
            'consistent': consistent,
        }
        per_chan_R[chan_name] = R_opt

        tag = "OK" if consistent else "INCONSISTENT"
        print(f"  {chan_name}: NIS={mean_nis:.3f} ({tag}), "
              f"R_opt={R_opt:.6f}, n={n_valid}")

    inconsistent_channels = [ch for ch, s in chan_stats.items()
                              if not s['consistent']]

    # ── Joint estimation for shared parameters ──
    param_to_chans = {}
    for ch, p in CHAN_TO_PARAM.items():
        param_to_chans.setdefault(p, []).append(ch)

    corrected_params = {}
    for param_name, channels in param_to_chans.items():
        Rs, ws = [], []
        for ch in channels:
            if ch in per_chan_R:
                Rs.append(per_chan_R[ch])
                ws.append(chan_stats[ch]['n_valid'])
        if not Rs:
            corrected_params[param_name] = params.get(param_name, 0.5)
            continue
        total_w = sum(ws)
        R_joint = sum(r * w for r, w in zip(Rs, ws)) / total_w
        noise = math.sqrt(max(R_joint, 0.0))
        lo, hi = PARAM_RANGES[param_name]
        noise = max(lo, min(hi, noise))
        corrected_params[param_name] = round(noise, 4)
        print(f"  {param_name}: {params.get(param_name, '?')} → {noise:.4f}")

    # ── Write output ──
    def to_native(obj):
        """Convert numpy types to native Python for JSON serialization."""
        if isinstance(obj, dict):
            return {k: to_native(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [to_native(v) for v in obj]
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    result = to_native({
        'corrected_params': corrected_params,
        'inconsistent_channels': inconsistent_channels,
        'primary_core_switches': core_switches,
        'cruise_phase': {
            'start_sample': cruise_start,
            'end_sample': cruise_end,
        },
        'gps_outage': gps_outage,
        'anomalies': anomalies,
    })

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/analysis_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    print("\nResults written to /app/output/analysis_results.json")


if __name__ == '__main__':
    main()
