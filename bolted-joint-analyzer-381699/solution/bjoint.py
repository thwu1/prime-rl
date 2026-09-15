#!/usr/bin/env python3
"""
Bolted Joint Integrity Analyzer — Reference Solution

Implements VDI 2230-based analysis for bolted joints with gnuplot diagram
generation, batch processing, and SQLite logging with triggers and views.
"""


import csv
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("/app/data")
DB_PATH = "/app/analysis.db"
DIAGRAM_DIR = "/app/diagrams"

TEMP_LIMITS = {
    "ISO898": 150,
    "A193_B7": 400,
    "A193_B16": 500,
    "A286": 700,
    "Inconel718": 760,
}

EMBEDDING_PER_INTERFACE_MM = {
    "fine": 0.002,
    "normal": 0.003,
    "rough": 0.005,
}

BOLT_CTE_PPM = {
    "ISO898": 12.0,
    "A193_B7": 12.0,
    "A193_B16": 16.5,
    "A286": 16.0,
    "Inconel718": 13.0,
}

E_BOLT_MPA = 210_000  # Steel bolt Young's modulus


def load_csv(filename):
    with open(DATA_DIR / filename) as f:
        return list(csv.DictReader(f))


def load_thread_data():
    data = {}
    for row in load_csv("thread_data.csv"):
        data[row["size"]] = {
            "d": float(row["d_mm"]),
            "p": float(row["p_mm"]),
            "d2": float(row["d2_mm"]),
            "d3": float(row["d3_mm"]),
            "As": float(row["As_mm2"]),
        }
    return data


def load_bolt_grades():
    data = {}
    for row in load_csv("bolt_grades.csv"):
        data[row["property_class"]] = {
            "yield_MPa": float(row["yield_MPa"]),
            "uts_MPa": float(row["uts_MPa"]),
        }
    return data


def load_nut_proof_loads():
    data = {}
    for row in load_csv("nut_proof_loads.csv"):
        key = (row["size"], int(row["nut_class"]), row["standard"])
        data[key] = float(row["proof_load_N"])
    return data


def compute_preload_N(torque_Nm, d2_mm, p_mm, mu_t, mu_b, Dkm_mm):
    """Long-form torque-tension equation."""
    cos30 = math.cos(math.radians(30))
    factor_mm = (
        p_mm / (2 * math.pi)
        + mu_t * d2_mm / (2 * cos30)
        + mu_b * Dkm_mm / 2
    )
    F_N = torque_Nm / (factor_mm * 1e-3)
    return F_N


def compute_bolt_stiffness(d_mm, As_mm2, grip_mm):
    """Compliance-summation model."""
    A_shank = math.pi / 4 * d_mm**2
    head_compliance = (0.4 * d_mm) / (E_BOLT_MPA * A_shank)
    grip_compliance = grip_mm / (E_BOLT_MPA * As_mm2)
    nut_compliance = (0.4 * d_mm) / (E_BOLT_MPA * As_mm2)
    return 1.0 / (head_compliance + grip_compliance + nut_compliance)


def compute_joint_stiffness(d_mm, grip_mm, E_joint_MPa):
    """Roetscher frustum model for symmetric through-bolt joint."""
    d_w = 1.5 * d_mm
    d_h = d_mm + 1.0
    alpha_rad = math.radians(30)
    tan_a = math.tan(alpha_rad)
    D_A = d_w + grip_mm * tan_a
    numerator = E_joint_MPa * math.pi * d_h * tan_a
    log_arg = ((D_A - d_h) * (d_w + d_h)) / ((D_A + d_h) * (d_w - d_h))
    K_frustum = numerator / math.log(log_arg)
    return K_frustum / 2.0


