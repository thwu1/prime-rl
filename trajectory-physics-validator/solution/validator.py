#!/usr/bin/env python3
"""Physics trajectory validator — reference implementation.

Reads HDF5 trajectory files, analyses physical plausibility using thresholds
from /app/config.toml, writes per-file JSON reports, SQLite database, and
gnuplot phase-space diagnostic plots.
"""

import json
import math
import os
import sqlite3
import subprocess
import tomllib
from glob import glob

import h5py

DATA_DIR = "/app/data"


# ── config ────────────────────────────────────────────────────────────────

def load_config(path="/app/config.toml"):
    with open(path, "rb") as f:
        return tomllib.load(f)


# ── math helpers ──────────────────────────────────────────────────────────

def _mag(v):
    return math.sqrt(sum(c * c for c in v))


def _dot(a, b):
    return sum(ai * bi for ai, bi in zip(a, b))


def _mat_mul_33(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def _mat_vec_3(M, v):
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]


def _mat_T(M):
    return [[M[j][i] for j in range(3)] for i in range(3)]


def _quat_to_rotmat(q):
    """Quaternion [w,x,y,z] → 3x3 rotation matrix (body→world)."""
    w, x, y, z = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ]


# ── HDF5 reader ──────────────────────────────────────────────────────────

def read_hdf5(filepath):
    data = {}
    with h5py.File(filepath, "r") as f:
        data["dt"] = float(f.attrs["dt"])
        data["floor_z"] = float(f.attrs.get("floor_z", 0.0))
        data["gravity"] = f["gravity"][:].tolist()

        data["bodies"] = []
        for name in f:
            if name == "gravity":
                continue
            g = f[name]
            if not isinstance(g, h5py.Group):
                continue
            st = g.attrs["shape_type"]
            if isinstance(st, bytes):
                st = st.decode("utf-8")
            body = {
                "name": name,
                "mass": float(g.attrs["mass"]),
                "shape_type": st,
                "shape_params": g["shape_params"][:].tolist(),
                "inertia_tensor": g["inertia_tensor"][:].tolist(),
                "positions": g["positions"][:].tolist(),
                "quaternions": g["quaternions"][:].tolist(),
                "velocities": g["velocities"][:].tolist(),
                "angular_velocities": g["angular_velocities"][:].tolist(),
            }
            data["bodies"].append(body)

    data["bodies"].sort(key=lambda b: b["name"])
    return data


# ── world-frame inertia tensor ───────────────────────────────────────────

def _inertia_world(body, frame):
    """I_world = R(q) · I_body · R(q)^T"""
    q = body["quaternions"][frame]
    R = _quat_to_rotmat(q)
    I_body = body["inertia_tensor"]
    return _mat_mul_33(_mat_mul_33(R, I_body), _mat_T(R))


# ── per-frame energy ─────────────────────────────────────────────────────

def _kinetic_energy(body, frame):
    m = body["mass"]
    v = body["velocities"][frame]
    w = body["angular_velocities"][frame]
    I_w = _inertia_world(body, frame)
    ke_trans = 0.5 * m * _dot(v, v)
    Iw = _mat_vec_3(I_w, w)
    ke_rot = 0.5 * _dot(w, Iw)
    return ke_trans + ke_rot


def _potential_energy(body, frame, gravity):
    m = body["mass"]
    r = body["positions"][frame]
    return -m * _dot(gravity, r)


def _total_system_energy(data, frame):
    g = data["gravity"]
    return sum(
        _kinetic_energy(b, frame) + _potential_energy(b, frame, g)
        for b in data["bodies"]
    )


# ── collision detection ──────────────────────────────────────────────────

def _velocity_jumps(body, threshold):
    vels = body["velocities"]
    jumps = set()
    for i in range(1, len(vels)):
        dv = [vels[i][j] - vels[i - 1][j] for j in range(3)]
        if _mag(dv) > threshold:
            jumps.add(i)
    return jumps


def _all_collision_frames(data, threshold):
    s = set()
    for b in data["bodies"]:
        s |= _velocity_jumps(b, threshold)
    return sorted(s)


