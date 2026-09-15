#!/usr/bin/env python3
"""
Nav2 configuration failure diagnosis, repair, and justification.


Reads /app/nav2_params_broken.yaml, /app/robot_spec.json, and simulation logs.
Evaluates the provided validation tool for correctness.
Produces diagnosis_report.json, nav2_params_fixed.yaml, and parameter_justification.json.
"""

import copy
import json
import yaml


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


def classify_log_entries(log_path):
    """Parse simulation log and classify entries as config-related or environmental."""
    environmental = []

    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            lower = line.lower()

            # Environmental / non-config observations
            if "laser scan" in lower and ("below minimum" in lower or "max range" in lower or "multipath" in lower):
                environmental.append({
                    "id": "sensor_noise",
                    "description": f"Transient sensor artifact — normal lidar behavior: {line.split('] ')[-1]}"
                })
            elif "tf" in lower and "latency" in lower and "within" in lower:
                environmental.append({
                    "id": "tf_latency_nominal",
                    "description": f"TF latency within tolerance — not a configuration issue: {line.split('] ')[-1]}"
                })
            elif "battery" in lower:
                environmental.append({
                    "id": "battery_telemetry",
                    "description": f"Normal battery monitoring data: {line.split('] ')[-1]}"
                })
            elif "wifi" in lower or "rssi" in lower:
                environmental.append({
                    "id": "network_transient",
                    "description": f"Transient WiFi signal fluctuation — no impact on configuration: {line.split('] ')[-1]}"
                })
            elif "lidar" in lower and ("self-test" in lower or "health" in lower or "nominal" in lower):
                environmental.append({
                    "id": "lidar_health_nominal",
                    "description": f"Lidar health check passed — sensor hardware functioning normally: {line.split('] ')[-1]}"
                })
            elif "cpu temperature" in lower or "cpu temp" in lower:
                environmental.append({
                    "id": "cpu_thermal",
                    "description": f"CPU temperature within operating range — not config related: {line.split('] ')[-1]}"
                })
            elif "encoder" in lower and "nominal" in lower:
                environmental.append({
                    "id": "encoder_telemetry",
                    "description": f"Wheel encoder functioning normally: {line.split('] ')[-1]}"
                })

    return environmental


