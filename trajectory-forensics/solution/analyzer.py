#!/usr/bin/env python3
"""Physics Trajectory Forensics - Oracle Solver"""

import sys
import json
import h5py
import numpy as np
import tomllib


def load_config(path="/app/config.toml"):
    with open(path, "rb") as f:
        return tomllib.load(f)


def h5str(val):
    return val.decode("utf-8") if isinstance(val, bytes) else str(val)


def load_trajectory(path):
    with h5py.File(path, "r") as f:
        scenario_id = h5str(f.attrs["scenario_id"])
        dt = float(f.attrs["dt"])
        noise_sigma_vel = float(f.attrs["noise_sigma_vel"])
        body_order = json.loads(h5str(f.attrs["body_order"]))

        g_decl = float(f["declared"].attrs["gravity"])
        friction_decl = float(f["declared"].attrs["friction"])
        cor_decl = float(f["declared"].attrs["cor"])

        bodies = {}
        for bid in body_order:
            bg = f[f"declared/bodies/{bid}"]
            bodies[bid] = {
                "mass": float(bg.attrs["mass"]),
                "radius": float(bg.attrs["radius"]),
            }

        times = f["trajectory/time"][:]
        trajectories = {}
        for bid in body_order:
            trajectories[bid] = {
                "pos": f[f"trajectory/{bid}/position"][:],
                "vel": f[f"trajectory/{bid}/velocity"][:],
            }

    return {
        "scenario_id": scenario_id,
        "dt": dt,
        "noise_sigma_vel": noise_sigma_vel,
        "body_order": body_order,
        "declared": {"gravity": g_decl, "friction": friction_decl, "cor": cor_decl},
        "bodies": bodies,
        "times": times,
        "trajectories": trajectories,
    }


def find_velocity_jumps(vel, noise_sigma, factor=10):
    dv = np.diff(vel, axis=0)
    dv_mag = np.sqrt(np.sum(dv ** 2, axis=1))
    threshold = max(factor * noise_sigma, 0.05)
    return np.where(dv_mag > threshold)[0]


def infer_gravity(data):
    """Infer gravitational acceleration from vertical velocity vs time.

    Only infers when there is significant vertical velocity variation
    (indicating gravitational acceleration, not just noise).
    """
    best_g = None
    best_r2 = -1.0

    for bid in data["body_order"]:
        vel = data["trajectories"][bid]["vel"]
        vy = vel[:, 1]
        t = data["times"]

        # Require significant vertical velocity range (well above noise)
        vy_range = np.max(vy) - np.min(vy)
        if vy_range < 0.5:
            continue

        # Segment at collision events
        jumps = find_velocity_jumps(vel, data["noise_sigma_vel"])

        if len(jumps) == 0:
            seg_t, seg_vy = t, vy
        else:
            first_jump = jumps[0]
            if first_jump < 20:
                continue
            seg_t, seg_vy = t[:first_jump], vy[:first_jump]

        if len(seg_t) < 20:
            continue

        # Check that the pre-collision segment itself shows variation
        seg_range = np.max(seg_vy) - np.min(seg_vy)
        if seg_range < 0.3:
            continue

        # OLS: vy = slope * t + intercept
        A = np.column_stack([seg_t, np.ones(len(seg_t))])
        result = np.linalg.lstsq(A, seg_vy, rcond=None)
        slope = result[0][0]

        predicted = A @ result[0]
        ss_res = np.sum((seg_vy - predicted) ** 2)
        ss_tot = np.sum((seg_vy - np.mean(seg_vy)) ** 2)

        if ss_tot < 1e-10:
            continue

        r2 = 1.0 - ss_res / ss_tot
        if r2 > best_r2 and r2 > 0.9:
            best_g = -slope
            best_r2 = r2

    return best_g


