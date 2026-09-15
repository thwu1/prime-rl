#!/usr/bin/env python3
"""
Generate telemetry database and calibration binary for ROV fault diagnosis task.
This script runs ONLY during Docker build (builder stage) and is NOT included
in the final image.
"""

import numpy as np
import sqlite3
import struct
import os

np.random.seed(42)

# ============================================================
# TRUE thruster configuration (ground truth - what physics uses)
# ============================================================
TRUE_THRUSTERS = [
    {"id": 1, "pos": [0.18, 0.15, 0.0],   "dir": [0.7071068, -0.7071068, 0.0]},
    {"id": 2, "pos": [0.18, -0.15, 0.0],   "dir": [0.7071068, 0.7071068, 0.0]},
    {"id": 3, "pos": [-0.20, 0.18, 0.0],   "dir": [-0.7071068, -0.7071068, 0.0]},
    {"id": 4, "pos": [-0.20, -0.18, 0.0],  "dir": [-0.7071068, 0.7071068, 0.0]},
    {"id": 5, "pos": [0.12, 0.16, 0.03],   "dir": [0.0, 0.0, 1.0]},
    {"id": 6, "pos": [0.12, -0.16, 0.03],  "dir": [0.0, 0.0, 1.0]},
    {"id": 7, "pos": [-0.14, 0.16, 0.03],  "dir": [0.0, 0.0, 1.0]},
    {"id": 8, "pos": [-0.14, -0.16, 0.03], "dir": [0.0, 0.0, 1.0]},
]

MASS = 12.5
INERTIA = {"Ixx": 0.21, "Iyy": 0.24, "Izz": 0.18}

THRUST_COEFFS = [5.2, 4.8, 5.0, 5.1, 3.6, 3.8, 3.5, 3.7]
DEADBAND_POS = [0.030, 0.030, 0.025, 0.030, 0.035, 0.030, 0.025, 0.030]
DEADBAND_NEG = [0.035, 0.030, 0.030, 0.025, 0.030, 0.035, 0.030, 0.025]
MAX_FWD = [5.5, 5.2, 5.3, 5.4, 3.8, 4.0, 3.7, 3.9]
MAX_REV = [4.5, 4.2, 4.3, 4.4, 3.0, 3.2, 2.9, 3.1]
CAL_DATES = [1710000000 + i * 86400 for i in range(8)]


def build_allocation_matrix(thrusters):
    B = np.zeros((6, len(thrusters)))
    for i, t in enumerate(thrusters):
        d = np.array(t["dir"])
        p = np.array(t["pos"])
        B[0:3, i] = d
        B[3:6, i] = np.cross(p, d)
    return B


def build_mass_matrix():
    M = np.zeros((6, 6))
    M[0:3, 0:3] = MASS * np.eye(3)
    M[3, 3] = INERTIA["Ixx"]
    M[4, 4] = INERTIA["Iyy"]
    M[5, 5] = INERTIA["Izz"]
    return M


