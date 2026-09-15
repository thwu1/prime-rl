#!/usr/bin/env python3
"""
ROV thruster fault diagnosis via system identification.


Strategy:
1. Parse frame.param (ArduPilot format) to get faulty thruster config.
2. Parse vehicle.urdf (XML) to extract mass and inertia tensor.
3. Decode thrust_cal.dat (binary) to get per-thruster thrust coefficients.
4. Query flight_test.db (SQLite) for session 3 data:
   - Pivot long-format thruster_commands into wide 8-column matrix
   - Join with imu_data on session_id and timestamp_us
5. Convert PWM commands to forces using calibration coefficients.
6. Build mass matrix M and compute wrenches W = M @ accelerations.
7. System identification: B_true = W @ pinv(F).
8. Compare B_true vs B_faulty to identify faults.
9. Output diagnosis.json.
"""

import json
import struct
import sqlite3
import re
import numpy as np
import xml.etree.ElementTree as ET


def parse_param_file(path):
    """Parse ArduPilot .param file into a dict of parameter values."""
    params = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                params[parts[0].strip()] = parts[1].strip()
    return params


def extract_thrusters_from_params(params):
    """Extract thruster config from MOT_*_POS_* and MOT_*_DIR_* parameters."""
    thrusters = []
    for tid in range(1, 9):
        pos = [
            float(params[f'MOT_{tid}_POS_X']),
            float(params[f'MOT_{tid}_POS_Y']),
            float(params[f'MOT_{tid}_POS_Z']),
        ]
        direction = [
            float(params[f'MOT_{tid}_DIR_X']),
            float(params[f'MOT_{tid}_DIR_Y']),
            float(params[f'MOT_{tid}_DIR_Z']),
        ]
        thrusters.append({
            "id": tid,
            "position": pos,
            "direction": direction,
        })
    return thrusters


def parse_urdf(path):
    """Parse URDF XML to extract mass and inertia tensor from base_link."""
    tree = ET.parse(path)
    root = tree.getroot()

    # Find the base_link element
    for link in root.findall('link'):
        if link.get('name') == 'base_link':
            inertial = link.find('inertial')
            mass = float(inertial.find('mass').get('value'))
            inertia_el = inertial.find('inertia')
            inertia = {
                'Ixx': float(inertia_el.get('ixx')),
                'Iyy': float(inertia_el.get('iyy')),
                'Izz': float(inertia_el.get('izz')),
                'Ixy': float(inertia_el.get('ixy', '0')),
                'Ixz': float(inertia_el.get('ixz', '0')),
                'Iyz': float(inertia_el.get('iyz', '0')),
            }
            return mass, inertia

    raise ValueError("base_link not found in URDF")


def decode_calibration_binary(path):
    """Decode the TCAL v2 binary calibration file."""
    coefficients = {}
    with open(path, 'rb') as f:
        # Header: 8 bytes
        magic = f.read(4)
        assert magic == b'TCAL', f"Invalid magic: {magic}"
        version = struct.unpack('<B', f.read(1))[0]
        num_thrusters = struct.unpack('<B', f.read(1))[0]
        flags = struct.unpack('<H', f.read(2))[0]

        # Per-thruster records: 32 bytes each
        for _ in range(num_thrusters):
            tid = struct.unpack('<B', f.read(1))[0]
            f.read(3)  # padding
            cal_date = struct.unpack('<I', f.read(4))[0]
            thrust_coeff = struct.unpack('<d', f.read(8))[0]
            deadband_pos = struct.unpack('<f', f.read(4))[0]
            deadband_neg = struct.unpack('<f', f.read(4))[0]
            max_fwd = struct.unpack('<f', f.read(4))[0]
            max_rev = struct.unpack('<f', f.read(4))[0]
            coefficients[tid] = thrust_coeff

    return coefficients


