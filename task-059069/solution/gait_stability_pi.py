#!/usr/bin/env python3
"""
Eurobench-compliant gait stability PI computation pipeline.

Reads HDF5 sensor data, queries SQLite protocol database for calibration,
computes spatiotemporal gait parameters, Extrapolated Center of Mass (XCoM),
and Margin of Stability (MoS).
"""

import csv
import glob
import math
import os
import re
import sqlite3
import sys

import h5py
import numpy as np
import yaml

G = 9.81  # m/s^2
GRF_THRESHOLD = 20.0  # N – force threshold for stance detection
DB_PATH = '/app/protocol/config.db'


# ---- Calibration from SQLite ----

def get_calibration(db_path=DB_PATH):
    """Query sensor calibration parameters from protocol database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT sensor_name, scale_factor, offset FROM sensor_calibration")
    cal = {}
    for name, scale, offset in c.fetchall():
        cal[name] = {'scale': scale, 'offset': offset}
    conn.close()
    return cal


# ---- HDF5 I/O ----

def _decode(val):
    """Decode bytes to str if needed (h5py attribute handling)."""
    if isinstance(val, bytes):
        return val.decode()
    return val


def read_hdf5_run(filepath, calibration):
    """Read one run of sensor data from HDF5, applying calibration."""
    with h5py.File(filepath, 'r') as f:
        time = f['time'][:]

        com_pos = f['kinematics/com_position'][:]
        com_vel = f['kinematics/com_velocity'][:]
        feet = f['kinematics/foot_trajectories'][:]

        grf_right_raw = f['kinetics/grf_right_z'][:]
        grf_left_raw = f['kinetics/grf_left_z'][:]

        sensor_r = _decode(f['kinetics/grf_right_z'].attrs.get(
            'sensor_id', 'fp_right'))
        sensor_l = _decode(f['kinetics/grf_left_z'].attrs.get(
            'sensor_id', 'fp_left'))

    # Apply calibration: calibrated = (raw + offset) * scale_factor
    cal_r = calibration.get(sensor_r, {'scale': 1.0, 'offset': 0.0})
    cal_l = calibration.get(sensor_l, {'scale': 1.0, 'offset': 0.0})

    grf_right = (grf_right_raw + cal_r['offset']) * cal_r['scale']
    grf_left = (grf_left_raw + cal_l['offset']) * cal_l['scale']

    com = {
        'com_x': com_pos[:, 0], 'com_y': com_pos[:, 1],
        'com_z': com_pos[:, 2],
        'com_vel_x': com_vel[:, 0], 'com_vel_y': com_vel[:, 1],
        'com_vel_z': com_vel[:, 2],
    }
    foot = {
        'right_heel_x': feet[:, 0], 'right_heel_y': feet[:, 1],
        'right_heel_z': feet[:, 2],
        'left_heel_x': feet[:, 3], 'left_heel_y': feet[:, 4],
        'left_heel_z': feet[:, 5],
    }
    return time, com, foot, grf_right, grf_left


# ---- Gait event detection ----

def detect_events(grf_z, time, threshold=GRF_THRESHOLD):
    """Detect heel-strike (force onset) and toe-off (force offset) events."""
    in_stance = grf_z > threshold
    heel_strikes = []
    toe_offs = []
    for i in range(1, len(in_stance)):
        if in_stance[i] and not in_stance[i - 1]:
            heel_strikes.append(time[i])
        elif not in_stance[i] and in_stance[i - 1]:
            toe_offs.append(time[i])
    return np.array(heel_strikes), np.array(toe_offs)


# ---- XCoM ----

def xcom(pos, vel, omega0):
    """Extrapolated center of mass: XCoM = pos + vel / omega0."""
    return pos + vel / omega0


# ---- Spatiotemporal parameters ----

def compute_spatiotemporal(r_hs, l_hs, r_to, l_to, foot, time):
    """Compute per-run spatiotemporal gait parameters."""
    all_hs = sorted(
        [(t, 'R') for t in r_hs] + [(t, 'L') for t in l_hs]
    )

    step_times = []
    for i in range(1, len(all_hs)):
        if all_hs[i][1] != all_hs[i - 1][1]:
            step_times.append(all_hs[i][0] - all_hs[i - 1][0])

    stride_times = (
        list(np.diff(r_hs)) + list(np.diff(l_hs))
    ) if len(r_hs) > 1 or len(l_hs) > 1 else []

    step_lengths, step_widths = [], []
    for i in range(1, len(all_hs)):
        if all_hs[i][1] == all_hs[i - 1][1]:
            continue
        idx_c = np.argmin(np.abs(time - all_hs[i][0]))
        idx_p = np.argmin(np.abs(time - all_hs[i - 1][0]))
        if all_hs[i][1] == 'R':
            fx_c = foot['right_heel_x'][idx_c]
            fx_p = foot['left_heel_x'][idx_p]
            fy_c = foot['right_heel_y'][idx_c]
            fy_p = foot['left_heel_y'][idx_p]
        else:
            fx_c = foot['left_heel_x'][idx_c]
            fx_p = foot['right_heel_x'][idx_p]
            fy_c = foot['left_heel_y'][idx_c]
            fy_p = foot['right_heel_y'][idx_p]
        step_lengths.append(abs(fx_c - fx_p))
        step_widths.append(abs(fy_c - fy_p))

    stance_ratios = []
    for hs_arr, to_arr in [(r_hs, r_to), (l_hs, l_to)]:
        for t_hs in hs_arr:
            tos = to_arr[to_arr > t_hs]
            next_hs = hs_arr[hs_arr > t_hs]
            if len(tos) > 0 and len(next_hs) > 0:
                st = tos[0] - t_hs
                ct = next_hs[0] - t_hs
                if ct > 0:
                    stance_ratios.append(st / ct)

    ws = (
        float(np.mean(step_lengths) / np.mean(step_times))
        if step_times and step_lengths else 0.0
    )
    cad = 60.0 / np.mean(step_times) if step_times else 0.0

    def _stat(arr):
        a = np.array(arr) if arr else np.array([0.0])
        return float(np.mean(a)), float(np.std(a))

    return {
        'step_time':     {'mean': _stat(step_times)[0],     'std': _stat(step_times)[1],     'unit': 's'},
        'stride_time':   {'mean': _stat(stride_times)[0],   'std': _stat(stride_times)[1],   'unit': 's'},
        'step_length':   {'mean': _stat(step_lengths)[0],   'std': _stat(step_lengths)[1],   'unit': 'm'},
        'step_width':    {'mean': _stat(step_widths)[0],    'std': _stat(step_widths)[1],    'unit': 'm'},
        'cadence':       {'mean': float(cad),                'std': 0.0,                      'unit': 'steps/min'},
        'walking_speed': {'mean': ws,                        'std': 0.0,                      'unit': 'm/s'},
        'stance_ratio':  {'mean': _stat(stance_ratios)[0],  'std': _stat(stance_ratios)[1],  'unit': 'fraction'},
    }


# ---- Stability ----

def compute_stability(com, foot, r_hs, l_hs, time, leg_length):
    """Compute XCoM and MoS at each heel-strike event."""
    omega0 = math.sqrt(G / leg_length)

    all_hs = sorted(
        [(t, 'R') for t in r_hs] + [(t, 'L') for t in l_hs]
    )

    mos_ml, mos_ap = [], []
    xcom_ml_vals, xcom_ap_vals = [], []

    for t_hs, side in all_hs:
        idx = np.argmin(np.abs(time - t_hs))

        cx = com['com_x'][idx]
        cy = com['com_y'][idx]
        cvx = com['com_vel_x'][idx]
        cvy = com['com_vel_y'][idx]

        xc_x = xcom(cx, cvx, omega0)
        xc_y = xcom(cy, cvy, omega0)

        if side == 'R':
            f_x = foot['right_heel_x'][idx]
            f_y = foot['right_heel_y'][idx]
        else:
            f_x = foot['left_heel_x'][idx]
            f_y = foot['left_heel_y'][idx]

        mos_ap.append(f_x - xc_x)
        mos_ml.append(abs(f_y - xc_y))
        xcom_ap_vals.append(xc_x)
        xcom_ml_vals.append(xc_y)

    def _stat(arr):
        a = np.array(arr) if arr else np.array([0.0])
        return float(np.mean(a)), float(np.std(a))

    return {
        'mos_ml':        {'mean': _stat(mos_ml)[0],        'std': _stat(mos_ml)[1],        'unit': 'm'},
        'mos_ap':        {'mean': _stat(mos_ap)[0],        'std': _stat(mos_ap)[1],        'unit': 'm'},
        'xcom_ml_at_hs': {'mean': _stat(xcom_ml_vals)[0], 'std': _stat(xcom_ml_vals)[1], 'unit': 'm'},
        'xcom_ap_at_hs': {'mean': _stat(xcom_ap_vals)[0], 'std': _stat(xcom_ap_vals)[1], 'unit': 'm'},
        'n_strides':     len(mos_ml),
    }


# ---- Run processing ----

def process_run(in_dir, out_dir, sid, cid, rid, subj, calibration):
    pfx = f"subject_{sid:02d}_cond_{cid:02d}_run_{rid:02d}"
    filepath = os.path.join(in_dir, f"{pfx}.h5")

    time, com, foot, grf_right, grf_left = read_hdf5_run(filepath, calibration)

    r_hs, r_to = detect_events(grf_right, time)
    l_hs, l_to = detect_events(grf_left, time)

    spatio = compute_spatiotemporal(r_hs, l_hs, r_to, l_to, foot, time)
    stab = compute_stability(com, foot, r_hs, l_hs, time, subj['leg_length'])

    with open(os.path.join(out_dir, f"{pfx}_spatiotemporal.yaml"), 'w') as f:
        yaml.dump(spatio, f, default_flow_style=False)
    with open(os.path.join(out_dir, f"{pfx}_stability.yaml"), 'w') as f:
        yaml.dump(stab, f, default_flow_style=False)

    return spatio, stab


def aggregate(all_spatio, all_stab, out_dir, sid, cid):
    agg = {}
    for dicts in (all_spatio, all_stab):
        for key in dicts[0]:
            entry = dicts[0][key]
            if isinstance(entry, dict) and 'mean' in entry:
                means = [d[key]['mean'] for d in dicts]
                agg[key] = {
                    'mean': float(np.mean(means)),
                    'std':  float(np.std(means)),
                    'unit': entry['unit'],
                }
    agg['num_runs'] = len(all_spatio)
    path = os.path.join(out_dir,
                        f"subject_{sid:02d}_cond_{cid:02d}_aggregated.yaml")
    with open(path, 'w') as f:
        yaml.dump(agg, f, default_flow_style=False)


def write_summary(out_dir, runs_map, sid):
    path = os.path.join(out_dir, 'summary.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['condition', 'run', 'step_time', 'step_length',
                     'cadence', 'walking_speed', 'mos_ml', 'mos_ap'])
        for cid in sorted(runs_map):
            for rid in sorted(runs_map[cid]):
                pfx = f"subject_{sid:02d}_cond_{cid:02d}_run_{rid:02d}"
                with open(os.path.join(out_dir,
                          f"{pfx}_spatiotemporal.yaml")) as yf:
                    sp = yaml.safe_load(yf)
                with open(os.path.join(out_dir,
                          f"{pfx}_stability.yaml")) as yf:
                    st = yaml.safe_load(yf)
                w.writerow([
                    cid, rid,
                    f"{sp['step_time']['mean']:.4f}",
                    f"{sp['step_length']['mean']:.4f}",
                    f"{sp['cadence']['mean']:.1f}",
                    f"{sp['walking_speed']['mean']:.4f}",
                    f"{st['mos_ml']['mean']:.4f}",
                    f"{st['mos_ap']['mean']:.4f}",
                ])


# ---- Main ----

def main(in_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    # Get calibration from protocol database
    calibration = get_calibration()

    # Subject info
    subj_files = glob.glob(os.path.join(in_dir, 'subject_*_info.yaml'))
    if not subj_files:
        raise FileNotFoundError("No subject_*_info.yaml found")
    with open(subj_files[0]) as f:
        subj = yaml.safe_load(f)
    sid = subj.get('subject_id', 1)

    # Discover conditions and runs from HDF5 files
    h5_files = glob.glob(os.path.join(in_dir, '*.h5'))
    runs_map = {}
    for hf in h5_files:
        m = re.match(
            r'subject_(\d+)_cond_(\d+)_run_(\d+)\.h5',
            os.path.basename(hf),
        )
        if m:
            c, r = int(m.group(2)), int(m.group(3))
            runs_map.setdefault(c, []).append(r)

    # Process
    for cid in sorted(runs_map):
        all_sp, all_st = [], []
        for rid in sorted(runs_map[cid]):
            sp, st = process_run(in_dir, out_dir, sid, cid, rid, subj,
                                 calibration)
            all_sp.append(sp)
            all_st.append(st)
        aggregate(all_sp, all_st, out_dir, sid, cid)

    write_summary(out_dir, runs_map, sid)
    print("Pipeline complete.")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_dir>",
              file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
