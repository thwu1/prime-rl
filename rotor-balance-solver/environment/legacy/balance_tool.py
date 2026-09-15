#!/usr/bin/env python3
"""
Legacy rotating machinery balance analysis tool.
Supports rotating and reciprocating modes.
NOTE: This tool has known calculation issues - use results with caution.
"""
import json
import math
import sys


def analyze_rotating(config):
    planes = config["planes"]
    known = [p for p in planes if not p.get("is_correction", False)]
    corrections = sorted(
        [p for p in planes if p.get("is_correction", False)],
        key=lambda p: p["axial_position"],
    )

    if len(corrections) != 2:
        raise ValueError("Need exactly 2 correction planes")

    ref = corrections[0]
    other = corrections[1]
    x_ref = ref["axial_position"]
    d_other = other["axial_position"] - x_ref

    sum_fx = 0.0
    sum_fy = 0.0
    sum_mx = 0.0
    sum_my = 0.0

    for p in known:
        mr = p["mass"] * p["radius"]
        # component forces
        fx = mr * math.cos(p["angle_deg"])
        fy = mr * math.sin(p["angle_deg"])
        d = p["axial_position"] - x_ref
        sum_fx += fx
        sum_fy += fy
        sum_mx += fx * d
        sum_my += fy * d

    # moment balance about ref -> other correction
    mr_ox = sum_mx / d_other
    mr_oy = sum_my / d_other
    mass_other = math.sqrt(mr_ox ** 2 + mr_oy ** 2) / other["radius"]
    angle_other = math.degrees(math.atan2(mr_oy, mr_ox))

    # force balance -> ref correction
    mr_rx = -(sum_fx + mr_ox)
    mr_ry = -(sum_fy + mr_oy)
    mass_ref = math.sqrt(mr_rx ** 2 + mr_ry ** 2) / ref["radius"]
    angle_ref = math.degrees(math.atan2(mr_ry, mr_rx))

    return {
        "corrections": [
            {"name": ref["name"], "mass_kg": mass_ref, "angle_deg": angle_ref},
            {"name": other["name"], "mass_kg": mass_other, "angle_deg": angle_other},
        ],
        "residual_mr": 0.0,
        "residual_mrx": 0.0,
    }


def analyze_reciprocating(config):
    cylinders = config["cylinders"]
    omega = config["speed_rad_s"]
    ref_x = config.get("reference_plane_m", 0.0)

    sum_fx = 0.0
    sum_fy = 0.0
    sum_mx = 0.0
    sum_my = 0.0

    for c in cylinders:
        m = c["mass_kg"]
        R = c["crank_radius_m"]
        alpha = math.radians(c["crank_angle_deg"])
        d = c["axial_position_m"] - ref_x

        fx = m * R * math.cos(alpha)
        fy = m * R * math.sin(alpha)
        sum_fx += fx
        sum_fy += fy
        sum_mx += fx * d
        sum_my += fy * d

    pf_mag = math.sqrt(sum_fx ** 2 + sum_fy ** 2)
    pm_mag = math.sqrt(sum_mx ** 2 + sum_my ** 2)

    return {
        "primary_force": {
            "balanced": pf_mag < 1e-9,
            "resultant_mr": pf_mag,
            "peak_N": omega ** 2 * pf_mag,
        },
        "secondary_force": {
            "balanced": True,
            "resultant_mr_n": 0.0,
            "peak_N": 0.0,
        },
        "primary_moment": {
            "balanced": pm_mag < 1e-9,
            "resultant_mrx": pm_mag,
            "peak_Nm": omega ** 2 * pm_mag,
        },
        "secondary_moment": {
            "balanced": True,
            "resultant_mrx_n": 0.0,
            "peak_Nm": 0.0,
        },
        "primary_corrections": [],
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 balance_tool.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    mode = config["type"]
    if mode == "rotating":
        result = analyze_rotating(config)
    elif mode == "reciprocating":
        result = analyze_reciprocating(config)
    else:
        print(f"Unsupported type: {mode}", file=sys.stderr)
        sys.exit(1)

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