def _collision_neighbourhood(data, threshold, radius=2):
    collisions = _all_collision_frames(data, threshold)
    n = len(data["bodies"][0]["positions"])
    exclude = set()
    for cf in collisions:
        for k in range(max(0, cf - radius), min(n, cf + radius + 1)):
            exclude.add(k)
    return exclude


# ── checks ───────────────────────────────────────────────────────────────

def check_energy(data, cfg):
    tol = cfg["thresholds"]["energy_relative"]
    vd = cfg["thresholds"]["velocity_discontinuity"]
    n = len(data["bodies"][0]["positions"])
    energies = [_total_system_energy(data, f) for f in range(n)]
    collisions = _all_collision_frames(data, vd)
    violations = []

    boundaries = sorted(set([0] + collisions + [n]))
    for si in range(len(boundaries) - 1):
        s, e = boundaries[si], boundaries[si + 1]
        if e - s < 3:
            continue
        e_ref = energies[s]
        for f in range(s + 1, e):
            denom = abs(e_ref) if abs(e_ref) > 1e-10 else 1.0
            rel = abs(energies[f] - e_ref) / denom
            if rel > tol:
                violations.append({
                    "frame": f,
                    "expected_energy": round(e_ref, 6),
                    "actual_energy": round(energies[f], 6),
                    "relative_change": round(rel, 6),
                })
                break

    for cf in collisions:
        if cf == 0 or cf >= n:
            continue
        e_before = energies[cf - 1]
        e_after = energies[cf]
        if e_after > e_before * (1 + tol):
            denom = abs(e_before) if abs(e_before) > 1e-10 else 1.0
            violations.append({
                "frame": cf,
                "type": "energy_gain_at_collision",
                "energy_before": round(e_before, 6),
                "energy_after": round(e_after, 6),
                "gain_ratio": round(e_after / denom, 6),
            })

    return violations


def check_momentum(data, cfg):
    if len(data["bodies"]) < 2:
        return []
    tol = cfg["thresholds"]["momentum_absolute"]
    vd = cfg["thresholds"]["velocity_discontinuity"]
    collisions = _all_collision_frames(data, vd)
    n = len(data["bodies"][0]["positions"])
    violations = []
    for cf in collisions:
        if cf == 0 or cf >= n:
            continue
        p_before = [0.0, 0.0, 0.0]
        p_after = [0.0, 0.0, 0.0]
        for b in data["bodies"]:
            m = b["mass"]
            vb = b["velocities"][cf - 1]
            va = b["velocities"][cf]
            for j in range(3):
                p_before[j] += m * vb[j]
                p_after[j] += m * va[j]
        dp = [p_after[j] - p_before[j] for j in range(3)]
        dp_mag = _mag(dp)
        if dp_mag > tol:
            violations.append({
                "frame": cf,
                "momentum_before": [round(p, 6) for p in p_before],
                "momentum_after": [round(p, 6) for p in p_after],
                "momentum_change": round(dp_mag, 6),
            })
    return violations


def check_interpenetration(data, cfg):
    bodies = data["bodies"]
    if len(bodies) < 2:
        return []
    tol = cfg["thresholds"]["overlap_distance"]
    n = len(bodies[0]["positions"])
    results = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            bi, bj = bodies[i], bodies[j]
            ri = bi["shape_params"][0]
            rj = bj["shape_params"][0]
            min_dist = ri + rj
            for f in range(n):
                pi = bi["positions"][f]
                pj = bj["positions"][f]
                dist = _mag([pi[k] - pj[k] for k in range(3)])
                if dist < min_dist - tol:
                    results.append({
                        "bodies": [bi["name"], bj["name"]],
                        "frame": f,
                        "distance": round(dist, 6),
                        "min_allowed": round(min_dist, 6),
                        "overlap": round(min_dist - dist, 6),
                    })
    return results


