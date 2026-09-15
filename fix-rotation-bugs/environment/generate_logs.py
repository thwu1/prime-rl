#!/usr/bin/env python3
"""Generate NDJSON pipeline error logs by testing configured backends.
Run during Docker build, then deleted. Not visible to the solver.
"""
import json
import sys
import os
import sqlite3
import importlib
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/app')
DB_PATH = "/app/rotations.db"
THRESHOLD = 1e-6


def quat_err(qp, qe):
    qp = np.asarray(qp, dtype=float)
    qe = np.asarray(qe, dtype=float)
    qp = qp / np.linalg.norm(qp)
    qe = qe / np.linalg.norm(qe)
    return min(np.linalg.norm(qp - qe), np.linalg.norm(qp + qe))


def mat_err(Rp, Re):
    return np.linalg.norm(np.asarray(Rp) - np.asarray(Re))


def main():
    with open('/app/pipeline.json') as f:
        config = json.load(f)

    backends = config['backends']
    chains = config['conversion_chains']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    logs = []
    t0 = datetime(2024, 11, 15, 8, 0, 0)
    idx = 0

    for func_name, lib_name in backends.items():
        lib = importlib.import_module(f"lib_{lib_name}")

        if func_name == "quaternion_to_matrix":
            for row in c.execute(
                "SELECT id, category, qw,qx,qy,qz, "
                "r00,r01,r02,r10,r11,r12,r20,r21,r22 "
                "FROM test_rotations"
            ).fetchall():
                tid, cat = row[0], row[1]
                q = np.array(row[2:6])
                Re = np.array(row[6:15]).reshape(3, 3)
                try:
                    err = float(mat_err(lib.quaternion_to_matrix(q), Re))
                except Exception:
                    err = 999.0
                ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
                logs.append({
                    "ts": ts, "run_id": "run_4721",
                    "func": func_name, "backend": lib_name,
                    "test_id": tid, "category": cat,
                    "error": round(err, 10),
                    "status": "FAIL" if err >= THRESHOLD else "PASS"
                })
                idx += 1

        elif func_name == "matrix_to_quaternion":
            for row in c.execute(
                "SELECT id, category, qw,qx,qy,qz, "
                "r00,r01,r02,r10,r11,r12,r20,r21,r22 "
                "FROM test_rotations"
            ).fetchall():
                tid, cat = row[0], row[1]
                qe = np.array(row[2:6])
                R = np.array(row[6:15]).reshape(3, 3)
                try:
                    err = float(quat_err(lib.matrix_to_quaternion(R), qe))
                except Exception:
                    err = 999.0
                ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
                logs.append({
                    "ts": ts, "run_id": "run_4721",
                    "func": func_name, "backend": lib_name,
                    "test_id": tid, "category": cat,
                    "error": round(err, 10),
                    "status": "FAIL" if err >= THRESHOLD else "PASS"
                })
                idx += 1

        elif func_name == "axis_angle_to_matrix":
            for row in c.execute(
                "SELECT id, category, ax,ay,az, "
                "r00,r01,r02,r10,r11,r12,r20,r21,r22 "
                "FROM test_rotations"
            ).fetchall():
                tid, cat = row[0], row[1]
                aa = np.array(row[2:5])
                Re = np.array(row[5:14]).reshape(3, 3)
                try:
                    err = float(mat_err(lib.axis_angle_to_matrix(aa), Re))
                except Exception:
                    err = 999.0
                ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
                logs.append({
                    "ts": ts, "run_id": "run_4721",
                    "func": func_name, "backend": lib_name,
                    "test_id": tid, "category": cat,
                    "error": round(err, 10),
                    "status": "FAIL" if err >= THRESHOLD else "PASS"
                })
                idx += 1

        elif func_name == "matrix_to_euler_angles":
            for row in c.execute(
                "SELECT id, category, "
                "r00,r01,r02,r10,r11,r12,r20,r21,r22, "
                "ex,ey,ez FROM test_rotations"
            ).fetchall():
                tid, cat = row[0], row[1]
                R = np.array(row[2:11]).reshape(3, 3)
                ee = np.array(row[11:14])
                try:
                    err = float(np.linalg.norm(
                        lib.matrix_to_euler_angles(R, "XYZ") - ee))
                except Exception:
                    err = 999.0
                ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
                logs.append({
                    "ts": ts, "run_id": "run_4721",
                    "func": func_name, "backend": lib_name,
                    "test_id": tid, "category": cat,
                    "error": round(err, 10),
                    "status": "FAIL" if err >= THRESHOLD else "PASS"
                })
                idx += 1

        elif func_name == "geodesic_distance":
            for row in c.execute(
                "SELECT id, category, "
                "a00,a01,a02,a10,a11,a12,a20,a21,a22, "
                "b00,b01,b02,b10,b11,b12,b20,b21,b22, "
                "expected FROM test_geodesic"
            ).fetchall():
                tid, cat = row[0], row[1]
                R1 = np.array(row[2:11]).reshape(3, 3)
                R2 = np.array(row[11:20]).reshape(3, 3)
                exp = row[20]
                try:
                    err = float(abs(lib.geodesic_distance(R1, R2) - exp))
                except Exception:
                    err = 999.0
                ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
                logs.append({
                    "ts": ts, "run_id": "run_4721",
                    "func": func_name, "backend": lib_name,
                    "test_id": tid, "category": cat,
                    "error": round(err, 10),
                    "status": "FAIL" if err >= THRESHOLD else "PASS"
                })
                idx += 1

        elif func_name == "slerp":
            for row in c.execute(
                "SELECT id, category, "
                "q0w,q0x,q0y,q0z, q1w,q1x,q1y,q1z, "
                "t, ew,ex,ey,ez FROM test_slerp"
            ).fetchall():
                tid, cat = row[0], row[1]
                q0 = np.array(row[2:6])
                q1 = np.array(row[6:10])
                t_val = row[10]
                qe = np.array(row[11:15])
                try:
                    err = float(quat_err(lib.slerp(q0, q1, t_val), qe))
                except Exception:
                    err = 999.0
                ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
                logs.append({
                    "ts": ts, "run_id": "run_4721",
                    "func": func_name, "backend": lib_name,
                    "test_id": tid, "category": cat,
                    "error": round(err, 10),
                    "status": "FAIL" if err >= THRESHOLD else "PASS"
                })
                idx += 1

    # Chain-level summary entries
    for chain_name, chain_info in chains.items():
        steps = chain_info['steps']
        chain_funcs = set(steps)
        chain_entries = [e for e in logs if e.get('func') in chain_funcs]
        fails = sum(1 for e in chain_entries if e['status'] == 'FAIL')
        total = len(chain_entries)
        ts = (t0 + timedelta(milliseconds=idx * 50)).isoformat() + "Z"
        logs.append({
            "ts": ts, "run_id": "run_4721",
            "type": "chain_summary", "chain": chain_name,
            "steps": steps,
            "total_tests": total, "failures": fails,
            "failure_rate": round(fails / max(total, 1), 4),
            "status": "DEGRADED" if fails > 0 else "OK"
        })
        idx += 1

    os.makedirs('/app/logs', exist_ok=True)
    with open('/app/logs/pipeline_errors.ndjson', 'w') as f:
        for entry in logs:
            f.write(json.dumps(entry, separators=(',', ':')) + '\n')

    print(f"Generated {len(logs)} log entries to /app/logs/pipeline_errors.ndjson")
    conn.close()


if __name__ == "__main__":
    main()
