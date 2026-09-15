#!/usr/bin/env python3
"""
Fix known issues in a Nav2 configuration file.

Usage: python3 fix_config.py <input.yaml> <output.yaml>
"""

import sys

import yaml


def fix_config(cfg):
    local_params = cfg["local_costmap"]["local_costmap"]["ros__parameters"]
    global_params = cfg["global_costmap"]["global_costmap"]["ros__parameters"]
    ctrl = cfg["controller_server"]["ros__parameters"]

    # ------------------------------------------------------------------
    # Fix 1: Costmap plugin ordering — inflation after obstacle sources
    # ------------------------------------------------------------------
    for params in [local_params, global_params]:
        plugins = params.get("plugins", [])
        sources = [p for p in plugins if p in ("voxel_layer", "obstacle_layer", "static_layer")]
        inflations = [p for p in plugins if "inflation" in p.lower()]
        others = [p for p in plugins if p not in sources and p not in inflations]
        params["plugins"] = sources + others + inflations

    # ------------------------------------------------------------------
    # Fix 2: Motion model plugin consistency
    # ------------------------------------------------------------------
    PLUGIN_MAP = {
        "diff_drive": "mppi::DiffDriveMotionModel",
        "omni": "mppi::OmniMotionModel",
        "ackermann": "mppi::AckermannMotionModel",
    }
    for key, val in list(ctrl.items()):
        if not isinstance(val, dict) or "motion_model" not in val:
            continue
        mm = val["motion_model"]
        if mm in PLUGIN_MAP and mm in val and isinstance(val[mm], dict):
            val[mm]["plugin"] = PLUGIN_MAP[mm]

    # ------------------------------------------------------------------
    # Fix 3: Robot radius consistency — use local value as ground truth
    # ------------------------------------------------------------------
    robot_radius = local_params.get("robot_radius", 0.22)
    global_params["robot_radius"] = robot_radius

    # ------------------------------------------------------------------
    # Fix 4: Inflation radius >= robot radius
    # ------------------------------------------------------------------
    for params in [local_params, global_params]:
        rr = params.get("robot_radius", 0.22)
        infl = params.get("inflation_layer", {})
        if isinstance(infl, dict):
            ir = infl.get("inflation_radius", 0)
            if ir < rr:
                infl["inflation_radius"] = round(rr * 2.5, 2)

    # ------------------------------------------------------------------
    # Fix 5: Keepout filter type = 0
    # ------------------------------------------------------------------
    keepout = cfg.get("keepout_costmap_filter_info_server", {}).get("ros__parameters")
    if keepout:
        keepout["type"] = 0

    # ------------------------------------------------------------------
    # Fix 6: Speed filter multiplier = -1.0
    # ------------------------------------------------------------------
    speed = cfg.get("speed_costmap_filter_info_server", {}).get("ros__parameters")
    if speed:
        speed["multiplier"] = -1.0

    # ------------------------------------------------------------------
    # Fix 7: Costmap size for prediction horizon
    # ------------------------------------------------------------------
    for key, val in ctrl.items():
        if not isinstance(val, dict) or "time_steps" not in val:
            continue
        horizon_dist = val["time_steps"] * val["model_dt"] * val["vx_max"]
        required_width = max(int(horizon_dist * 2) + 1, 3)
        local_params["width"] = required_width
        local_params["height"] = required_width

    # ------------------------------------------------------------------
    # Fix 8: Progress checker radius <= goal tolerance
    # ------------------------------------------------------------------
    pc = ctrl.get("progress_checker", {})
    gc_names = ctrl.get("goal_checker_plugins", [])
    if isinstance(gc_names, str):
        gc_names = [gc_names]
    for gc_name in gc_names:
        gc = ctrl.get(gc_name, {})
        if isinstance(gc, dict) and "xy_goal_tolerance" in gc:
            pc["required_movement_radius"] = gc["xy_goal_tolerance"] * 0.5

    # ------------------------------------------------------------------
    # Fix 9: Frame ID consistency — standardise to base_link
    # ------------------------------------------------------------------
    cm = cfg.get("collision_monitor", {}).get("ros__parameters")
    if cm:
        cm["base_frame_id"] = "base_link"

    # ------------------------------------------------------------------
    # Fix 10: Velocity smoother >= controller limits
    # ------------------------------------------------------------------
    vs = cfg.get("velocity_smoother", {}).get("ros__parameters")
    if vs:
        for key, val in ctrl.items():
            if not isinstance(val, dict) or "vx_max" not in val:
                continue
            vs["max_velocity"] = [val["vx_max"], 0.0, val["wz_max"]]
            vs["min_velocity"] = [val["vx_min"], 0.0, -val["wz_max"]]

    # ------------------------------------------------------------------
    # Fix 11: BT timeout >= planner timeout
    # ------------------------------------------------------------------
    bt = cfg.get("bt_navigator", {}).get("ros__parameters")
    pl = cfg.get("planner_server", {}).get("ros__parameters")
    if bt and pl:
        pt = pl.get("costmap_update_timeout", 1.0)
        if bt.get("default_server_timeout", 0) < pt:
            bt["default_server_timeout"] = max(20, int(pt * 2))

    # ------------------------------------------------------------------
    # Fix 12: Ensure configured layers are in plugins list
    # ------------------------------------------------------------------
    KNOWN_LAYER_PLUGINS = {
        "nav2_costmap_2d::StaticLayer",
        "nav2_costmap_2d::ObstacleLayer",
        "nav2_costmap_2d::VoxelLayer",
        "nav2_costmap_2d::InflationLayer",
    }
    for params in [local_params, global_params]:
        plugins = params.get("plugins", [])
        filters = params.get("filters", [])
        combined = set(plugins) | set(filters)
        for key, val in list(params.items()):
            if isinstance(val, dict) and "plugin" in val:
                if val["plugin"] in KNOWN_LAYER_PLUGINS and key not in combined:
                    # Insert before inflation
                    infl_idx = next(
                        (i for i, p in enumerate(plugins) if "inflation" in p.lower()),
                        len(plugins),
                    )
                    plugins.insert(infl_idx, key)
                    combined.add(key)
        params["plugins"] = plugins

    return cfg


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.yaml> <output.yaml>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        cfg = yaml.safe_load(f)

    cfg = fix_config(cfg)

    with open(sys.argv[2], "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()