def query_telemetry(db_path, session_id=3):
    """Query SQLite DB for thruster commands and IMU data.

    Commands are in long format (one row per thruster per timestep).
    Must pivot to wide format and join with imu_data.
    """
    conn = sqlite3.connect(db_path)

    # Pivot thruster_commands from long to wide
    # and join with imu_data on matching timestamps
    query = """
    SELECT
        c.timestamp_us,
        MAX(CASE WHEN c.thruster_id = 1 THEN c.pwm_us END) AS t1_pwm,
        MAX(CASE WHEN c.thruster_id = 2 THEN c.pwm_us END) AS t2_pwm,
        MAX(CASE WHEN c.thruster_id = 3 THEN c.pwm_us END) AS t3_pwm,
        MAX(CASE WHEN c.thruster_id = 4 THEN c.pwm_us END) AS t4_pwm,
        MAX(CASE WHEN c.thruster_id = 5 THEN c.pwm_us END) AS t5_pwm,
        MAX(CASE WHEN c.thruster_id = 6 THEN c.pwm_us END) AS t6_pwm,
        MAX(CASE WHEN c.thruster_id = 7 THEN c.pwm_us END) AS t7_pwm,
        MAX(CASE WHEN c.thruster_id = 8 THEN c.pwm_us END) AS t8_pwm,
        i.accel_x, i.accel_y, i.accel_z,
        i.ang_accel_x, i.ang_accel_y, i.ang_accel_z
    FROM thruster_commands c
    JOIN imu_data i ON c.session_id = i.session_id
                    AND c.timestamp_us = i.timestamp_us
    WHERE c.session_id = ?
    GROUP BY c.timestamp_us
    ORDER BY c.timestamp_us
    """

    rows = conn.execute(query, (session_id,)).fetchall()
    conn.close()

    n = len(rows)
    pwm_cmds = np.zeros((n, 8))
    accels = np.zeros((n, 6))

    for i, row in enumerate(rows):
        pwm_cmds[i] = row[1:9]
        accels[i] = row[9:15]

    return pwm_cmds, accels


def build_mass_matrix(mass, inertia):
    """Construct 6x6 mass/inertia matrix."""
    M = np.zeros((6, 6))
    M[0:3, 0:3] = mass * np.eye(3)
    M[3, 3] = inertia['Ixx']
    M[3, 4] = inertia['Ixy']
    M[3, 5] = inertia['Ixz']
    M[4, 3] = inertia['Ixy']
    M[4, 4] = inertia['Iyy']
    M[4, 5] = inertia['Iyz']
    M[5, 3] = inertia['Ixz']
    M[5, 4] = inertia['Iyz']
    M[5, 5] = inertia['Izz']
    return M


def build_allocation_matrix(thrusters):
    """Build 6x8 TAM: force rows = direction, torque rows = cross(pos, dir)."""
    n = len(thrusters)
    B = np.zeros((6, n))
    for i, t in enumerate(thrusters):
        pos = np.array(t["position"])
        d = np.array(t["direction"])
        B[0:3, i] = d
        B[3:6, i] = np.cross(pos, d)
    return B


def recover_position_from_torque(direction, torque, z_known):
    """
    Given torque = position x direction, recover position.
    Uses the constraint that pz = z_known.
    """
    d = np.array(direction)
    T = np.array(torque)

    # T = p x d:
    # T_x = py*dz - pz*dy
    # T_y = pz*dx - px*dz
    # T_z = px*dy - py*dx
    A = np.array([
        [0.0, d[2]],
        [-d[2], 0.0],
        [d[1], -d[0]],
    ])
    b = np.array([
        T[0] + z_known * d[1],
        T[1] - z_known * d[0],
        T[2],
    ])

    result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    return [float(result[0]), float(result[1]), z_known]


def round_nested(obj, decimals=6):
    if isinstance(obj, bool):
        return obj
    elif isinstance(obj, (float, np.floating)):
        return round(float(obj), decimals)
    elif isinstance(obj, (int, np.integer)):
        return int(obj)
    elif isinstance(obj, np.ndarray):
        return round_nested(obj.tolist(), decimals)
    elif isinstance(obj, list):
        return [round_nested(x, decimals) for x in obj]
    elif isinstance(obj, dict):
        return {k: round_nested(v, decimals) for k, v in obj.items()}
    return obj