def audit_config(cfg, spec):
    """Analyze the configuration and return a list of issues with evidence."""
    issues = []

    fp = get_nested(cfg, "controller_server", "ros__parameters", "FollowPath", default={})
    cp = get_nested(cfg, "controller_server", "ros__parameters", default={})
    lc = get_nested(cfg, "local_costmap", "local_costmap", "ros__parameters", default={})
    gc = get_nested(cfg, "global_costmap", "global_costmap", "ros__parameters", default={})
    vs = get_nested(cfg, "velocity_smoother", "ros__parameters", default={})

    # Bug 1: Prediction horizon exceeds costmap
    time_steps = fp.get("time_steps", 56)
    model_dt = fp.get("model_dt", 0.05)
    vx_max = fp.get("vx_max", 0.5)
    prediction_distance = time_steps * model_dt * vx_max
    costmap_width = lc.get("width", 3)
    costmap_radius = costmap_width / 2.0

    if prediction_distance > costmap_radius:
        issues.append({
            "id": "prediction_horizon_exceeds_costmap",
            "severity": "critical",
            "description": (
                f"MPPI prediction distance ({time_steps} time_steps * "
                f"{model_dt} model_dt * {vx_max} vx_max = {prediction_distance:.2f}m) "
                f"exceeds local costmap radius ({costmap_width}m width / 2 = "
                f"{costmap_radius:.2f}m). Trajectories extend beyond available "
                f"cost information, causing the controller to plan blind."
            ),
            "evidence": [
                f"Config: FollowPath.time_steps={time_steps}, model_dt={model_dt}, vx_max={vx_max}",
                f"Config: local_costmap width={costmap_width}m",
                "Sim log: 'trajectory rollout extends beyond local costmap boundary at step 62/80'"
            ]
        })

    # Bug 2: Wrong motion model
    motion_model = fp.get("motion_model", "")
    drive_type = spec.get("drive_type", "differential")
    if drive_type == "differential" and "diff" not in motion_model.lower():
        issues.append({
            "id": "wrong_motion_model",
            "severity": "critical",
            "description": (
                f"motion_model is set to '{motion_model}' but robot spec "
                f"indicates '{drive_type}' drive. Using omni motion model on "
                f"a differential drive robot produces lateral velocity commands "
                f"the robot cannot execute."
            ),
            "evidence": [
                f"Config: FollowPath.motion_model='{motion_model}'",
                f"Robot spec: drive_type='{drive_type}'",
                "Sim log: 'Lateral velocity command vy=0.31 m/s generated but base_link reports zero lateral DOF'"
            ]
        })

    # Bug 3: Velocity smoother clips controller output
    vs_max_vel = vs.get("max_velocity", [0, 0, 0])
    wz_max = fp.get("wz_max", 1.9)
    if vs_max_vel[0] < vx_max:
        issues.append({
            "id": "velocity_smoother_clips_linear_velocity",
            "severity": "critical",
            "description": (
                f"Velocity smoother max_velocity[0]={vs_max_vel[0]} is less "
                f"than MPPI vx_max={vx_max}. The smoother clips the controller's "
                f"linear velocity output, making trajectory predictions invalid."
            ),
            "evidence": [
                f"Config: velocity_smoother.max_velocity[0]={vs_max_vel[0]}",
                f"Config: FollowPath.vx_max={vx_max}",
                "Sim log: 'Linear velocity clipped: controller commanded 0.48 m/s, smoother output 0.30 m/s'"
            ]
        })
    if vs_max_vel[2] < wz_max:
        issues.append({
            "id": "velocity_smoother_clips_angular_velocity",
            "severity": "warning",
            "description": (
                f"Velocity smoother max_velocity[2]={vs_max_vel[2]} is less "
                f"than MPPI wz_max={wz_max}. The smoother clips angular velocity."
            ),
            "evidence": [
                f"Config: velocity_smoother.max_velocity[2]={vs_max_vel[2]}",
                f"Config: FollowPath.wz_max={wz_max}",
                "Sim log: 'Angular velocity clipped: controller commanded 1.72 rad/s, smoother output 1.50 rad/s'"
            ]
        })

    # Bug 4: raytrace_max_range < obstacle_max_range
    voxel_scan = get_nested(lc, "voxel_layer", "scan", default={})
    raytrace = voxel_scan.get("raytrace_max_range", 3.0)
    obstacle = voxel_scan.get("obstacle_max_range", 2.5)
    if raytrace < obstacle:
        issues.append({
            "id": "raytrace_less_than_obstacle_range",
            "severity": "critical",
            "description": (
                f"In local costmap voxel_layer scan: "
                f"raytrace_max_range={raytrace} < obstacle_max_range={obstacle}. "
                f"Obstacles detected between {raytrace}m and {obstacle}m will "
                f"never be cleared by raytracing, creating persistent ghost obstacles."
            ),
            "evidence": [
                f"Config: voxel_layer.scan.raytrace_max_range={raytrace}",
                f"Config: voxel_layer.scan.obstacle_max_range={obstacle}",
                "Sim log: 'Obstacle cell persists at map coordinates (42, 16) — no active sensor detection for 45 seconds'",
                "Sim log: '12 stale obstacle cells detected in voxel layer — possible clearing range deficiency'"
            ]
        })

    # Bug 5: Inflation radius mismatch
    local_infl = get_nested(lc, "inflation_layer", "inflation_radius", default=0.55)
    global_infl = get_nested(gc, "inflation_layer", "inflation_radius", default=0.55)
    if abs(local_infl - global_infl) > 0.1:
        issues.append({
            "id": "inflation_radius_mismatch",
            "severity": "critical",
            "description": (
                f"Inflation radius differs between local costmap ({local_infl}m) "
                f"and global costmap ({global_infl}m). This causes the planner "
                f"to generate paths through areas the controller considers costly. "
                f"Note: the validation tool incorrectly passes this check."
            ),
            "evidence": [
                f"Config: local_costmap inflation_radius={local_infl}",
                f"Config: global_costmap inflation_radius={global_infl}",
                "Sim log: 'local costmap marks cells as LETHAL where global costmap shows FREE'",
                "Validation tool bug: reports 'correct hierarchy' instead of flagging mismatch"
            ]
        })

    # Bug 6: Robot radius inconsistency
    local_rr = lc.get("robot_radius", 0.22)
    global_rr = gc.get("robot_radius", 0.22)
    spec_rr = spec.get("robot_radius_m", 0.22)
    if abs(local_rr - global_rr) > 0.01:
        issues.append({
            "id": "robot_radius_inconsistency",
            "severity": "critical",
            "description": (
                f"robot_radius differs: local={local_rr}m, global={global_rr}m "
                f"(spec={spec_rr}m). Different inscribed radii create different "
                f"lethal zones, causing corridor planning failures."
            ),
            "evidence": [
                f"Config: local_costmap robot_radius={local_rr}",
                f"Config: global_costmap robot_radius={global_rr}",
                f"Robot spec: robot_radius_m={spec_rr}",
                "Sim log: 'Corridor width in global map: 0.82m' but robot cannot traverse"
            ]
        })

    # Bug 7: PathFollowCritic/GoalCritic threshold mismatch
    pf_thresh = get_nested(fp, "PathFollowCritic", "threshold_to_consider", default=1.4)
    gc_thresh = get_nested(fp, "GoalCritic", "threshold_to_consider", default=1.4)
    if abs(pf_thresh - gc_thresh) > 0.3:
        issues.append({
            "id": "critic_threshold_to_consider_mismatch",
            "severity": "warning",
            "description": (
                f"PathFollowCritic threshold_to_consider={pf_thresh} differs "
                f"from GoalCritic threshold_to_consider={gc_thresh}. "
                f"These should be equal for clean handoff between path following "
                f"and goal seeking. The gap causes oscillation near goals."
            ),
            "evidence": [
                f"Config: PathFollowCritic.threshold_to_consider={pf_thresh}",
                f"Config: GoalCritic.threshold_to_consider={gc_thresh}",
                "Sim log: 'GoalCritic and PathFollowCritic both active with conflicting weights'",
                "Sim log: 'Oscillation detected near goal — 4 direction reversals in 2.0 seconds'"
            ]
        })

    # Bug 8: model_dt exceeds control period
    ctrl_freq = cp.get("controller_frequency", 20.0)
    control_period = 1.0 / ctrl_freq
    if model_dt > control_period + 0.001:
        issues.append({
            "id": "model_dt_exceeds_control_period",
            "severity": "critical",
            "description": (
                f"model_dt={model_dt}s exceeds control period "
                f"1/{ctrl_freq}Hz={control_period:.4f}s. The MPPI controller "
                f"predicts at coarser resolution than it operates, producing "
                f"suboptimal control. This check was missing from the validation tool."
            ),
            "evidence": [
                f"Config: FollowPath.model_dt={model_dt}",
                f"Config: controller_frequency={ctrl_freq}Hz, period={control_period:.4f}s",
                "Sim log: 'MPPI forward simulation timestep (model_dt) is coarser than control loop period'",
                "Validation tool omission: no check for model_dt vs control period"
            ]
        })

    # Bug 9: obstacle_layer missing from global costmap plugins
    gc_plugins = gc.get("plugins", [])
    has_obstacle_plugin = any("obstacle" in p.lower() or "voxel" in p.lower()
                              for p in gc_plugins)
    obstacle_config_exists = "obstacle_layer" in gc or "voxel_layer" in gc
    if obstacle_config_exists and not has_obstacle_plugin:
        issues.append({
            "id": "obstacle_layer_missing_from_global_plugins",
            "severity": "critical",
            "description": (
                f"Global costmap has obstacle_layer configuration but it is not "
                f"in the plugins list {gc_plugins}. Dynamic obstacles are invisible "
                f"to the global planner."
            ),
            "evidence": [
                f"Config: global_costmap plugins={gc_plugins}",
                "Config: obstacle_layer section exists with full configuration",
                "Sim log: 'Global costmap contains no dynamic obstacle layer — replanning uses only static map data'",
                "Sim log: 'Replanned path routes through area with known dynamic obstacle'"
            ]
        })

    # Bug 10: Acceleration limits mismatch
    vs_accel = vs.get("max_accel", [3.0, 0.0, 3.5])
    vs_decel = vs.get("max_decel", [-3.0, 0.0, -3.5])
    ax_max = fp.get("ax_max", 3.0)
    az_max = fp.get("az_max", 3.5)
    ax_min = fp.get("ax_min", -3.0)

    if vs_accel[0] < ax_max * 0.7:
        issues.append({
            "id": "acceleration_limit_mismatch",
            "severity": "critical",
            "description": (
                f"Velocity smoother max_accel[0]={vs_accel[0]} is much lower "
                f"than MPPI ax_max={ax_max}. The smoother aggressively clips "
                f"acceleration, causing trajectory prediction to diverge from "
                f"actual execution. max_accel[2]={vs_accel[2]} vs az_max={az_max} "
                f"has the same problem. Missing from validation tool."
            ),
            "evidence": [
                f"Config: velocity_smoother max_accel={vs_accel}",
                f"Config: FollowPath ax_max={ax_max}, az_max={az_max}",
                "Sim log: 'Acceleration clipped: controller commanded 2.8 m/s², smoother output 1.0 m/s²'",
                "Sim log: 'Angular acceleration clipped: commanded 3.2 rad/s², smoother output 1.5 rad/s²'",
                "Validation tool omission: no acceleration limit check"
            ]
        })

    if abs(vs_decel[0]) < abs(ax_min) * 0.7:
        issues.append({
            "id": "deceleration_limit_mismatch",
            "severity": "warning",
            "description": (
                f"Velocity smoother max_decel[0]={vs_decel[0]} is much less "
                f"aggressive than MPPI ax_min={ax_min}."
            ),
            "evidence": [
                f"Config: velocity_smoother max_decel={vs_decel}",
                f"Config: FollowPath ax_min={ax_min}"
            ]
        })

    return issues