def create_database(db_path, B_true, M_inv):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE sessions (
        session_id INTEGER PRIMARY KEY,
        session_date TEXT NOT NULL,
        session_type TEXT NOT NULL,
        description TEXT,
        operator TEXT,
        duration_sec REAL,
        sample_rate_hz REAL
    )""")

    c.execute("""CREATE TABLE thruster_commands (
        session_id INTEGER NOT NULL,
        timestamp_us INTEGER NOT NULL,
        thruster_id INTEGER NOT NULL,
        pwm_us INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE imu_data (
        session_id INTEGER NOT NULL,
        timestamp_us INTEGER NOT NULL,
        accel_x REAL,
        accel_y REAL,
        accel_z REAL,
        ang_accel_x REAL,
        ang_accel_y REAL,
        ang_accel_z REAL,
        temperature_c REAL
    )""")

    c.execute("""CREATE TABLE pressure_depth (
        session_id INTEGER NOT NULL,
        timestamp_us INTEGER NOT NULL,
        pressure_mbar REAL,
        depth_m REAL,
        temperature_c REAL
    )""")

    c.execute("""CREATE TABLE motor_health (
        session_id INTEGER NOT NULL,
        thruster_id INTEGER NOT NULL,
        avg_current_a REAL,
        max_rpm INTEGER,
        motor_temp_c REAL,
        esc_temp_c REAL,
        status TEXT,
        PRIMARY KEY (session_id, thruster_id)
    )""")

    c.execute("CREATE INDEX idx_cmd_sess_ts ON thruster_commands(session_id, timestamp_us)")
    c.execute("CREATE INDEX idx_imu_sess_ts ON imu_data(session_id, timestamp_us)")

    sessions = [
        (1, '2026-04-10', 'field_ops',
         'Reef survey dive - all thrusters active, currents present',
         'K. Park', 1200.0, 50.0),
        (2, '2026-05-14', 'maintenance_check',
         'Quick post-maintenance functionality check - brief motor test',
         'J. Chen', 120.0, 50.0),
        (3, '2026-05-15', 'thruster_test',
         'Systematic single and multi-thruster firing patterns for system identification',
         'J. Chen', 180.0, 50.0),
        (4, '2026-05-18', 'field_ops',
         'Pipeline inspection dive - variable depth, strong crosscurrent',
         'M. Rodriguez', 900.0, 50.0),
    ]
    c.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", sessions)

    coeffs = np.array(THRUST_COEFFS)
    dt_us = 20000  # 50 Hz

    # === Session 3: Controlled thruster test (THE ONE) ===
    n_test = 200
    cmds_norm = np.random.uniform(-0.8, 0.8, (n_test, 8))
    for t in range(n_test):
        ts = t * dt_us
        # Store exact PWM values and recompute forces from those to avoid
        # quantization mismatch between generation and recovery
        pwm_vals = np.clip((cmds_norm[t] * 400 + 1500), 1100, 1900).astype(int)
        norm_from_pwm = (pwm_vals - 1500.0) / 400.0
        forces = norm_from_pwm * coeffs
        wrench = B_true @ forces
        accel = M_inv @ wrench + np.random.normal(0, 0.002, 6)
        for tid in range(8):
            c.execute("INSERT INTO thruster_commands VALUES (3,?,?,?)",
                      (ts, tid + 1, int(pwm_vals[tid])))
        c.execute("INSERT INTO imu_data VALUES (3,?,?,?,?,?,?,?,?)",
                  (ts, accel[0], accel[1], accel[2],
                   accel[3], accel[4], accel[5],
                   35.2 + np.random.normal(0, 0.1)))

    # === Session 1: Field ops (correlated commands, high noise) ===
    n_s1 = 250
    for t in range(n_s1):
        ts = t * dt_us
        base_cmd = np.random.uniform(-0.3, 0.3)
        cmds = np.clip(base_cmd + np.random.normal(0, 0.05, 8), -1, 1)
        pwm_vals = np.clip((cmds * 400 + 1500), 1100, 1900).astype(int)
        for tid in range(8):
            c.execute("INSERT INTO thruster_commands VALUES (1,?,?,?)",
                      (ts, tid + 1, int(pwm_vals[tid])))
        forces = cmds * coeffs
        wrench = B_true @ forces
        accel = M_inv @ wrench + np.random.normal(0, 0.15, 6)
        c.execute("INSERT INTO imu_data VALUES (1,?,?,?,?,?,?,?,?)",
                  (ts, accel[0], accel[1], accel[2],
                   accel[3], accel[4], accel[5],
                   33.5 + np.random.normal(0, 0.2)))

    # === Session 2: Quick maintenance check (very few samples) ===
    n_s2 = 12
    for t in range(n_s2):
        ts = t * dt_us * 4
        cmds = np.random.uniform(-0.4, 0.4, 8)
        pwm_vals = np.clip((cmds * 400 + 1500), 1100, 1900).astype(int)
        for tid in range(8):
            c.execute("INSERT INTO thruster_commands VALUES (2,?,?,?)",
                      (ts, tid + 1, int(pwm_vals[tid])))
        forces = cmds * coeffs
        wrench = B_true @ forces
        accel = M_inv @ wrench + np.random.normal(0, 0.02, 6)
        c.execute("INSERT INTO imu_data VALUES (2,?,?,?,?,?,?,?,?)",
                  (ts, accel[0], accel[1], accel[2],
                   accel[3], accel[4], accel[5],
                   34.0 + np.random.normal(0, 0.1)))

    # === Session 4: Pipeline inspection (large external disturbances) ===
    n_s4 = 350
    for t in range(n_s4):
        ts = t * dt_us
        cmds = np.random.uniform(-0.7, 0.7, 8)
        pwm_vals = np.clip((cmds * 400 + 1500), 1100, 1900).astype(int)
        for tid in range(8):
            c.execute("INSERT INTO thruster_commands VALUES (4,?,?,?)",
                      (ts, tid + 1, int(pwm_vals[tid])))
        forces = cmds * coeffs
        wrench = B_true @ forces + np.random.normal(0, 2.5, 6)
        accel = M_inv @ wrench
        c.execute("INSERT INTO imu_data VALUES (4,?,?,?,?,?,?,?,?)",
                  (ts, accel[0], accel[1], accel[2],
                   accel[3], accel[4], accel[5],
                   32.0 + np.random.normal(0, 0.3)))

    # Pressure/depth for sessions 1,4
    for sid, n, base_d in [(1, 250, 5.0), (4, 350, 12.0)]:
        for t in range(n):
            ts = t * dt_us
            depth = base_d + 0.5 * np.sin(t * 0.01) + np.random.normal(0, 0.05)
            pressure = 1013.25 + depth * 100.5
            c.execute("INSERT INTO pressure_depth VALUES (?,?,?,?,?)",
                      (sid, ts, round(pressure, 2), round(depth, 3),
                       18.0 + np.random.normal(0, 0.1)))

    # Motor health for all sessions
    for sid in [1, 2, 3, 4]:
        for tid in range(1, 9):
            c.execute("INSERT INTO motor_health VALUES (?,?,?,?,?,?,?)",
                      (sid, tid,
                       round(2.5 + np.random.normal(0, 0.3), 2),
                       3000 + np.random.randint(-200, 200),
                       round(35.0 + np.random.normal(0, 2), 1),
                       round(40.0 + np.random.normal(0, 3), 1),
                       'OK'))

    conn.commit()
    conn.close()


def create_calibration_binary(cal_path):
    with open(cal_path, 'wb') as f:
        f.write(b'TCAL')
        f.write(struct.pack('<B', 2))
        f.write(struct.pack('<B', 8))
        f.write(struct.pack('<H', 0))

        for i in range(8):
            f.write(struct.pack('<B', i + 1))
            f.write(b'\x00\x00\x00')
            f.write(struct.pack('<I', CAL_DATES[i]))
            f.write(struct.pack('<d', THRUST_COEFFS[i]))
            f.write(struct.pack('<f', DEADBAND_POS[i]))
            f.write(struct.pack('<f', DEADBAND_NEG[i]))
            f.write(struct.pack('<f', MAX_FWD[i]))
            f.write(struct.pack('<f', MAX_REV[i]))


if __name__ == "__main__":
    B_true = build_allocation_matrix(TRUE_THRUSTERS)
    M = build_mass_matrix()
    M_inv = np.linalg.inv(M)

    create_database("/tmp/flight_test.db", B_true, M_inv)
    create_calibration_binary("/tmp/thrust_cal.dat")
    print("Data generation complete")
    print(f"  DB: /tmp/flight_test.db")
    print(f"  Cal: /tmp/thrust_cal.dat ({os.path.getsize('/tmp/thrust_cal.dat')} bytes)")
