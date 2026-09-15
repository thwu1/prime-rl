"""Audit and fix Nav2 configuration for Ackermann warehouse AGV migration.

Queries fleet database for platform constraints and incident history,
reads the robot specification, corrects the MPPI controller YAML and
behavior tree XML, and produces a structured audit report.
"""


import json
import math
import sqlite3
import xml.etree.ElementTree as ET
import yaml


def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def save_yaml(data, path):
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def query_fleet_db(db_path):
    """Query fleet database for Ackermann platform reference data."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get correct motion model plugin for Ackermann platforms
    cur.execute(
        "SELECT motion_model_plugin FROM platform_registry "
        "WHERE platform_type = 'ackermann' LIMIT 1"
    )
    ackermann_plugin = cur.fetchone()["motion_model_plugin"]

    # Get deployment constraints from successful Ackermann deployments
    cur.execute(
        "SELECT param_path, param_value, notes FROM deployment_configs "
        "WHERE platform_id LIKE 'WH-ACK%'"
    )
    constraints = [dict(r) for r in cur.fetchall()]

    # Get incident reports for failure pattern analysis
    cur.execute(
        "SELECT category, root_cause, resolution FROM incident_log "
        "WHERE platform_id LIKE 'WH-ACK%' ORDER BY incident_date"
    )
    incidents = [dict(r) for r in cur.fetchall()]

    conn.close()
    return ackermann_plugin, constraints, incidents


def fix_yaml_config(config, spec, ackermann_plugin):
    """Fix all YAML configuration issues. Returns list of audit entries."""
    robot = spec["robot"]
    kin = robot["kinematics"]
    fp = config["controller_server"]["ros__parameters"]["FollowPath"]
    audit = []

    # --- Motion model ---
    old = fp["motion_model"]
    fp["motion_model"] = "ackermann"
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.motion_model",
        "old": old,
        "new": "ackermann",
        "reason": "Robot is Ackermann-steered; diff_drive generates unrealizable lateral trajectories"
    })

    # --- Ackermann plugin and turning radius ---
    old_ack = dict(fp.get("ackermann", {}))
    fp.pop("diff_drive", None)
    fp["ackermann"] = {
        "plugin": ackermann_plugin,
        "min_turning_r": kin["min_turning_radius"],
    }
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.ackermann",
        "old": old_ack,
        "new": {"plugin": ackermann_plugin, "min_turning_r": kin["min_turning_radius"]},
        "reason": "Plugin was copy-pasted from diff_drive; turning radius did not match specification"
    })

    # --- Lateral velocity ---
    old = fp["vy_max"]
    fp["vy_max"] = 0.0
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.vy_max",
        "old": old,
        "new": 0.0,
        "reason": "Ackermann vehicles cannot strafe; nonzero lateral velocity is physically impossible"
    })

    # --- Lateral acceleration ---
    old_ay_max = fp["ay_max"]
    old_ay_min = fp["ay_min"]
    fp["ay_max"] = 0.0
    fp["ay_min"] = 0.0
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.ay_max",
        "old": old_ay_max,
        "new": 0.0,
        "reason": "No lateral acceleration possible on non-holonomic Ackermann platform"
    })
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.ay_min",
        "old": old_ay_min,
        "new": 0.0,
        "reason": "Lateral deceleration also impossible for non-holonomic Ackermann steering geometry"
    })

    # --- Compute prediction horizon for downstream checks ---
    time_steps = fp["time_steps"]  # protected: 40
    model_dt = fp["model_dt"]     # protected: 0.05
    vx_max = fp["vx_max"]         # 1.0
    pred_dist = time_steps * model_dt * vx_max  # 2.0 m

    # --- Local costmap dimensions ---
    local = config["local_costmap"]["local_costmap"]["ros__parameters"]
    min_dim = 2 * pred_dist
    new_dim = max(int(math.ceil(min_dim)) + 1, 5)

    old_w = local["width"]
    old_h = local["height"]
    local["width"] = new_dim
    local["height"] = new_dim
    audit.append({
        "file": "nav2_params.yaml",
        "path": "local_costmap.width",
        "old": old_w,
        "new": new_dim,
        "reason": f"Must contain MPPI prediction horizon ({pred_dist}m) on each side of robot"
    })
    audit.append({
        "file": "nav2_params.yaml",
        "path": "local_costmap.height",
        "old": old_h,
        "new": new_dim,
        "reason": f"Height must also cover prediction horizon for trajectory evaluation in all directions"
    })

    # --- Rolling window ---
    old = local["rolling_window"]
    local["rolling_window"] = True
    audit.append({
        "file": "nav2_params.yaml",
        "path": "local_costmap.rolling_window",
        "old": old,
        "new": True,
        "reason": "Odom-frame local costmap requires rolling window to stay centered on robot"
    })

    # --- Inflation radius ---
    circ_r = robot["circumscribed_radius"]
    new_infl = round(max(0.55, circ_r + 0.15), 2)

    old_li = local["inflation_layer"]["inflation_radius"]
    local["inflation_layer"]["inflation_radius"] = new_infl
    audit.append({
        "file": "nav2_params.yaml",
        "path": "local_costmap.inflation_layer.inflation_radius",
        "old": old_li,
        "new": new_infl,
        "reason": f"Must exceed circumscribed_radius ({circ_r}m) to protect swept rectangular corners"
    })

    glob = config["global_costmap"]["global_costmap"]["ros__parameters"]
    old_gi = glob["inflation_layer"]["inflation_radius"]
    glob["inflation_layer"]["inflation_radius"] = new_infl
    audit.append({
        "file": "nav2_params.yaml",
        "path": "global_costmap.inflation_layer.inflation_radius",
        "old": old_gi,
        "new": new_infl,
        "reason": f"Global planner also needs inflation exceeding circumscribed_radius for safe paths"
    })

    # --- Velocity smoother consistency ---
    vs = config["velocity_smoother"]["ros__parameters"]
    old_max = list(vs["max_velocity"])
    old_min = list(vs["min_velocity"])
    vs["max_velocity"] = [fp["vx_max"], 0.0, fp["wz_max"]]
    vs["min_velocity"] = [fp["vx_min"], 0.0, -fp["wz_max"]]
    audit.append({
        "file": "nav2_params.yaml",
        "path": "velocity_smoother.max_velocity",
        "old": old_max,
        "new": [fp["vx_max"], 0.0, fp["wz_max"]],
        "reason": "Smoother limits must match controller bounds to prevent asymmetric command clipping"
    })
    audit.append({
        "file": "nav2_params.yaml",
        "path": "velocity_smoother.min_velocity",
        "old": old_min,
        "new": [fp["vx_min"], 0.0, -fp["wz_max"]],
        "reason": "Reverse and angular minimums must mirror controller for consistent velocity pipeline"
    })

    # --- CostCritic near_collision_cost ---
    old_ncc = fp["CostCritic"]["near_collision_cost"]
    fp["CostCritic"]["near_collision_cost"] = 253
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.CostCritic.near_collision_cost",
        "old": old_ncc,
        "new": 253,
        "reason": "Valid OccupancyGrid costs are [0-253]; values 254-255 are reserved sentinel values"
    })

    # --- Critic handoff thresholds ---
    old_gt = fp["GoalCritic"]["threshold_to_consider"]
    old_pt = fp["PathFollowCritic"]["threshold_to_consider"]
    rounded_pred = round(pred_dist, 1)
    fp["GoalCritic"]["threshold_to_consider"] = rounded_pred
    fp["PathFollowCritic"]["threshold_to_consider"] = rounded_pred
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.GoalCritic.threshold_to_consider",
        "old": old_gt,
        "new": rounded_pred,
        "reason": f"Should equal prediction horizon ({rounded_pred}m) for clean behavioral handoff"
    })
    audit.append({
        "file": "nav2_params.yaml",
        "path": "FollowPath.PathFollowCritic.threshold_to_consider",
        "old": old_pt,
        "new": rounded_pred,
        "reason": f"Must match GoalCritic threshold to prevent discontinuous cost function transitions"
    })

    # --- Collision monitor topology ---
    cm = config["collision_monitor"]["ros__parameters"]
    old_topic = cm["cmd_vel_in_topic"]
    cm["cmd_vel_in_topic"] = "cmd_vel_smoothed"
    audit.append({
        "file": "nav2_params.yaml",
        "path": "collision_monitor.cmd_vel_in_topic",
        "old": old_topic,
        "new": "cmd_vel_smoothed",
        "reason": "Must receive post-smoother commands for correct velocity pipeline ordering"
    })

    return audit


def fix_behavior_tree(bt_path):
    """Fix behavior tree recovery actions for Ackermann. Returns audit entries."""
    audit = []

    with open(bt_path, "r") as f:
        content = f.read()

    if "<Spin " in content or "<Spin/>" in content:
        old_snippet = '<Spin spin_dist="1.57"/>'
        new_snippet = '<BackUp backup_dist="0.3" backup_speed="0.15"/>'
        content = content.replace(old_snippet, new_snippet)
        content = content.replace("ClearCostmapAndSpin", "ClearCostmapAndBackUp")
        content = content.replace("ClearLocalCostmap-Spin", "ClearLocalCostmap-BackUp")
        content = content.replace("ClearGlobalCostmap-Spin", "ClearGlobalCostmap-BackUp")

        audit.append({
            "file": "nav2_bt.xml",
            "path": "RecoveryActions.Spin",
            "old": "Spin(spin_dist=1.57)",
            "new": "BackUp(backup_dist=0.3, backup_speed=0.15)",
            "reason": "Ackermann vehicles cannot rotate in place; BackUp is a valid alternative recovery"
        })

    with open(bt_path, "w") as f:
        f.write(content)

    return audit


def main():
    config = load_yaml("/app/nav2_params.yaml")
    spec = load_yaml("/app/robot_spec.yaml")
    ackermann_plugin, constraints, incidents = query_fleet_db("/app/fleet.db")

    # Fix YAML configuration
    audit = fix_yaml_config(config, spec, ackermann_plugin)
    save_yaml(config, "/app/nav2_params.yaml")

    # Fix behavior tree
    bt_audit = fix_behavior_tree("/app/nav2_bt.xml")
    audit.extend(bt_audit)

    # Write audit report
    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2, default=str)

    print(f"Migration complete. {len(audit)} issues documented in audit.json.")


if __name__ == "__main__":
    main()