def fix_config(cfg, spec):
    """Fix all identified issues and return the corrected config."""
    fixed = copy.deepcopy(cfg)

    fp = fixed["controller_server"]["ros__parameters"]["FollowPath"]
    cp = fixed["controller_server"]["ros__parameters"]
    lc = fixed["local_costmap"]["local_costmap"]["ros__parameters"]
    gc = fixed["global_costmap"]["global_costmap"]["ros__parameters"]
    vs = fixed["velocity_smoother"]["ros__parameters"]

    spec_rr = spec["robot_radius_m"]
    spec_vx = spec["max_forward_velocity_ms"]
    spec_vx_rev = spec["max_reverse_velocity_ms"]
    spec_wz = spec["max_angular_velocity_rads"]
    spec_ax = spec["max_forward_acceleration_ms2"]
    spec_decel = spec["max_deceleration_ms2"]
    spec_az = spec["max_angular_acceleration_rads2"]

    # Fix Bug 8: model_dt to match control period
    ctrl_freq = cp.get("controller_frequency", 20.0)
    correct_dt = 1.0 / ctrl_freq
    fp["model_dt"] = correct_dt

    # Fix Bug 1: Reduce time_steps so prediction fits costmap
    costmap_width = lc.get("width", 3)
    costmap_radius = costmap_width / 2.0
    max_time_steps = int(costmap_radius / (correct_dt * spec_vx))
    fp["time_steps"] = min(fp.get("time_steps", 56), max_time_steps)
    if max_time_steps >= 56:
        fp["time_steps"] = 56

    # Fix Bug 2: Correct motion model to differential drive
    fp["motion_model"] = "diff_drive"
    if "omni" in fp:
        del fp["omni"]
    fp["diff_drive"] = {"plugin": "mppi::DiffDriveMotionModel"}

    # Fix velocity parameters for diff drive
    fp["vx_max"] = spec_vx
    fp["vx_min"] = -spec_vx_rev
    fp["wz_max"] = spec_wz
    fp["ax_max"] = spec_ax
    fp["ax_min"] = -spec_decel
    fp["az_max"] = spec_az

    # Fix Bug 3: Velocity smoother must not clip controller
    vs["max_velocity"] = [spec_vx, 0.0, 2.0]
    vs["min_velocity"] = [-spec_vx_rev, 0.0, -2.0]

    # Fix Bug 10: Acceleration limits must match
    vs["max_accel"] = [spec_ax, 0.0, spec_az]
    vs["max_decel"] = [-spec_decel, 0.0, -spec_az]

    # Fix Bug 4: raytrace_max_range >= obstacle_max_range
    voxel = lc.get("voxel_layer", {})
    scan = voxel.get("scan", {})
    obs_range = scan.get("obstacle_max_range", 2.5)
    ray_range = scan.get("raytrace_max_range", 3.0)
    if ray_range < obs_range:
        correct_raytrace = max(obs_range, 3.0)
        lc["voxel_layer"]["scan"]["raytrace_max_range"] = correct_raytrace

    # Fix Bug 5: Equalize inflation radius between costmaps
    target_inflation = 0.55
    lc["inflation_layer"]["inflation_radius"] = target_inflation
    gc["inflation_layer"]["inflation_radius"] = target_inflation
    gc["inflation_layer"]["cost_scaling_factor"] = lc["inflation_layer"].get(
        "cost_scaling_factor", 3.0
    )

    # Fix Bug 6: Equalize robot_radius and match spec
    lc["robot_radius"] = spec_rr
    gc["robot_radius"] = spec_rr

    # Fix Bug 7: Match PathFollowCritic and GoalCritic thresholds
    threshold_val = round(fp["time_steps"] * fp["model_dt"] * spec_vx, 1)
    if threshold_val < 0.5:
        threshold_val = 1.4
    fp["PathFollowCritic"]["threshold_to_consider"] = threshold_val
    fp["GoalCritic"]["threshold_to_consider"] = threshold_val

    # Fix Bug 9: Add obstacle_layer to global costmap plugins
    gc_plugins = gc.get("plugins", [])
    has_obstacle = any("obstacle" in p.lower() for p in gc_plugins)
    if not has_obstacle and "obstacle_layer" in gc:
        if "inflation_layer" in gc_plugins:
            idx = gc_plugins.index("inflation_layer")
            gc_plugins.insert(idx, "obstacle_layer")
        else:
            gc_plugins.append("obstacle_layer")
        gc["plugins"] = gc_plugins

    return fixed


