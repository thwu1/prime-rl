#!/usr/bin/env python3
"""Nav2 config validator - quick sanity check for AGV migration.
Author: J. Rivera (warehouse robotics team)
"""
import yaml
import sys


def validate():
    with open("/app/nav2_params.yaml") as f:
        config = yaml.safe_load(f)
    with open("/app/robot_spec.yaml") as f:
        spec = yaml.safe_load(f)

    fp = config["controller_server"]["ros__parameters"]["FollowPath"]
    robot = spec["robot"]
    kin = robot["kinematics"]
    local_cm = config["local_costmap"]["local_costmap"]["ros__parameters"]

    passed = 0
    failed = 0

    # Motion model check
    if "motion_model" in fp and fp["motion_model"] in ("ackermann", "diff_drive"):
        print("[PASS] Motion model configured")
        passed += 1
    else:
        print("[FAIL] Motion model not configured")
        failed += 1

    # Ackermann section present
    if "ackermann" in fp:
        print("[PASS] Ackermann motion model section present")
        passed += 1
    else:
        print("[FAIL] Missing ackermann section")
        failed += 1

    # Forward velocity matches spec
    if fp["vx_max"] == kin["max_forward_velocity"]:
        print(f"[PASS] Forward velocity matches spec ({fp['vx_max']})")
        passed += 1
    else:
        print(f"[FAIL] vx_max mismatch: {fp['vx_max']} vs {kin['max_forward_velocity']}")
        failed += 1

    # Inflation radius (compared against inscribed_radius for clearance)
    infl = local_cm["inflation_layer"]["inflation_radius"]
    ref = robot["inscribed_radius"]
    if infl >= ref:
        print(f"[PASS] Local inflation radius ({infl}) >= robot clearance ({ref})")
        passed += 1
    else:
        print(f"[FAIL] Local inflation radius ({infl}) < robot clearance ({ref})")
        failed += 1

    # Costmap dimensions
    if local_cm["width"] > 0 and local_cm["height"] > 0:
        print(f"[PASS] Costmap dimensions: {local_cm['width']}x{local_cm['height']}")
        passed += 1
    else:
        print("[FAIL] Invalid costmap dimensions")
        failed += 1

    # Lateral velocity within bounds
    if fp["vy_max"] <= 0.5:
        print(f"[PASS] Lateral velocity within bounds ({fp['vy_max']})")
        passed += 1
    else:
        print(f"[FAIL] Lateral velocity too high ({fp['vy_max']})")
        failed += 1

    # Cost thresholds
    ncc = fp["CostCritic"]["near_collision_cost"]
    if ncc > 200:
        print(f"[PASS] near_collision_cost provides strong obstacle avoidance ({ncc})")
        passed += 1
    else:
        print(f"[FAIL] near_collision_cost too low ({ncc})")
        failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed == 0:
        print("All checks passed - configuration looks good!")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if validate() else 1)