def detect_collision(data):
    """Detect collision between two bodies from simultaneous velocity jumps."""
    if len(data["body_order"]) < 2:
        return None

    bid1, bid2 = data["body_order"][0], data["body_order"][1]
    v1 = data["trajectories"][bid1]["vel"]
    v2 = data["trajectories"][bid2]["vel"]

    jumps1 = set(find_velocity_jumps(v1, data["noise_sigma_vel"]))
    jumps2 = set(find_velocity_jumps(v2, data["noise_sigma_vel"]))

    collision_idx = None
    for j1 in sorted(jumps1):
        for j2 in sorted(jumps2):
            if abs(j1 - j2) <= 2:
                collision_idx = min(j1, j2)
                break
        if collision_idx is not None:
            break

    if collision_idx is None:
        return None

    m1 = data["bodies"][bid1]["mass"]
    m2 = data["bodies"][bid2]["mass"]

    # Average over a window to reduce noise
    window = 5
    pre_s = max(0, collision_idx - window)
    pre_e = collision_idx
    post_s = collision_idx + 2
    post_e = min(len(v1), collision_idx + 2 + window)

    if pre_e <= pre_s or post_e <= post_s:
        return None

    return {
        "idx": collision_idx,
        "bid1": bid1, "bid2": bid2,
        "m1": m1, "m2": m2,
        "v1_pre": np.mean(v1[pre_s:pre_e], axis=0),
        "v1_post": np.mean(v1[post_s:post_e], axis=0),
        "v2_pre": np.mean(v2[pre_s:pre_e], axis=0),
        "v2_post": np.mean(v2[post_s:post_e], axis=0),
    }


def compute_cor(coll):
    """Compute coefficient of restitution along approach direction."""
    v_rel_pre = coll["v1_pre"] - coll["v2_pre"]
    approach_speed = np.linalg.norm(v_rel_pre)
    if approach_speed < 0.1:
        return None

    n = v_rel_pre / approach_speed

    v1n_pre = np.dot(coll["v1_pre"], n)
    v2n_pre = np.dot(coll["v2_pre"], n)
    v1n_post = np.dot(coll["v1_post"], n)
    v2n_post = np.dot(coll["v2_post"], n)

    approach = v1n_pre - v2n_pre
    separation = v2n_post - v1n_post
    if abs(approach) < 0.1:
        return None

    return separation / approach


def infer_mass_ratio(coll):
    """Infer mass ratio m1/m2 from impulse equality: m1*dv1 = -m2*dv2."""
    dv1 = coll["v1_post"] - coll["v1_pre"]
    dv2 = coll["v2_post"] - coll["v2_pre"]

    best_ratio = None
    best_mag = 0.0

    for dim in range(dv1.shape[0]):
        if abs(dv1[dim]) > 0.1:
            ratio = -dv2[dim] / dv1[dim]
            if abs(dv1[dim]) > best_mag and ratio > 0:
                best_ratio = ratio
                best_mag = abs(dv1[dim])

    return best_ratio


def check_momentum(coll):
    """Check momentum conservation using sum of individual momenta as scale."""
    m1, m2 = coll["m1"], coll["m2"]
    p_before = m1 * coll["v1_pre"] + m2 * coll["v2_pre"]
    p_after = m1 * coll["v1_post"] + m2 * coll["v2_post"]

    dp = np.linalg.norm(p_after - p_before)

    # Scale: average of sum-of-individual-momenta before and after
    scale = (
        m1 * np.linalg.norm(coll["v1_pre"])
        + m2 * np.linalg.norm(coll["v2_pre"])
        + m1 * np.linalg.norm(coll["v1_post"])
        + m2 * np.linalg.norm(coll["v2_post"])
    ) / 2.0

    if scale < 0.01:
        return dp, 0.0
    return dp, dp / scale


def check_energy(coll):
    """Check kinetic energy conservation at collision."""
    m1, m2 = coll["m1"], coll["m2"]
    ke_before = 0.5 * (m1 * np.sum(coll["v1_pre"] ** 2)
                       + m2 * np.sum(coll["v2_pre"] ** 2))
    ke_after = 0.5 * (m1 * np.sum(coll["v1_post"] ** 2)
                      + m2 * np.sum(coll["v2_post"] ** 2))

    if ke_before < 0.01:
        return ke_before, ke_after, 1.0
    return ke_before, ke_after, ke_after / ke_before