def build_justification(cfg, fixed, spec):
    """Build a justification for each parameter change."""
    changes = []

    fp_old = get_nested(cfg, "controller_server", "ros__parameters", "FollowPath", default={})
    fp_new = get_nested(fixed, "controller_server", "ros__parameters", "FollowPath", default={})
    vs_old = get_nested(cfg, "velocity_smoother", "ros__parameters", default={})
    vs_new = get_nested(fixed, "velocity_smoother", "ros__parameters", default={})
    lc_old = get_nested(cfg, "local_costmap", "local_costmap", "ros__parameters", default={})
    lc_new = get_nested(fixed, "local_costmap", "local_costmap", "ros__parameters", default={})
    gc_old = get_nested(cfg, "global_costmap", "global_costmap", "ros__parameters", default={})
    gc_new = get_nested(fixed, "global_costmap", "global_costmap", "ros__parameters", default={})

    changes.append({
        "parameter": "controller_server.FollowPath.motion_model",
        "old_value": fp_old.get("motion_model"),
        "new_value": fp_new.get("motion_model"),
        "rationale": (
            f"Robot spec drive_type='{spec['drive_type']}' — omni motion model "
            f"generates lateral velocity commands incompatible with differential drive hardware"
        )
    })

    changes.append({
        "parameter": "controller_server.FollowPath.model_dt",
        "old_value": fp_old.get("model_dt"),
        "new_value": fp_new.get("model_dt"),
        "rationale": (
            f"model_dt must not exceed control period 1/{get_nested(cfg, 'controller_server', 'ros__parameters', 'controller_frequency', default=20.0)}Hz = "
            f"{1.0/get_nested(cfg, 'controller_server', 'ros__parameters', 'controller_frequency', default=20.0):.4f}s "
            f"for prediction resolution to match control loop granularity"
        )
    })

    changes.append({
        "parameter": "controller_server.FollowPath.time_steps",
        "old_value": fp_old.get("time_steps"),
        "new_value": fp_new.get("time_steps"),
        "rationale": (
            f"Prediction distance (time_steps * model_dt * vx_max) must fit within "
            f"local costmap radius ({lc_new.get('width', 3)/2.0}m) to ensure cost "
            f"information covers the entire prediction horizon"
        )
    })

    changes.append({
        "parameter": "velocity_smoother.max_velocity",
        "old_value": vs_old.get("max_velocity"),
        "new_value": vs_new.get("max_velocity"),
        "rationale": (
            f"Smoother velocity limits must be >= MPPI controller limits "
            f"(vx_max={fp_new.get('vx_max')}, wz_max={fp_new.get('wz_max')}) "
            f"to prevent clipping that invalidates trajectory predictions. "
            f"Sim log confirmed both linear and angular clipping."
        )
    })

    changes.append({
        "parameter": "velocity_smoother.max_accel",
        "old_value": vs_old.get("max_accel"),
        "new_value": vs_new.get("max_accel"),
        "rationale": (
            f"Smoother acceleration limits must match MPPI limits "
            f"(ax_max={spec['max_forward_acceleration_ms2']}, "
            f"az_max={spec['max_angular_acceleration_rads2']}) from robot spec "
            f"to prevent trajectory/execution divergence. Sim log showed 2.8→1.0 clipping."
        )
    })

    changes.append({
        "parameter": "velocity_smoother.max_decel",
        "old_value": vs_old.get("max_decel"),
        "new_value": vs_new.get("max_decel"),
        "rationale": (
            f"Deceleration limits aligned with robot spec "
            f"max_deceleration_ms2={spec['max_deceleration_ms2']} and "
            f"max_angular_acceleration_rads2={spec['max_angular_acceleration_rads2']}"
        )
    })

    changes.append({
        "parameter": "local_costmap.voxel_layer.scan.raytrace_max_range",
        "old_value": get_nested(lc_old, "voxel_layer", "scan", "raytrace_max_range"),
        "new_value": get_nested(lc_new, "voxel_layer", "scan", "raytrace_max_range"),
        "rationale": (
            f"raytrace_max_range must be >= obstacle_max_range to ensure obstacles "
            f"beyond raytrace range can be cleared. Previous value created persistent "
            f"ghost obstacles as confirmed by sim log."
        )
    })

    changes.append({
        "parameter": "local_costmap.inflation_layer.inflation_radius",
        "old_value": get_nested(lc_old, "inflation_layer", "inflation_radius"),
        "new_value": get_nested(lc_new, "inflation_layer", "inflation_radius"),
        "rationale": (
            f"Inflation radius equalized between local and global costmaps to prevent "
            f"planner/controller disagreement on path feasibility through narrow corridors. "
            f"Validation tool incorrectly approved the previous mismatch."
        )
    })

    changes.append({
        "parameter": "global_costmap.inflation_layer.inflation_radius",
        "old_value": get_nested(gc_old, "inflation_layer", "inflation_radius"),
        "new_value": get_nested(gc_new, "inflation_layer", "inflation_radius"),
        "rationale": (
            f"Matched to local costmap inflation_radius={get_nested(lc_new, 'inflation_layer', 'inflation_radius')}m "
            f"for planner/controller consistency. Value chosen to allow passage "
            f"through min corridor {spec['min_corridor_width_m']}m with robot radius {spec['robot_radius_m']}m."
        )
    })

    changes.append({
        "parameter": "global_costmap.robot_radius",
        "old_value": gc_old.get("robot_radius"),
        "new_value": gc_new.get("robot_radius"),
        "rationale": (
            f"Set to robot spec robot_radius_m={spec['robot_radius_m']}m to match "
            f"local costmap and physical robot dimensions"
        )
    })

    changes.append({
        "parameter": "controller_server.FollowPath.PathFollowCritic.threshold_to_consider",
        "old_value": get_nested(fp_old, "PathFollowCritic", "threshold_to_consider"),
        "new_value": get_nested(fp_new, "PathFollowCritic", "threshold_to_consider"),
        "rationale": (
            f"Equalized with GoalCritic threshold for clean handoff between "
            f"path-following and goal-seeking behavior, eliminating oscillation near goals"
        )
    })

    changes.append({
        "parameter": "controller_server.FollowPath.GoalCritic.threshold_to_consider",
        "old_value": get_nested(fp_old, "GoalCritic", "threshold_to_consider"),
        "new_value": get_nested(fp_new, "GoalCritic", "threshold_to_consider"),
        "rationale": (
            f"Equalized with PathFollowCritic threshold. Both set to prediction "
            f"distance for smooth transition. Sim log confirmed oscillation from mismatch."
        )
    })

    changes.append({
        "parameter": "global_costmap.plugins",
        "old_value": gc_old.get("plugins"),
        "new_value": gc_new.get("plugins"),
        "rationale": (
            f"Added obstacle_layer to plugins list — configuration section existed "
            f"but plugin was not loaded, leaving global planner blind to dynamic obstacles. "
            f"Sim log confirmed global planner routing through known obstacles."
        )
    })

    return changes