def normal_cdf(x):
    """Standard normal CDF."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def check_washer(bolt_class_str, washer_present, washer_HV):
    """ISO 898-3 washer hardness requirements."""
    grade = float(bolt_class_str)
    if grade >= 12.0:
        min_hv = 380
    elif grade >= 10.0:
        min_hv = 300
    elif grade >= 8.0:
        min_hv = 200
    else:
        return True
    if not washer_present:
        return False
    return washer_HV >= min_hv


def create_db_schema(conn):
    """Create table, trigger, and view if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            bolt_size TEXT,
            property_class TEXT,
            grip_length_mm REAL,
            design_margin REAL,
            probability_of_failure REAL,
            nut_compatible INTEGER,
            washer_suitable INTEGER,
            temperature_suitable INTEGER,
            risk_category TEXT,
            full_result TEXT
        )
    """)

    existing_trigger = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name='classify_risk'"
    ).fetchone()
    if not existing_trigger:
        conn.execute("""
            CREATE TRIGGER classify_risk AFTER INSERT ON analyses
            BEGIN
                UPDATE analyses SET risk_category =
                    CASE
                        WHEN NEW.design_margin < 0.8 THEN 'critical'
                        WHEN NEW.design_margin < 1.0 THEN 'marginal'
                        WHEN NEW.design_margin < 2.0 THEN 'acceptable'
                        ELSE 'over_designed'
                    END
                WHERE id = NEW.id;
            END
        """)

    existing_view = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='risk_summary'"
    ).fetchone()
    if not existing_view:
        conn.execute("""
            CREATE VIEW risk_summary AS
            SELECT
                bolt_size,
                COUNT(*) AS analysis_count,
                AVG(design_margin) AS avg_design_margin,
                MIN(design_margin) AS min_design_margin,
                MAX(probability_of_failure) AS max_pof
            FROM analyses
            GROUP BY bolt_size
        """)

    conn.commit()


def log_to_db(spec, result):
    """Append analysis result to SQLite database. Returns row ID."""
    conn = sqlite3.connect(DB_PATH)
    create_db_schema(conn)
    cursor = conn.execute(
        """INSERT INTO analyses
           (timestamp, bolt_size, property_class, grip_length_mm, design_margin,
            probability_of_failure, nut_compatible, washer_suitable,
            temperature_suitable, full_result)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            spec["bolt"]["size"],
            spec["bolt"]["property_class"],
            float(spec["bolt"]["grip_length_mm"]),
            result["design_margin"],
            result["probability_of_failure"],
            1 if result["nut_compatible"] else 0,
            1 if result["washer_suitable"] else 0,
            1 if result["temperature_suitable"] else 0,
            json.dumps(result),
        ),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def generate_diagram(bolt_size, result, row_id):
    """Generate gnuplot SVG diagram showing preload components."""
    os.makedirs(DIAGRAM_DIR, exist_ok=True)
    svg_path = f"{DIAGRAM_DIR}/{bolt_size}_{row_id}.svg"
    gp_path = f"{DIAGRAM_DIR}/{bolt_size}_{row_id}.gp"

    embed = result["embedding_loss_kN"]
    shear = result["shear_grip_requirement_kN"]
    axial = result["axial_clamp_reduction_kN"]
    thermal = max(0.0, -result["differential_thermal_load_kN"])
    min_pre = result["min_preload_kN"]
    max_pre = result["max_preload_kN"]

    top = max(max_pre * 1.3, 1.0)
    level1 = embed
    level2 = level1 + shear
    level3 = level2 + axial
    level4 = level3 + thermal

    script = f"""set terminal svg size 640 480 enhanced
set output "{svg_path}"
set title "{bolt_size} Joint Load Distribution"
set ylabel "Force (kN)"
set style fill solid 0.7 border -1
set boxwidth 0.6
set xrange [-1:2]
set yrange [0:{top:.1f}]
unset xtics
set key outside right top

set object 1 rect from -0.3,0 to 0.3,{level1:.4f} fc rgb "#e74c3c" fs solid 0.7
set object 2 rect from -0.3,{level1:.4f} to 0.3,{level2:.4f} fc rgb "#3498db" fs solid 0.7
set object 3 rect from -0.3,{level2:.4f} to 0.3,{level3:.4f} fc rgb "#2ecc71" fs solid 0.7
set object 4 rect from -0.3,{level3:.4f} to 0.3,{level4:.4f} fc rgb "#f39c12" fs solid 0.7

set arrow 1 from -0.4,{min_pre:.4f} to 0.4,{min_pre:.4f} nohead lw 2 lc rgb "#000000"
set label 1 "Min F_V = {min_pre:.1f} kN" at 0.5,{min_pre:.4f}
set arrow 2 from -0.4,{max_pre:.4f} to 0.4,{max_pre:.4f} nohead lw 2 dt 2 lc rgb "#555555"
set label 2 "Max F_V = {max_pre:.1f} kN" at 0.5,{max_pre:.4f}

plot 1/0 notitle
"""

    with open(gp_path, "w") as f:
        f.write(script)

    subprocess.run(["gnuplot", gp_path], check=True, capture_output=True)
    return svg_path


