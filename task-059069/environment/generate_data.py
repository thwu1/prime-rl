#!/usr/bin/env python3
"""Generate synthetic Eurobench-format bipedal walking data in HDF5 format and
create protocol configuration SQLite database."""

import numpy as np
import os
import yaml
import h5py
import sqlite3

# DC offset applied to GRF raw data (in mN), simulating force plate zero drift
DC_OFFSET_MN = 5000.0


def generate_grf_profile(t_norm, body_weight):
    """Generate vertical GRF profile during stance phase.
    Uses a smooth single-hump with slight asymmetry."""
    f1 = 1.15 * np.sin(np.pi * t_norm)
    f2 = -0.15 * np.sin(2 * np.pi * t_norm)
    return body_weight * (f1 + f2)


def generate_condition_data(subject, condition, run_id, rng):
    """Generate one run of walking data for a given condition."""
    speed = condition['walking_speed']
    T_cycle = condition['gait_cycle_time']
    T_step = T_cycle / 2.0
    step_length = condition['step_length']
    stance_ratio = condition['stance_ratio']
    num_cycles = condition['num_cycles']
    A_ml = condition['amplitude_ml']
    A_vert = condition['amplitude_vert']

    leg_length = subject['leg_length']
    mass = subject['mass']
    body_weight = mass * 9.81

    fs = 200  # Hz
    duration = num_cycles * T_cycle
    t = np.arange(0, duration + 1.0 / fs, 1.0 / fs)
    N = len(t)

    # --- Center of mass trajectory ---
    drift_x = rng.normal(0, 0.0005, N).cumsum() * (1.0 / fs)
    com_x = speed * t + drift_x

    drift_y = rng.normal(0, 0.0003, N).cumsum() * (1.0 / fs)
    com_y = A_ml * np.cos(2 * np.pi * t / T_cycle) + drift_y

    drift_z = rng.normal(0, 0.0002, N).cumsum() * (1.0 / fs)
    com_z = leg_length + A_vert * np.cos(4 * np.pi * t / T_cycle) + drift_z

    com_vx = speed * np.ones(N) + rng.normal(0, 0.005, N)
    com_vy = -A_ml * (2 * np.pi / T_cycle) * np.sin(2 * np.pi * t / T_cycle) \
             + rng.normal(0, 0.003, N)
    com_vz = -A_vert * (4 * np.pi / T_cycle) * np.sin(4 * np.pi * t / T_cycle) \
             + rng.normal(0, 0.002, N)

    step_width_half = 0.10

    grf_right_z = np.zeros(N)
    grf_left_z = np.zeros(N)

    foot_right_x = np.zeros(N)
    foot_right_y = step_width_half * np.ones(N)
    foot_right_z = np.zeros(N)
    foot_left_x = np.zeros(N)
    foot_left_y = -step_width_half * np.ones(N)
    foot_left_z = np.zeros(N)

    stance_dur = stance_ratio * T_cycle

    # ---- Right foot ----
    for k in range(num_cycles + 1):
        t_rhs = k * T_cycle
        if t_rhs > duration:
            break
        t_rto = t_rhs + stance_dur
        foot_x_land = speed * t_rhs + step_length / 2.0

        mask_st = (t >= t_rhs) & (t < min(t_rto, duration + 1.0 / fs))
        foot_right_x[mask_st] = foot_x_land
        foot_right_z[mask_st] = 0.0
        if np.any(mask_st):
            t_st = t[mask_st] - t_rhs
            tn = np.clip(t_st / stance_dur, 0, 1)
            grf_right_z[mask_st] = generate_grf_profile(tn, body_weight)

        t_next_rhs = (k + 1) * T_cycle
        if t_rto <= duration and t_next_rhs <= duration + 1.0 / fs:
            mask_sw = (t >= t_rto) & (t < t_next_rhs)
            next_land = speed * t_next_rhs + step_length / 2.0
            if np.any(mask_sw):
                sw_dur = t_next_rhs - t_rto
                t_sw = t[mask_sw] - t_rto
                tn_sw = t_sw / sw_dur
                foot_right_x[mask_sw] = foot_x_land + (next_land - foot_x_land) * tn_sw
                foot_right_z[mask_sw] = 0.025 * np.sin(np.pi * tn_sw)

    # ---- Left foot (offset by T_step) ----
    for k in range(-1, num_cycles + 1):
        t_lhs = k * T_cycle + T_step
        if t_lhs > duration:
            break
        t_lto = t_lhs + stance_dur
        foot_x_land = speed * t_lhs + step_length / 2.0

        t_start = max(t_lhs, 0)
        t_end = min(t_lto, duration + 1.0 / fs)
        if t_start < t_end:
            mask_st = (t >= t_start) & (t < t_end)
            foot_left_x[mask_st] = foot_x_land
            foot_left_z[mask_st] = 0.0
            if np.any(mask_st):
                t_st = t[mask_st] - t_lhs
                tn = np.clip(t_st / stance_dur, 0, 1)
                grf_left_z[mask_st] = generate_grf_profile(tn, body_weight)

        t_next_lhs = (k + 1) * T_cycle + T_step
        if t_lto <= duration and t_next_lhs <= duration + 1.0 / fs:
            t_start_sw = max(t_lto, 0)
            t_end_sw = min(t_next_lhs, duration + 1.0 / fs)
            if t_start_sw < t_end_sw:
                mask_sw = (t >= t_start_sw) & (t < t_end_sw)
                next_land = speed * t_next_lhs + step_length / 2.0
                if np.any(mask_sw):
                    sw_dur = t_next_lhs - t_lto
                    t_sw = t[mask_sw] - t_lto
                    tn_sw = t_sw / sw_dur
                    foot_left_x[mask_sw] = foot_x_land + (next_land - foot_x_land) * tn_sw
                    foot_left_z[mask_sw] = 0.025 * np.sin(np.pi * tn_sw)

    # Add noise to GRF (in Newtons)
    grf_right_z += rng.normal(0, 5.0, N) * (grf_right_z > 10)
    grf_left_z += rng.normal(0, 5.0, N) * (grf_left_z > 10)
    grf_right_z += rng.normal(0, 1.0, N)
    grf_left_z += rng.normal(0, 1.0, N)
    grf_right_z = np.maximum(grf_right_z, 0)
    grf_left_z = np.maximum(grf_left_z, 0)

    return {
        't': t,
        'com_x': com_x, 'com_y': com_y, 'com_z': com_z,
        'com_vx': com_vx, 'com_vy': com_vy, 'com_vz': com_vz,
        'grf_right_z': grf_right_z, 'grf_left_z': grf_left_z,
        'foot_right_x': foot_right_x, 'foot_right_y': foot_right_y,
        'foot_right_z': foot_right_z,
        'foot_left_x': foot_left_x, 'foot_left_y': foot_left_y,
        'foot_left_z': foot_left_z,
    }