def check_jitter(data, cfg):
    gravity = data["gravity"]
    dt = data["dt"]
    rms_threshold = cfg["thresholds"]["accel_rms_noise"]
    vd = cfg["thresholds"]["velocity_discontinuity"]
    exclude = _collision_neighbourhood(data, vd)

    for b in data["bodies"]:
        positions = b["positions"]
        n = len(positions)
        dev_sq = []
        for f in range(1, n - 1):
            if f in exclude:
                continue
            for axis in range(3):
                accel = (positions[f + 1][axis]
                         - 2.0 * positions[f][axis]
                         + positions[f - 1][axis]) / (dt * dt)
                dev = accel - gravity[axis]
                dev_sq.append(dev * dev)
        if dev_sq:
            rms = math.sqrt(sum(dev_sq) / len(dev_sq))
            if rms > rms_threshold:
                return True
    return False


def check_kinematic_consistency(data, cfg):
    dt = data["dt"]
    tol = cfg["thresholds"]["velocity_consistency"]
    vd = cfg["thresholds"]["velocity_discontinuity"]
    exclude = _collision_neighbourhood(data, vd)
    violations = []

    for b in data["bodies"]:
        pos = b["positions"]
        vel = b["velocities"]
        n = len(pos)
        count = 0
        for f in range(1, n - 1):
            if f in exclude:
                continue
            v_est = [(pos[f + 1][j] - pos[f - 1][j]) / (2.0 * dt) for j in range(3)]
            v_rep = vel[f]
            diff = [v_rep[j] - v_est[j] for j in range(3)]
            diff_mag = _mag(diff)
            v_mag = _mag(v_est)
            rel_diff = diff_mag / v_mag if v_mag > 1e-6 else diff_mag
            if rel_diff > tol:
                count += 1
                if count <= 10:
                    violations.append({
                        "frame": f,
                        "body": b["name"],
                        "estimated_velocity": [round(v, 4) for v in v_est],
                        "reported_velocity": [round(v, 4) for v in v_rep],
                        "relative_error": round(rel_diff, 6),
                    })
    return violations


def check_angular_momentum(data, cfg):
    """Check world-frame angular momentum conservation for torque-free segments."""
    tol = cfg["thresholds"]["angular_momentum_relative"]
    vd = cfg["thresholds"]["velocity_discontinuity"]
    exclude = _collision_neighbourhood(data, vd)
    violations = []

    for b in data["bodies"]:
        n = len(b["angular_velocities"])
        count = 0
        for f in range(1, n):
            if f in exclude or (f - 1) in exclude:
                continue

            I_prev = _inertia_world(b, f - 1)
            I_curr = _inertia_world(b, f)
            w_prev = b["angular_velocities"][f - 1]
            w_curr = b["angular_velocities"][f]

            L_prev = _mat_vec_3(I_prev, w_prev)
            L_curr = _mat_vec_3(I_curr, w_curr)

            dL = [L_curr[i] - L_prev[i] for i in range(3)]
            dL_mag = _mag(dL)
            L_mag = _mag(L_prev)
            if L_mag > 1e-10 and dL_mag / L_mag > tol:
                count += 1
                if count <= 10:
                    violations.append({
                        "frame": f,
                        "body": b["name"],
                        "angular_momentum_change": round(dL_mag, 6),
                        "relative_change": round(dL_mag / L_mag, 6),
                    })
    return violations


# ── scoring ──────────────────────────────────────────────────────────────

def compute_score(energy_v, momentum_v, interpen, jitter, kinematic_v,
                  angmom_v, cfg):
    s = cfg["scoring"]
    score = 100.0
    if energy_v:
        score -= s["energy_penalty"]
    if momentum_v:
        score -= s["momentum_penalty"]
    if interpen:
        score -= min(len(interpen) * s["interpenetration_per_frame"],
                     s["interpenetration_cap"])
    if jitter:
        score -= s["jitter_penalty"]
    if kinematic_v:
        score -= s["kinematic_penalty"]
    if angmom_v:
        score -= s["angular_momentum_penalty"]
    return max(0.0, round(score, 2))


# ── gnuplot phase-space plots ────────────────────────────────────────────