def analyze(spec):
    """Run a complete VDI 2230 analysis on one specification."""
    threads = load_thread_data()
    grades = load_bolt_grades()
    nut_loads = load_nut_proof_loads()

    # ── Extract spec ──
    bolt_size = spec["bolt"]["size"]
    bolt_class = spec["bolt"]["property_class"]
    grip_mm = float(spec["bolt"]["grip_length_mm"])

    nut_std = spec["nut"]["standard"]
    nut_class = int(spec["nut"]["property_class"])

    num_if = int(spec["joint"]["num_interfaces"])
    if_friction = float(spec["joint"]["interface_friction"])
    roughness = spec["joint"]["surface_roughness_class"]
    E_joint_GPa = float(spec["joint"]["material_elastic_modulus_GPa"])
    joint_cte = float(spec["joint"]["cte_ppm_per_K"])

    washer_present = bool(spec["washer"]["present"])
    washer_HV = int(spec["washer"]["hardness_HV"])

    axial_kN = float(spec["loading"]["axial_kN"])
    shear_kN = float(spec["loading"]["shear_kN"])

    torque_Nm = float(spec["tightening"]["torque_Nm"])
    mu_t_min = float(spec["tightening"]["thread_friction_min"])
    mu_t_max = float(spec["tightening"]["thread_friction_max"])
    mu_b_min = float(spec["tightening"]["bearing_friction_min"])
    mu_b_max = float(spec["tightening"]["bearing_friction_max"])

    temp_C = float(spec["environment"]["temperature_C"])
    bolt_mat = spec["environment"]["bolt_material"]

    shim_present = bool(spec["friction_shim"]["present"])
    shim_mu = float(spec["friction_shim"]["friction_coefficient"])

    # ── Thread geometry ──
    td = threads[bolt_size]
    d = td["d"]
    p = td["p"]
    d2 = td["d2"]
    As = td["As"]

    # ── Bolt grade ──
    gd = grades[bolt_class]
    uts_MPa = gd["uts_MPa"]

    # ── Mean bearing diameter ──
    d_hole = d + 1.0
    d_bearing = 1.5 * d
    Dkm = (d_hole + d_bearing) / 2.0

    # ── Preloads ──
    F_max_N = compute_preload_N(torque_Nm, d2, p, mu_t_min, mu_b_min, Dkm)
    F_min_N = compute_preload_N(torque_Nm, d2, p, mu_t_max, mu_b_max, Dkm)
    max_preload_kN = F_max_N / 1000.0
    min_preload_kN = F_min_N / 1000.0

    # ── Stiffness ──
    E_joint_MPa = E_joint_GPa * 1000.0
    Kb = compute_bolt_stiffness(d, As, grip_mm)
    Kj = compute_joint_stiffness(d, grip_mm, E_joint_MPa)
    Kb_kN_mm = Kb / 1000.0
    Kj_kN_mm = Kj / 1000.0

    # ── Load factor ──
    phi = Kb / (Kb + Kj)

    # ── Embedding loss ──
    embed_per_if_mm = EMBEDDING_PER_INTERFACE_MM[roughness]
    total_embed_mm = embed_per_if_mm * num_if
    K_series = (Kb * Kj) / (Kb + Kj)
    embedding_loss_kN = (total_embed_mm * K_series) / 1000.0

    # ── Differential thermal expansion ──
    bolt_cte = BOLT_CTE_PPM[bolt_mat]
    delta_T = temp_C - 20.0  # assembly reference temperature 20 C
    differential_thermal_N = (
        (joint_cte - bolt_cte) * 1e-6 * delta_T * grip_mm * K_series
    )
    differential_thermal_kN = differential_thermal_N / 1000.0

    # ── Shear grip requirement ──
    effective_friction = shim_mu if shim_present else if_friction
    shear_grip_kN = shear_kN / effective_friction if effective_friction > 0 else 0.0

    # ── Axial clamp reduction ──
    axial_clamp_kN = (1.0 - phi) * axial_kN

    # ── Total preload requirement (thermal loss added if negative) ──
    thermal_loss_kN = max(0.0, -differential_thermal_kN)
    total_req_kN = embedding_loss_kN + axial_clamp_kN + shear_grip_kN + thermal_loss_kN

    # ── Design margin ──
    if total_req_kN > 1e-9:
        design_margin = min_preload_kN / total_req_kN
    else:
        design_margin = 999.0

    # ── Nut compatibility ──
    nut_key = (bolt_size, nut_class, nut_std)
    nut_proof_N = nut_loads.get(nut_key, 0.0)
    bolt_uts_N = As * uts_MPa
    nut_compatible = nut_proof_N >= bolt_uts_N

    # ── Washer suitability ──
    washer_suitable = check_washer(bolt_class, washer_present, washer_HV)

    # ── Temperature suitability ──
    temp_limit = TEMP_LIMITS.get(bolt_mat, 150)
    temperature_suitable = temp_C <= temp_limit

    # ── Thread root radius range ──
    thread_root_min = 0.125 * p
    thread_root_max = 0.144 * p

    # ── Probability of failure ──
    preload_mean = (max_preload_kN + min_preload_kN) / 2.0
    preload_std = (max_preload_kN - min_preload_kN) / 6.0
    req_mean = total_req_kN
    req_std = 0.10 * total_req_kN

    combined_std = math.sqrt(preload_std**2 + req_std**2)
    if combined_std > 1e-12:
        Z = (preload_mean - req_mean) / combined_std
        pof = 1.0 - normal_cdf(Z)
    else:
        pof = 0.0 if preload_mean >= req_mean else 1.0

    # ── Build output ──
    result = {
        "stress_area_mm2": round(As, 2),
        "max_preload_kN": round(max_preload_kN, 2),
        "min_preload_kN": round(min_preload_kN, 2),
        "bolt_stiffness_kN_per_mm": round(Kb_kN_mm, 2),
        "joint_stiffness_kN_per_mm": round(Kj_kN_mm, 2),
        "load_factor_phi": round(phi, 4),
        "embedding_loss_kN": round(embedding_loss_kN, 2),
        "differential_thermal_load_kN": round(differential_thermal_kN, 2),
        "shear_grip_requirement_kN": round(shear_grip_kN, 2),
        "axial_clamp_reduction_kN": round(axial_clamp_kN, 2),
        "total_preload_requirement_kN": round(total_req_kN, 2),
        "design_margin": round(design_margin, 4),
        "nut_compatible": nut_compatible,
        "washer_suitable": washer_suitable,
        "temperature_suitable": temperature_suitable,
        "thread_root_radius_range_mm": [
            round(thread_root_min, 4),
            round(thread_root_max, 4),
        ],
        "probability_of_failure": round(pof, 6),
        "diagram_path": "",
    }

    # ── Log to SQLite ──
    row_id = log_to_db(spec, result)

    # ── Generate gnuplot diagram ──
    svg_path = generate_diagram(bolt_size, result, row_id)
    result["diagram_path"] = svg_path

    # ── Update DB full_result with diagram_path ──
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE analyses SET full_result = ? WHERE id = ?",
        (json.dumps(result), row_id),
    )
    conn.commit()
    conn.close()

    return result


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: bjoint <spec.toml> | bjoint --batch <dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    if sys.argv[1] == "--batch":
        if len(sys.argv) != 3:
            print("Usage: bjoint --batch <dir>", file=sys.stderr)
            sys.exit(1)
        batch_dir = Path(sys.argv[2])
        toml_files = sorted(batch_dir.glob("*.toml"))
        for toml_file in toml_files:
            with open(toml_file, "rb") as f:
                spec = tomllib.load(f)
            result = analyze(spec)
            result["source_file"] = toml_file.name
            print(json.dumps(result))
    else:
        with open(sys.argv[1], "rb") as f:
            spec = tomllib.load(f)
        result = analyze(spec)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