def write_hdf5(filepath, data, subject, cond_id, run_id, fs=200):
    """Write one run of data to HDF5 with hierarchical structure.
    GRF is stored in raw sensor units (mN with DC offset)."""
    with h5py.File(filepath, 'w') as f:
        f.attrs['sample_rate'] = fs
        f.attrs['subject_id'] = subject['subject_id']
        f.attrs['condition_id'] = cond_id
        f.attrs['run_id'] = run_id

        ds_time = f.create_dataset('time', data=data['t'])
        ds_time.attrs['unit'] = 's'

        kin = f.create_group('kinematics')

        com_pos = np.column_stack([data['com_x'], data['com_y'], data['com_z']])
        ds = kin.create_dataset('com_position', data=com_pos)
        ds.attrs['columns'] = 'x,y,z'
        ds.attrs['unit'] = 'm'

        com_vel = np.column_stack([data['com_vx'], data['com_vy'], data['com_vz']])
        ds = kin.create_dataset('com_velocity', data=com_vel)
        ds.attrs['columns'] = 'vx,vy,vz'
        ds.attrs['unit'] = 'm/s'

        feet = np.column_stack([
            data['foot_right_x'], data['foot_right_y'], data['foot_right_z'],
            data['foot_left_x'], data['foot_left_y'], data['foot_left_z'],
        ])
        ds = kin.create_dataset('foot_trajectories', data=feet)
        ds.attrs['columns'] = 'right_heel_x,right_heel_y,right_heel_z,left_heel_x,left_heel_y,left_heel_z'
        ds.attrs['unit'] = 'm'

        kinet = f.create_group('kinetics')

        # Store GRF in raw sensor units: milliNewtons with DC zero-drift offset
        grf_r_raw = data['grf_right_z'] * 1000.0 + DC_OFFSET_MN
        ds = kinet.create_dataset('grf_right_z', data=grf_r_raw)
        ds.attrs['unit'] = 'mN'
        ds.attrs['sensor_id'] = 'fp_right'

        grf_l_raw = data['grf_left_z'] * 1000.0 + DC_OFFSET_MN
        ds = kinet.create_dataset('grf_left_z', data=grf_l_raw)
        ds.attrs['unit'] = 'mN'
        ds.attrs['sensor_id'] = 'fp_left'