def main():
    # 1. Parse faulty thruster configuration from ArduPilot .param file
    params = parse_param_file("/app/config/frame.param")
    faulty_thrusters = extract_thrusters_from_params(params)

    # 2. Parse vehicle mass/inertia from URDF XML
    mass, inertia = parse_urdf("/app/config/vehicle.urdf")

    # 3. Decode binary calibration file for thrust coefficients
    thrust_coeffs = decode_calibration_binary("/app/calibration/thrust_cal.dat")

    # 4. Query SQLite database for session 3 telemetry
    pwm_cmds, accels = query_telemetry("/app/telemetry/flight_test.db", session_id=3)
    # pwm_cmds: Nx8 (PWM us), accels: Nx6 (linear + angular acceleration)

    # 5. Convert PWM to normalized commands, then to forces using calibration
    norm_cmds = (pwm_cmds - 1500.0) / 400.0
    coeffs_array = np.array([thrust_coeffs[i+1] for i in range(8)])
    forces = norm_cmds * coeffs_array  # Nx8 forces in Newtons

    # 6. Build mass matrix
    M = build_mass_matrix(mass, inertia)

    # 7. Convert accelerations to wrenches: W = M @ a for each timestep
    wrenches = np.array([M @ a for a in accels])  # Nx6

    # 8. System identification: B_true = W^T @ pinv(F^T)
    F = forces.T   # 8xN
    W = wrenches.T  # 6xN
    B_true = W @ np.linalg.pinv(F)  # 6x8

    # 9. Compute faulty allocation matrix from param file
    B_faulty = build_allocation_matrix(faulty_thrusters)

    # 10. Identify faults by comparing columns
    faults = []
    corrected_thrusters = []

    for i, t in enumerate(faulty_thrusters):
        col_true = B_true[:, i]
        col_faulty = B_faulty[:, i]

        true_dir = col_true[0:3]
        faulty_dir = col_faulty[0:3]
        true_torque = col_true[3:6]
        faulty_torque = col_faulty[3:6]

        # Normalize recovered direction to unit vector
        true_dir_unit = true_dir / np.linalg.norm(true_dir)

        dir_mismatch = not np.allclose(true_dir_unit, faulty_dir, atol=0.02)
        torque_mismatch = not np.allclose(true_torque, faulty_torque, atol=0.02)

        if dir_mismatch:
            correct_dir = true_dir_unit.tolist()
            faults.append({
                "thruster_id": t["id"],
                "field": "direction",
                "incorrect": t["direction"],
                "correct": [round(x, 7) for x in correct_dir],
            })
            corrected_t = dict(t)
            corrected_t["direction"] = correct_dir
            corrected_thrusters.append(corrected_t)
        elif torque_mismatch:
            z_known = t["position"][2]
            correct_pos = recover_position_from_torque(
                t["direction"], true_torque, z_known
            )
            faults.append({
                "thruster_id": t["id"],
                "field": "position",
                "incorrect": t["position"],
                "correct": [round(x, 7) for x in correct_pos],
            })
            corrected_t = dict(t)
            corrected_t["position"] = correct_pos
            corrected_thrusters.append(corrected_t)
        else:
            corrected_thrusters.append(dict(t))

    # 11. Build corrected allocation matrix
    B_corrected = build_allocation_matrix(corrected_thrusters)

    # 12. Assemble output
    diagnosis = {
        "faults": faults,
        "corrected_allocation_matrix": B_corrected.tolist(),
        "original_allocation_matrix": B_faulty.tolist(),
        "corrected_condition_number": float(np.linalg.cond(B_corrected)),
        "original_condition_number": float(np.linalg.cond(B_faulty)),
        "corrected_rank": int(np.linalg.matrix_rank(B_corrected)),
        "controllability_restored": bool(np.linalg.matrix_rank(B_corrected) == 6),
    }

    diagnosis = round_nested(diagnosis)

    with open("/app/diagnosis.json", "w") as f:
        json.dump(diagnosis, f, indent=2)

    print(f"Diagnosis complete: {len(faults)} faults found")
    for fault in faults:
        print(f"  Thruster {fault['thruster_id']}: {fault['field']} error")
    print(f"Corrected rank: {diagnosis['corrected_rank']}")
    print(f"Controllability restored: {diagnosis['controllability_restored']}")


if __name__ == "__main__":
    main()
