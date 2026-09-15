#!/usr/bin/env python3
"""
Multi-plane rotor balancing, reciprocating engine balance analysis,
and flywheel energy analysis solver.

Uses libbalance.so C library via ctypes for numerical routines.
Supports JSON and TOML input formats.
"""
import ctypes
import json
import math
import os
import sqlite3
import sys

BALANCE_THRESHOLD = 1e-9
LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libbalance.so")


class CorrectionResult(ctypes.Structure):
    _fields_ = [("mass_kg", ctypes.c_double), ("angle_deg", ctypes.c_double)]


class ResidualResult(ctypes.Structure):
    _fields_ = [("residual_mr", ctypes.c_double), ("residual_mrx", ctypes.c_double)]


def load_lib():
    lib = ctypes.CDLL(LIB_PATH)

    lib.rotating_balance.restype = ctypes.c_int
    lib.rotating_balance.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double,
        ctypes.POINTER(CorrectionResult), ctypes.POINTER(CorrectionResult),
        ctypes.POINTER(ResidualResult),
    ]

    lib.reciprocating_balance.restype = ctypes.c_int
    lib.reciprocating_balance.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
    ]

    lib.flywheel_analysis.restype = ctypes.c_int
    lib.flywheel_analysis.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]

    return lib


def make_double_array(lst):
    arr = (ctypes.c_double * len(lst))()
    for i, v in enumerate(lst):
        arr[i] = v
    return arr


def load_config(path):
    if path.endswith(".toml"):
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    else:
        with open(path) as f:
            return json.load(f)


def solve_rotating(lib, config):
    planes = config["planes"]
    known = [p for p in planes if not p.get("is_correction", False)]
    corrections = sorted(
        [p for p in planes if p.get("is_correction", False)],
        key=lambda p: p["axial_position"],
    )

    n = len(known)
    masses = make_double_array([p["mass"] for p in known])
    radii = make_double_array([p["radius"] for p in known])
    angles = make_double_array([p["angle_deg"] for p in known])
    positions = make_double_array([p["axial_position"] for p in known])

    corr1 = CorrectionResult()
    corr2 = CorrectionResult()
    residual = ResidualResult()

    rc = lib.rotating_balance(
        n, masses, radii, angles, positions,
        corrections[0]["axial_position"], corrections[0]["radius"],
        corrections[1]["axial_position"], corrections[1]["radius"],
        ctypes.byref(corr1), ctypes.byref(corr2), ctypes.byref(residual),
    )

    if rc != 0:
        raise RuntimeError("rotating_balance failed")

    return {
        "corrections": [
            {"name": corrections[0]["name"],
             "mass_kg": corr1.mass_kg, "angle_deg": corr1.angle_deg},
            {"name": corrections[1]["name"],
             "mass_kg": corr2.mass_kg, "angle_deg": corr2.angle_deg},
        ],
        "residual_mr": residual.residual_mr,
        "residual_mrx": residual.residual_mrx,
    }


def solve_reciprocating(lib, config):
    cylinders = config["cylinders"]
    omega = config["speed_rad_s"]
    ref_x = config.get("reference_plane_m", 0.0)
    correction_planes = config.get("correction_planes", [])

    n = len(cylinders)
    masses = make_double_array([c["mass_kg"] for c in cylinders])
    crank_radii = make_double_array([c["crank_radius_m"] for c in cylinders])
    rod_lengths = make_double_array([c["con_rod_length_m"] for c in cylinders])
    crank_angles = make_double_array([c["crank_angle_deg"] for c in cylinders])
    axial_pos = make_double_array([c["axial_position_m"] for c in cylinders])

    pf_mr = ctypes.c_double()
    sf_mr_n = ctypes.c_double()
    pm_mrx = ctypes.c_double()
    sm_mrx_n = ctypes.c_double()

    rc = lib.reciprocating_balance(
        n, masses, crank_radii, rod_lengths, crank_angles, axial_pos,
        ref_x,
        ctypes.byref(pf_mr), ctypes.byref(sf_mr_n),
        ctypes.byref(pm_mrx), ctypes.byref(sm_mrx_n),
    )

    if rc != 0:
        raise RuntimeError("reciprocating_balance failed")

    omega2 = omega ** 2

    result = {
        "primary_force": {
            "balanced": pf_mr.value < BALANCE_THRESHOLD,
            "resultant_mr": pf_mr.value,
            "peak_N": omega2 * pf_mr.value,
        },
        "secondary_force": {
            "balanced": sf_mr_n.value < BALANCE_THRESHOLD,
            "resultant_mr_n": sf_mr_n.value,
            "peak_N": omega2 * sf_mr_n.value,
        },
        "primary_moment": {
            "balanced": pm_mrx.value < BALANCE_THRESHOLD,
            "resultant_mrx": pm_mrx.value,
            "peak_Nm": omega2 * pm_mrx.value,
        },
        "secondary_moment": {
            "balanced": sm_mrx_n.value < BALANCE_THRESHOLD,
            "resultant_mrx_n": sm_mrx_n.value,
            "peak_Nm": omega2 * sm_mrx_n.value,
        },
        "primary_corrections": [],
    }

    # Primary balance corrections (computed in Python using complex vectors)
    if len(correction_planes) == 2:
        cp = sorted(correction_planes, key=lambda p: p["axial_position_m"])
        x_ref_c = cp[0]["axial_position_m"]
        d_other = cp[1]["axial_position_m"] - x_ref_c

        sum_mr_c = 0j
        sum_mrx_c = 0j
        for c in cylinders:
            alpha = math.radians(c["crank_angle_deg"])
            mr = c["mass_kg"] * c["crank_radius_m"] * complex(
                math.cos(alpha), math.sin(alpha)
            )
            d_c = c["axial_position_m"] - x_ref_c
            sum_mr_c += mr
            sum_mrx_c += mr * d_c

        mr_corr_other = -sum_mrx_c / d_other
        mr_corr_ref = -(sum_mr_c + mr_corr_other)

        def extract_mass_angle(z, radius):
            mass = abs(z) / radius
            if mass < BALANCE_THRESHOLD:
                return 0.0, 0.0
            angle = math.degrees(math.atan2(z.imag, z.real)) % 360
            return mass, angle

        m_r, a_r = extract_mass_angle(mr_corr_ref, cp[0]["crank_radius_m"])
        m_o, a_o = extract_mass_angle(mr_corr_other, cp[1]["crank_radius_m"])

        result["primary_corrections"] = [
            {"name": cp[0]["name"], "mass_kg": m_r, "angle_deg": a_r},
            {"name": cp[1]["name"], "mass_kg": m_o, "angle_deg": a_o},
        ]

    return result