def generate_phase_plot(stem, body, plots_dir):
    """Generate a position-vs-velocity phase-space PNG using gnuplot."""
    name = body["name"]
    positions = body["positions"]
    velocities = body["velocities"]

    # Find dominant motion axis (largest position range)
    max_range = 0.0
    dom_axis = 0
    for axis in range(3):
        vals = [p[axis] for p in positions]
        r = max(vals) - min(vals)
        if r > max_range:
            max_range = r
            dom_axis = axis

    axis_labels = ["X", "Y", "Z"]

    # Write data file for gnuplot
    data_file = os.path.join(plots_dir, f"{stem}_{name}.dat")
    with open(data_file, "w") as fh:
        for i in range(len(positions)):
            fh.write(f"{positions[i][dom_axis]} {velocities[i][dom_axis]}\n")

    # Write gnuplot script
    png_file = os.path.join(plots_dir, f"{stem}_{name}.png")
    script_file = os.path.join(plots_dir, f"{stem}_{name}.gp")
    with open(script_file, "w") as fh:
        fh.write(f'set terminal pngcairo size 800,600\n')
        fh.write(f'set output "{png_file}"\n')
        fh.write(f'set xlabel "Position {axis_labels[dom_axis]} (m)"\n')
        fh.write(f'set ylabel "Velocity {axis_labels[dom_axis]} (m/s)"\n')
        fh.write(f'set title "Phase Space: {stem} / {name}"\n')
        fh.write(f'set grid\n')
        fh.write(f'plot "{data_file}" using 1:2 with lines lw 1.5 notitle\n')

    subprocess.run(["gnuplot", script_file], check=True,
                   capture_output=True, timeout=30)


# ── SQLite output ────────────────────────────────────────────────────────

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scenarios "
        "(name TEXT PRIMARY KEY, plausibility_score REAL, total_anomalies INTEGER)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS anomalies "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_name TEXT "
        "REFERENCES scenarios(name), anomaly_type TEXT, frame INTEGER, "
        "details TEXT)"
    )
    conn.commit()
    return conn


def write_db(conn, stem, report):
    total = 0
    anomalies_data = report["anomalies"]
    rows = []
    for atype, val in anomalies_data.items():
        if atype == "jitter_detected":
            if val:
                total += 1
                rows.append((stem, "jitter", -1, json.dumps({"detected": True})))
        elif isinstance(val, list):
            total += len(val)
            for entry in val:
                rows.append((
                    stem, atype,
                    entry.get("frame", -1),
                    json.dumps(entry),
                ))

    conn.execute(
        "INSERT OR REPLACE INTO scenarios VALUES (?, ?, ?)",
        (stem, report["plausibility_score"], total),
    )
    for row in rows:
        conn.execute(
            "INSERT INTO anomalies (scenario_name, anomaly_type, frame, details) "
            "VALUES (?, ?, ?, ?)",
            row,
        )
    conn.commit()


# ── main ─────────────────────────────────────────────────────────────────

def validate(filepath, cfg):
    data = read_hdf5(filepath)
    ev = check_energy(data, cfg)
    mv = check_momentum(data, cfg)
    ip = check_interpenetration(data, cfg)
    jt = check_jitter(data, cfg)
    kv = check_kinematic_consistency(data, cfg)
    av = check_angular_momentum(data, cfg)
    return data, {
        "plausibility_score": compute_score(ev, mv, ip, jt, kv, av, cfg),
        "anomalies": {
            "energy_violations": ev,
            "momentum_violations": mv,
            "interpenetrations": ip,
            "kinematic_violations": kv,
            "angular_momentum_violations": av,
            "jitter_detected": jt,
        },
    }


def main():
    cfg = load_config()
    reports_dir = cfg["output"]["reports_dir"]
    db_path = cfg["output"]["database_path"]
    plots_dir = cfg["output"]["plots_dir"]

    os.makedirs(reports_dir, exist_ok=True)
    os.makedirs(plots_dir, exist_ok=True)
    conn = init_db(db_path)

    for fp in sorted(glob(os.path.join(DATA_DIR, "*.h5"))):
        stem = os.path.splitext(os.path.basename(fp))[0]
        data, report = validate(fp, cfg)

        out = os.path.join(reports_dir, f"{stem}_report.json")
        with open(out, "w") as fh:
            json.dump(report, fh, indent=2)

        write_db(conn, stem, report)

        for body in data["bodies"]:
            generate_phase_plot(stem, body, plots_dir)

        print(f"{stem:30s}  score={report['plausibility_score']}")

    conn.close()


if __name__ == "__main__":
    main()