def create_protocol_db(db_path):
    """Create SQLite protocol configuration database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Required output metrics
    c.execute('''CREATE TABLE required_metrics (
        metric_name TEXT NOT NULL,
        output_type TEXT NOT NULL CHECK(output_type IN ('spatiotemporal', 'stability')),
        unit TEXT NOT NULL,
        description TEXT
    )''')
    metrics = [
        ('step_time', 'spatiotemporal', 's',
         'Duration between successive contralateral heel contacts'),
        ('stride_time', 'spatiotemporal', 's',
         'Duration between successive ipsilateral heel contacts'),
        ('step_length', 'spatiotemporal', 'm',
         'Anteroposterior inter-foot distance at heel contacts'),
        ('step_width', 'spatiotemporal', 'm',
         'Mediolateral inter-foot distance at heel contacts'),
        ('cadence', 'spatiotemporal', 'steps/min', 'Step frequency'),
        ('walking_speed', 'spatiotemporal', 'm/s', 'Forward locomotion velocity'),
        ('stance_ratio', 'spatiotemporal', 'fraction',
         'Stance phase duration relative to full gait cycle'),
        ('mos_ml', 'stability', 'm',
         'Mediolateral margin of stability at heel contact'),
        ('mos_ap', 'stability', 'm',
         'Anteroposterior margin of stability at heel contact'),
    ]
    c.executemany('INSERT INTO required_metrics VALUES (?,?,?,?)', metrics)

    # Sensor calibration parameters
    c.execute('''CREATE TABLE sensor_calibration (
        sensor_name TEXT PRIMARY KEY,
        raw_unit TEXT NOT NULL,
        target_unit TEXT NOT NULL,
        scale_factor REAL NOT NULL,
        offset REAL NOT NULL DEFAULT 0.0,
        description TEXT
    )''')
    calibrations = [
        ('fp_right', 'mN', 'N', 0.001, -5000.0,
         'Right force plate vertical GRF calibration'),
        ('fp_left', 'mN', 'N', 0.001, -5000.0,
         'Left force plate vertical GRF calibration'),
    ]
    c.executemany('INSERT INTO sensor_calibration VALUES (?,?,?,?,?,?)',
                  calibrations)

    # Calibration formula documentation
    c.execute('''CREATE TABLE calibration_formula (
        id INTEGER PRIMARY KEY,
        formula TEXT NOT NULL,
        description TEXT
    )''')
    c.execute("INSERT INTO calibration_formula VALUES (?, ?, ?)",
              (1, 'calibrated = (raw + offset) * scale_factor',
               'Apply sensor calibration. Offset corrects zero-level drift '
               '(added to raw before scaling). Scale converts from raw_unit '
               'to target_unit.'))

    # Output naming conventions
    c.execute('''CREATE TABLE output_naming (
        output_level TEXT PRIMARY KEY,
        pattern TEXT NOT NULL,
        description TEXT
    )''')
    naming = [
        ('per_run_spatiotemporal',
         'subject_{sid:02d}_cond_{cid:02d}_run_{rid:02d}_spatiotemporal.yaml',
         'Per-run spatiotemporal metrics'),
        ('per_run_stability',
         'subject_{sid:02d}_cond_{cid:02d}_run_{rid:02d}_stability.yaml',
         'Per-run stability metrics'),
        ('per_condition',
         'subject_{sid:02d}_cond_{cid:02d}_aggregated.yaml',
         'Cross-run aggregated metrics'),
        ('summary', 'summary.csv', 'Summary across all runs'),
    ]
    c.executemany('INSERT INTO output_naming VALUES (?,?,?)', naming)

    # Summary CSV column definitions
    c.execute('''CREATE TABLE summary_columns (
        column_name TEXT NOT NULL,
        column_order INTEGER NOT NULL
    )''')
    columns = [
        ('condition', 1), ('run', 2), ('step_time', 3), ('step_length', 4),
        ('cadence', 5), ('walking_speed', 6), ('mos_ml', 7), ('mos_ap', 8),
    ]
    c.executemany('INSERT INTO summary_columns VALUES (?,?)', columns)

    # Metric schema definition
    c.execute('''CREATE TABLE metric_schema (
        key TEXT PRIMARY KEY,
        required_fields TEXT NOT NULL,
        description TEXT
    )''')
    c.execute("INSERT INTO metric_schema VALUES (?, ?, ?)",
              ('standard', 'mean,std,unit',
               'Each metric must be a dict with mean, std, and unit fields'))

    conn.commit()
    conn.close()


def main():
    output_dir = '/app/data'
    os.makedirs(output_dir, exist_ok=True)
    protocol_dir = '/app/protocol'
    os.makedirs(protocol_dir, exist_ok=True)

    subject = {
        'subject_id': 1,
        'mass': 72.0,
        'height': 1.80,
        'leg_length': 0.92,
        'age': 35,
        'sex': 'M',
    }
    with open(os.path.join(output_dir, 'subject_01_info.yaml'), 'w') as f:
        yaml.dump(subject, f, default_flow_style=False)

    conditions = {
        1: {
            'condition_id': 1,
            'description': 'normal walking speed on flat ground',
            'walking_speed': 1.3,
            'step_length': 0.65,
            'gait_cycle_time': 1.0,
            'stance_ratio': 0.62,
            'num_cycles': 10,
            'amplitude_ml': 0.025,
            'amplitude_vert': 0.02,
            'slope_angle': 0.0,
        },
        2: {
            'condition_id': 2,
            'description': 'fast walking speed on flat ground',
            'walking_speed': 1.8,
            'step_length': 0.81,
            'gait_cycle_time': 0.9,
            'stance_ratio': 0.58,
            'num_cycles': 11,
            'amplitude_ml': 0.025,
            'amplitude_vert': 0.018,
            'slope_angle': 0.0,
        },
    }

    for cid, cond in conditions.items():
        cond_yaml = {
            'condition_id': cond['condition_id'],
            'description': cond['description'],
            'walking_speed': cond['walking_speed'],
            'slope_angle': cond['slope_angle'],
        }
        with open(os.path.join(output_dir, f'condition_{cid:02d}.yaml'), 'w') as f:
            yaml.dump(cond_yaml, f, default_flow_style=False)

    base_seed = 42
    for cid, cond in conditions.items():
        for rid in [1, 2]:
            seed = base_seed + cid * 10 + rid
            rng = np.random.default_rng(seed)
            data = generate_condition_data(subject, cond, rid, rng)
            filepath = os.path.join(
                output_dir, f"subject_01_cond_{cid:02d}_run_{rid:02d}.h5")
            write_hdf5(filepath, data, subject, cid, rid)

    # Create protocol configuration database
    create_protocol_db(os.path.join(protocol_dir, 'config.db'))

    print(f"Generated HDF5 data in {output_dir}")
    for fn in sorted(os.listdir(output_dir)):
        print(f"  {fn}")
    print(f"Created protocol database at {protocol_dir}/config.db")


if __name__ == '__main__':
    main()