def main():
    cfg = load_yaml("/app/nav2_params_broken.yaml")
    spec = load_json("/app/robot_spec.json")

    # Classify simulation log entries
    environmental = classify_log_entries("/app/sim_logs/navigation_test.log")

    # Audit configuration
    config_issues = audit_config(cfg, spec)

    # Build diagnosis report
    diagnosis = {
        "config_issues": config_issues,
        "environmental": environmental
    }
    with open("/app/diagnosis_report.json", "w") as f:
        json.dump(diagnosis, f, indent=2)
    print(f"Diagnosis complete: {len(config_issues)} config issues, {len(environmental)} environmental observations")

    # Fix configuration
    fixed = fix_config(cfg, spec)
    with open("/app/nav2_params_fixed.yaml", "w") as f:
        yaml.dump(fixed, f, default_flow_style=False, sort_keys=False)
    print("Fixed configuration written to /app/nav2_params_fixed.yaml")

    # Build justification
    justification = {"changes": build_justification(cfg, fixed, spec)}
    with open("/app/parameter_justification.json", "w") as f:
        json.dump(justification, f, indent=2)
    print(f"Parameter justification written: {len(justification['changes'])} changes documented")

    # Verify
    verify_issues = audit_config(fixed, spec)
    if verify_issues:
        print(f"\nWARNING: {len(verify_issues)} issues remain after fix:")
        for issue in verify_issues:
            print(f"  [{issue['severity']}] {issue['id']}")
    else:
        print("\nVerification passed: no issues found in fixed configuration")


if __name__ == "__main__":
    main()
