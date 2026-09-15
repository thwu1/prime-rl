#!/usr/bin/env python3
"""Nav2 configuration parameter validation tool.
Checks for common configuration errors in Nav2 parameter files.

Usage: python3 validate_nav2.py <params.yaml> <robot_spec.json>
"""

import sys
import yaml
import json


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def get_nested(d, *keys, default=None):
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k, default)
        if current is default:
            return default
    return current


def validate(cfg, spec):
    results = []

    fp = get_nested(cfg, "controller_server", "ros__parameters", "FollowPath", default={})
    cp = get_nested(cfg, "controller_server", "ros__parameters", default={})
    lc = get_nested(cfg, "local_costmap", "local_costmap", "ros__parameters", default={})
    gc = get_nested(cfg, "global_costmap", "global_costmap", "ros__parameters", default={})
    vs = get_nested(cfg, "velocity_smoother", "ros__parameters", default={})

    # --- Check 1: Controller frequency ---
    ctrl_freq = cp.get("controller_frequency", 20.0)
    if ctrl_freq > 15.0:
        results.append(("FAIL", "controller_frequency",
            f"controller_frequency={ctrl_freq}Hz exceeds recommended maximum of 15Hz. "
            f"High controller rates cause excessive CPU load and may introduce timing "
            f"jitter on resource-constrained platforms. Recommend reducing to 10-15Hz."))
    else:
        results.append(("PASS", "controller_frequency",
            f"controller_frequency={ctrl_freq}Hz within acceptable range"))

    # --- Check 2: Prediction horizon vs costmap ---
    time_steps = fp.get("time_steps", 56)
    model_dt = fp.get("model_dt", 0.05)
    vx_max = fp.get("vx_max", 0.5)
    prediction_dist = time_steps * model_dt * vx_max
    costmap_width = lc.get("width", 3)
    costmap_radius = costmap_width / 2.0
    if prediction_dist > costmap_radius:
        results.append(("FAIL", "prediction_horizon",
            f"Prediction distance ({time_steps}*{model_dt}*{vx_max}="
            f"{prediction_dist:.2f}m) exceeds local costmap radius "
            f"({costmap_width}/2={costmap_radius:.2f}m)"))
    else:
        results.append(("PASS", "prediction_horizon",
            f"Prediction distance {prediction_dist:.2f}m within costmap {costmap_radius:.2f}m"))

    # --- Check 3: Motion model compatibility ---
    motion_model = fp.get("motion_model", "")
    drive_type = spec.get("drive_type", "")
    if drive_type == "differential" and "diff" not in motion_model.lower():
        results.append(("FAIL", "motion_model",
            f"motion_model='{motion_model}' incompatible with {drive_type} drive robot"))
    else:
        results.append(("PASS", "motion_model",
            f"motion_model='{motion_model}' compatible with {drive_type} drive"))

    # --- Check 4: Velocity smoother limits ---
    vs_max = vs.get("max_velocity", [0, 0, 0])
    if vs_max[0] < vx_max:
        results.append(("FAIL", "velocity_smoother_linear",
            f"Smoother max_velocity[0]={vs_max[0]} clips controller vx_max={vx_max}"))
    else:
        results.append(("PASS", "velocity_smoother_linear",
            f"Smoother linear limit {vs_max[0]} >= controller {vx_max}"))

    wz_max = fp.get("wz_max", 1.9)
    if vs_max[2] >= wz_max:
        results.append(("FAIL", "velocity_smoother_angular",
            f"Smoother max_velocity[2]={vs_max[2]} exceeds MPPI wz_max={wz_max} — "
            f"wasteful headroom, reduce to match controller limit"))
    else:
        results.append(("PASS", "velocity_smoother_angular",
            f"Smoother angular limit {vs_max[2]} within controller range {wz_max}"))

    # --- Check 5: Raytrace vs obstacle range ---
    voxel = lc.get("voxel_layer", {})
    scan = voxel.get("scan", {})
    raytrace = scan.get("raytrace_max_range", 3.0)
    obstacle = scan.get("obstacle_max_range", 2.5)
    if raytrace < obstacle:
        results.append(("FAIL", "raytrace_range",
            f"raytrace_max_range={raytrace} < obstacle_max_range={obstacle} — "
            f"obstacles beyond raytrace range will never be cleared"))
    else:
        results.append(("PASS", "raytrace_range",
            f"Raytrace range {raytrace} >= obstacle range {obstacle}"))

    # --- Check 6: Inflation radius hierarchy ---
    local_infl = get_nested(lc, "inflation_layer", "inflation_radius", default=0.55)
    global_infl = get_nested(gc, "inflation_layer", "inflation_radius", default=0.55)
    if global_infl >= local_infl:
        results.append(("PASS", "inflation_radius",
            f"Global inflation ({global_infl}m) >= local ({local_infl}m) — "
            f"correct costmap hierarchy ensures planner paths respect controller margins"))
    else:
        results.append(("FAIL", "inflation_radius",
            f"Global inflation ({global_infl}m) < local ({local_infl}m) — "
            f"inverted hierarchy causes planner to generate overly aggressive paths"))

    # --- Check 7: Robot radius consistency ---
    local_rr = lc.get("robot_radius", 0.22)
    global_rr = gc.get("robot_radius", 0.22)
    spec_rr = spec.get("robot_radius_m", 0.22)
    if abs(local_rr - global_rr) > 0.01:
        results.append(("FAIL", "robot_radius",
            f"robot_radius mismatch: local={local_rr}m, global={global_rr}m "
            f"(spec={spec_rr}m)"))
    else:
        results.append(("PASS", "robot_radius",
            f"robot_radius consistent at {local_rr}m (spec={spec_rr}m)"))

    # --- Check 8: Global costmap obstacle plugin ---
    gc_plugins = gc.get("plugins", [])
    has_obstacle = any("obstacle" in p.lower() or "voxel" in p.lower() for p in gc_plugins)
    if "obstacle_layer" in gc and not has_obstacle:
        results.append(("FAIL", "global_obstacle_plugin",
            f"obstacle_layer configured but not in plugins list {gc_plugins}"))
    else:
        results.append(("PASS", "global_obstacle_plugin",
            f"Global costmap plugin list consistent"))

    return results


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <params.yaml> <robot_spec.json>")
        sys.exit(1)

    cfg = load_yaml(sys.argv[1])
    spec = load_json(sys.argv[2])

    results = validate(cfg, spec)

    print("=" * 65)
    print("  Nav2 Configuration Validation Report")
    print("=" * 65)

    fails = 0
    passes = 0
    for status, name, detail in results:
        marker = "\u2713" if status == "PASS" else "\u2717"
        print(f"  [{marker}] {name}: {detail}")
        if status == "FAIL":
            fails += 1
        else:
            passes += 1

    print("-" * 65)
    print(f"  Summary: {passes} passed, {fails} failed")
    if fails > 0:
        print("  Configuration has issues — address FAIL items above.")
    else:
        print("  Configuration appears valid.")
    print("=" * 65)


if __name__ == "__main__":
    main()