def infer_friction(data):
    """Infer friction coefficient from horizontal deceleration on a surface."""
    if len(data["body_order"]) != 1:
        return None

    bid = data["body_order"][0]
    vx = data["trajectories"][bid]["vel"][:, 0]
    t = data["times"]

    if abs(np.mean(vx[:5])) < 0.5:
        return None

    moving_mask = np.abs(vx) > 0.2
    if np.sum(moving_mask) < 20:
        return None

    t_mov = t[moving_mask]
    vx_mov = vx[moving_mask]

    A = np.column_stack([t_mov, np.ones(len(t_mov))])
    result = np.linalg.lstsq(A, vx_mov, rcond=None)
    slope = result[0][0]
    decel = abs(slope)

    g_decl = data["declared"]["gravity"]
    if g_decl < 0.1:
        return None

    return decel / g_decl


def compute_score(anomalies):
    """Compute plausibility score from anomaly severities."""
    score = 100.0
    for a in anomalies:
        if a["type"] == "gravity_anomaly":
            err = float(a["detail"].split("err=")[1])
            score -= min(50.0, err * 100.0)
        elif a["type"] == "momentum_violation":
            rel = float(a["detail"].split("relative=")[1])
            score -= min(100.0, rel * 200.0)
        elif a["type"] == "energy_violation":
            ratio = float(a["detail"].split("ratio=")[1])
            score -= min(100.0, abs(ratio - 1.0) * 150.0)
    return max(0.0, min(100.0, score))


def analyze(filepath):
    config = load_config()
    data = load_trajectory(filepath)

    thresholds = config["thresholds"]
    cls_config = config["classification"]

    anomalies = []
    inferred = {
        "gravity": None,
        "mass_ratios": None,
        "coefficient_of_restitution": None,
        "friction_coefficient": None,
    }

    # Gravity inference
    g = infer_gravity(data)
    if g is not None:
        inferred["gravity"] = round(g, 4)
        g_decl = data["declared"]["gravity"]
        if g_decl > 0.1:
            rel_err = abs(g - g_decl) / g_decl
            if rel_err > thresholds["gravity"]:
                anomalies.append({
                    "type": "gravity_anomaly",
                    "detail": f"declared={g_decl} inferred={round(g, 4)} err={round(rel_err, 4)}",
                })

    # Collision analysis
    coll = detect_collision(data)
    if coll is not None:
        ratio = infer_mass_ratio(coll)
        if ratio is not None:
            inferred["mass_ratios"] = {
                f"{coll['bid1']}/{coll['bid2']}": round(ratio, 4)
            }

        cor = compute_cor(coll)
        if cor is not None:
            inferred["coefficient_of_restitution"] = round(cor, 4)

        dp, dp_rel = check_momentum(coll)
        if dp_rel > thresholds["momentum"]:
            anomalies.append({
                "type": "momentum_violation",
                "detail": f"|dp|={round(dp, 4)} relative={round(dp_rel, 4)}",
            })

        ke_b, ke_a, ke_ratio = check_energy(coll)
        if abs(ke_ratio - 1.0) > thresholds["energy"]:
            anomalies.append({
                "type": "energy_violation",
                "detail": f"KE {round(ke_b, 4)}->{round(ke_a, 4)} ratio={round(ke_ratio, 4)}",
            })

    # Friction inference
    mu = infer_friction(data)
    if mu is not None:
        inferred["friction_coefficient"] = round(mu, 4)

    # Classification by priority
    classification = cls_config["default"]
    for prio in cls_config["priority"]:
        if any(a["type"] == prio for a in anomalies):
            classification = prio
            break

    score = compute_score(anomalies)

    report = {
        "scenario_id": data["scenario_id"],
        "classification": classification,
        "inferred_parameters": inferred,
        "anomalies": anomalies,
        "plausibility_score": round(score, 2),
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <trajectory.h5>", file=sys.stderr)
        sys.exit(1)
    analyze(sys.argv[1])
