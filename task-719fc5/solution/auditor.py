#!/usr/bin/env python3
"""
Nav2 Configuration Auditor — validates Nav2 params YAML files for
cross-component consistency, physical constraints, and architectural
correctness.

Usage: python3 nav2_auditor.py <config.yaml>
Output: JSON array of issue objects to stdout.
"""

import json
import sys

import yaml


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _get_nested(cfg, *keys, default=None):
    """Safely traverse nested dicts."""
    node = cfg
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
    return node


def audit(cfg):
    issues = []

    # Shorthand accessors
    local_params = _get_nested(cfg, "local_costmap", "local_costmap", "ros__parameters", default={})
    global_params = _get_nested(cfg, "global_costmap", "global_costmap", "ros__parameters", default={})
    ctrl = _get_nested(cfg, "controller_server", "ros__parameters", default={})
    bt_params = _get_nested(cfg, "bt_navigator", "ros__parameters", default={})
    planner_params = _get_nested(cfg, "planner_server", "ros__parameters", default={})
    vs_params = _get_nested(cfg, "velocity_smoother", "ros__parameters", default={})
    cm_params = _get_nested(cfg, "collision_monitor", "ros__parameters", default={})
    bs_params = _get_nested(cfg, "behavior_server", "ros__parameters", default={})

    # ---------------------------------------------------------------
    # Rule 1: Costmap plugin ordering
    # ---------------------------------------------------------------
    OBSTACLE_SOURCE_TYPES = {"voxel_layer", "obstacle_layer", "static_layer"}

    for name, params in [("local_costmap", local_params), ("global_costmap", global_params)]:
        plugins = params.get("plugins", [])
        source_indices = [i for i, p in enumerate(plugins) if p in OBSTACLE_SOURCE_TYPES]
        inflation_indices = [i for i, p in enumerate(plugins) if "inflation" in p.lower()]
        if source_indices and inflation_indices:
            if min(inflation_indices) < max(source_indices):
                issues.append({
                    "rule_id": "costmap_plugin_order",
                    "severity": "critical",
                    "component": name,
                    "description": (
                        f"In {name}, an inflation layer appears before obstacle source "
                        f"layers in the plugins list {plugins}. Costmap layers are "
                        f"applied in order; inflation applied before obstacles are added "
                        f"results in un-inflated obstacles. Move inflation_layer after "
                        f"all obstacle source layers."
                    ),
                })

    # ---------------------------------------------------------------
    # Rule 2: Motion model / plugin class mismatch
    # ---------------------------------------------------------------
    MOTION_MODEL_PLUGINS = {
        "diff_drive": "DiffDrive",
        "omni": "Omni",
        "ackermann": "Ackermann",
    }
    for key, val in ctrl.items():
        if not isinstance(val, dict) or "motion_model" not in val:
            continue
        mm = val["motion_model"]
        mm_cfg = val.get(mm, {})
        if isinstance(mm_cfg, dict):
            plugin = mm_cfg.get("plugin", "")
            expected_frag = MOTION_MODEL_PLUGINS.get(mm)
            if expected_frag and expected_frag not in plugin:
                issues.append({
                    "rule_id": "motion_model_plugin_mismatch",
                    "severity": "critical",
                    "component": "controller_server",
                    "description": (
                        f"Motion model is \"{mm}\" but the plugin loaded is "
                        f"\"{plugin}\". Expected a plugin containing "
                        f"\"{expected_frag}\" for the {mm} motion model."
                    ),
                })

    # ---------------------------------------------------------------
    # Rule 3: Robot radius mismatch between costmaps
    # ---------------------------------------------------------------
    local_rr = local_params.get("robot_radius")
    global_rr = global_params.get("robot_radius")
    if local_rr is not None and global_rr is not None and abs(local_rr - global_rr) > 0.001:
        issues.append({
            "rule_id": "robot_radius_mismatch",
            "severity": "error",
            "component": "costmaps",
            "description": (
                f"robot_radius differs between local_costmap ({local_rr}) and "
                f"global_costmap ({global_rr}). The same physical robot must "
                f"have a consistent radius in both costmaps."
            ),
        })

    # ---------------------------------------------------------------
    # Rule 4: Inflation radius < robot radius
    # ---------------------------------------------------------------
    for name, params in [("local_costmap", local_params), ("global_costmap", global_params)]:
        rr = params.get("robot_radius")
        infl = params.get("inflation_layer", {})
        if isinstance(infl, dict):
            ir = infl.get("inflation_radius")
            if rr is not None and ir is not None and ir < rr:
                issues.append({
                    "rule_id": "inflation_radius_too_small",
                    "severity": "critical",
                    "component": name,
                    "description": (
                        f"In {name}, inflation_radius ({ir}) is less than "
                        f"robot_radius ({rr}). The inflation zone must be at "
                        f"least as large as the robot to prevent collisions."
                    ),
                })

    # ---------------------------------------------------------------
    # Rule 5: Keepout filter info server type code
    # ---------------------------------------------------------------
    keepout_info = _get_nested(cfg, "keepout_costmap_filter_info_server", "ros__parameters", default={})
    if keepout_info:
        ftype = keepout_info.get("type")
        if ftype is not None and ftype != 0:
            issues.append({
                "rule_id": "keepout_filter_type_wrong",
                "severity": "error",
                "component": "keepout_costmap_filter_info_server",
                "description": (
                    f"Keepout filter info server type is {ftype}; must be 0. "
                    f"Type 0 = keepout/preferred-lane, type 1 = speed filter."
                ),
            })

    # ---------------------------------------------------------------
    # Rule 6: Speed filter multiplier sign
    # ---------------------------------------------------------------
    speed_info = _get_nested(cfg, "speed_costmap_filter_info_server", "ros__parameters", default={})
    if speed_info:
        multiplier = speed_info.get("multiplier")
        base = speed_info.get("base", 0.0)
        if multiplier is not None and multiplier > 0 and base > 0:
            issues.append({
                "rule_id": "speed_filter_multiplier_sign",
                "severity": "error",
                "component": "speed_costmap_filter_info_server",
                "description": (
                    f"Speed filter multiplier is {multiplier} (positive) with "
                    f"base {base}. For percentage-based speed limits the "
                    f"multiplier must be negative (typically -1.0) so that "
                    f"speed decreases from the base value."
                ),
            })

    # ---------------------------------------------------------------
    # Rule 7: Local costmap too small for MPPI prediction horizon
    # ---------------------------------------------------------------
    for key, val in ctrl.items():
        if not isinstance(val, dict) or "time_steps" not in val:
            continue
        ts = val.get("time_steps", 56)
        dt = val.get("model_dt", 0.05)
        vx = val.get("vx_max", 0.5)
        horizon_dist = ts * dt * vx
        lw = local_params.get("width", 5)
        lh = local_params.get("height", 5)
        costmap_radius = min(lw, lh) / 2.0
        if horizon_dist > costmap_radius:
            issues.append({
                "rule_id": "costmap_too_small_for_horizon",
                "severity": "warning",
                "component": "local_costmap/controller_server",
                "description": (
                    f"MPPI prediction distance is {horizon_dist:.2f}m "
                    f"(time_steps={ts} * model_dt={dt} * vx_max={vx}) but "
                    f"local costmap radius is only {costmap_radius:.2f}m "
                    f"(width={lw}, height={lh}). Trajectories will be clipped "
                    f"at the costmap boundary."
                ),
            })

    # ---------------------------------------------------------------
    # Rule 8: Progress checker radius > goal tolerance
    # ---------------------------------------------------------------
    pc = ctrl.get("progress_checker", {})
    gc_names = ctrl.get("goal_checker_plugins", [])
    if isinstance(gc_names, str):
        gc_names = [gc_names]
    pc_radius = pc.get("required_movement_radius") if isinstance(pc, dict) else None
    for gc_name in gc_names:
        gc = ctrl.get(gc_name, {})
        if not isinstance(gc, dict):
            continue
        gc_tol = gc.get("xy_goal_tolerance")
        if pc_radius is not None and gc_tol is not None and pc_radius > gc_tol:
            issues.append({
                "rule_id": "progress_checker_exceeds_goal_tolerance",
                "severity": "error",
                "component": "controller_server",
                "description": (
                    f"Progress checker required_movement_radius ({pc_radius}) "
                    f"exceeds goal checker xy_goal_tolerance ({gc_tol}). The "
                    f"robot may be reported as stuck while making fine "
                    f"adjustments near the goal."
                ),
            })

    # ---------------------------------------------------------------
    # Rule 9: Inconsistent robot base frame IDs
    # ---------------------------------------------------------------
    base_frames = {}
    if local_params.get("robot_base_frame"):
        base_frames["local_costmap"] = local_params["robot_base_frame"]
    if global_params.get("robot_base_frame"):
        base_frames["global_costmap"] = global_params["robot_base_frame"]
    if cm_params.get("base_frame_id"):
        base_frames["collision_monitor"] = cm_params["base_frame_id"]
    if bs_params.get("robot_base_frame"):
        base_frames["behavior_server"] = bs_params["robot_base_frame"]
    if bt_params.get("robot_base_frame"):
        base_frames["bt_navigator"] = bt_params["robot_base_frame"]

    if len(set(base_frames.values())) > 1:
        issues.append({
            "rule_id": "frame_id_inconsistency",
            "severity": "error",
            "component": "multiple",
            "description": (
                f"Inconsistent robot base frame IDs across components: "
                f"{base_frames}. All components must use the same base frame "
                f"for TF lookups to succeed."
            ),
        })

    # ---------------------------------------------------------------
    # Rule 10: Velocity smoother clips controller output
    # ---------------------------------------------------------------
    vs_max = vs_params.get("max_velocity", [])
    if vs_max and len(vs_max) >= 3:
        for key, val in ctrl.items():
            if not isinstance(val, dict) or "vx_max" not in val:
                continue
            vx_max = val.get("vx_max", 0)
            wz_max = val.get("wz_max", 0)
            clipped = []
            if vs_max[0] < vx_max:
                clipped.append(f"vx: smoother={vs_max[0]} < controller={vx_max}")
            if vs_max[2] < wz_max:
                clipped.append(f"wz: smoother={vs_max[2]} < controller={wz_max}")
            if clipped:
                issues.append({
                    "rule_id": "velocity_smoother_clips_controller",
                    "severity": "warning",
                    "component": "velocity_smoother",
                    "description": (
                        f"Velocity smoother max_velocity is lower than "
                        f"controller limits: {'; '.join(clipped)}. The smoother "
                        f"will clip controller output, preventing the robot "
                        f"from reaching configured maximum speeds."
                    ),
                })

    # ---------------------------------------------------------------
    # Rule 11: BT navigator timeout < planner timeout
    # ---------------------------------------------------------------
    bt_timeout = bt_params.get("default_server_timeout")
    planner_timeout = planner_params.get("costmap_update_timeout")
    if bt_timeout is not None and planner_timeout is not None:
        if bt_timeout < planner_timeout:
            issues.append({
                "rule_id": "bt_timeout_too_short",
                "severity": "error",
                "component": "bt_navigator",
                "description": (
                    f"BT navigator default_server_timeout ({bt_timeout}s) is "
                    f"less than planner_server costmap_update_timeout "
                    f"({planner_timeout}s). The behavior tree may abort before "
                    f"the planner finishes updating the costmap."
                ),
            })

    # ---------------------------------------------------------------
    # Rule 12: Configured costmap layer not in plugins/filters list
    # ---------------------------------------------------------------
    KNOWN_LAYER_PLUGINS = {
        "nav2_costmap_2d::StaticLayer",
        "nav2_costmap_2d::ObstacleLayer",
        "nav2_costmap_2d::VoxelLayer",
        "nav2_costmap_2d::InflationLayer",
    }
    for name, params in [("local_costmap", local_params), ("global_costmap", global_params)]:
        plugins = params.get("plugins", [])
        filters = params.get("filters", [])
        combined = set(plugins) | set(filters)
        for key, val in params.items():
            if isinstance(val, dict) and "plugin" in val:
                plugin_type = val["plugin"]
                if plugin_type in KNOWN_LAYER_PLUGINS and key not in combined:
                    issues.append({
                        "rule_id": "configured_layer_not_in_plugins",
                        "severity": "error",
                        "component": name,
                        "description": (
                            f"In {name}, layer \"{key}\" is configured with "
                            f"plugin \"{plugin_type}\" but is not listed in "
                            f"the plugins or filters arrays. It will not be "
                            f"loaded."
                        ),
                    })

    return issues


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config.yaml>", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(sys.argv[1])
    issues = audit(cfg)
    print(json.dumps(issues, indent=2))


if __name__ == "__main__":
    main()