def solve_flywheel(lib, config):
    data = config["torque_angle_data"]
    cycle = config["cycle_angle_rad"]
    mean_speed_rpm = config["mean_speed_rpm"]

    n = len(data)
    angles_arr = make_double_array([d[0] for d in data])
    torques_arr = make_double_array([d[1] for d in data])

    mean_torque = ctypes.c_double()
    energy = ctypes.c_double()
    fluctuation = ctypes.c_double()

    rc = lib.flywheel_analysis(
        n, angles_arr, torques_arr, cycle,
        ctypes.byref(mean_torque), ctypes.byref(energy), ctypes.byref(fluctuation),
    )

    if rc != 0:
        raise RuntimeError("flywheel_analysis failed")

    omega_mean = mean_speed_rpm * 2.0 * math.pi / 60.0

    result = {
        "mean_torque_Nm": mean_torque.value,
        "energy_per_cycle_J": energy.value,
        "max_energy_fluctuation_J": fluctuation.value,
    }

    target_cs = config.get("target_cof_speed")
    if target_cs is not None:
        inertia = fluctuation.value / (omega_mean ** 2 * target_cs)
        result["required_inertia_kgm2"] = inertia

        k = config.get("flywheel_radius_gyration_m")
        if k is not None:
            result["required_mass_kg"] = inertia / (k ** 2)

        delta_omega = target_cs * omega_mean
        omega_max = omega_mean + delta_omega / 2.0
        omega_min = omega_mean - delta_omega / 2.0
        result["speed_range_rpm"] = {
            "max": omega_max * 60.0 / (2.0 * math.pi),
            "min": omega_min * 60.0 / (2.0 * math.pi),
        }

    return result


def run_analysis(lib, config):
    atype = config["type"]
    if atype == "rotating":
        return solve_rotating(lib, config)
    elif atype == "reciprocating":
        return solve_reciprocating(lib, config)
    elif atype == "flywheel":
        return solve_flywheel(lib, config)
    else:
        raise ValueError(f"Unknown type: {atype}")


def cmd_solve(lib, args):
    config_path = args[0]
    config = load_config(config_path)
    result = run_analysis(lib, config)
    json.dump(result, sys.stdout, indent=2)
    print()


def cmd_batch(lib, args):
    directory = args[0]
    db_path = args[1]

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_name TEXT,
            analysis_type TEXT,
            result_json TEXT,
            mean_torque REAL,
            max_fluctuation REAL,
            residual_mr REAL
        )
    """)

    for fname in sorted(os.listdir(directory)):
        if not (fname.endswith(".json") or fname.endswith(".toml")):
            continue

        config_path = os.path.join(directory, fname)
        config = load_config(config_path)
        analysis_type = config["type"]
        result = run_analysis(lib, config)

        conn.execute(
            "INSERT INTO results "
            "(config_name, analysis_type, result_json, mean_torque, max_fluctuation, residual_mr) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                fname,
                analysis_type,
                json.dumps(result),
                result.get("mean_torque_Nm"),
                result.get("max_energy_fluctuation_J"),
                result.get("residual_mr"),
            ),
        )

    conn.commit()
    conn.close()


def cmd_query(args):
    db_path = args[0]
    sql = args[1]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(sql)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    json.dump(rows, sys.stdout, indent=2)
    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 balance_solver.py <solve|batch|query> ...",
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "query":
        cmd_query(sys.argv[2:])
    else:
        lib = load_lib()
        if cmd == "solve":
            cmd_solve(lib, sys.argv[2:])
        elif cmd == "batch":
            cmd_batch(lib, sys.argv[2:])
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
