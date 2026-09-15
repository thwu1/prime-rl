#!/usr/bin/env python3
"""
Solution for the multiphase flow V&V pipeline task.
Computes correct verification results, queries normalized SQLite DB,
classifies historical runs, and exports convergence data.
"""

import json
import math
import sqlite3
import tomllib


def load_config():
    with open("/app/config.toml", "rb") as f:
        return tomllib.load(f)


# =====================================================================
# Correct physics implementations
# =====================================================================

def correct_drag(config):
    """Schiller-Naumann with correct exponent 0.687."""
    results = {}
    for Re in config["drag"]["reynolds_numbers"]:
        if Re > 1000.0:
            results[f"Re_{Re}"] = 0.44
        else:
            results[f"Re_{Re}"] = (24.0 / Re) * (1.0 + 0.15 * Re ** 0.687)
    return results


def correct_settling(config):
    """Settling analysis with correct Rankine-Hugoniot: eps_g^(n+1)."""
    p = config["physical"]
    g = p["gravity"]
    rho_g = p["fluid_density"]
    rho_s = p["solid_density"]
    mu = p["fluid_viscosity"]
    d_p = p["particle_diameter"]
    n = p["richardson_zaki_n"]
    eps_max = p["max_packing"]
    y0 = p["initial_bed_top"]
    t = p["eval_time"]

    u_t = g * (rho_s - rho_g) * d_p ** 2 / (18.0 * mu)
    Re_t = rho_g * u_t * d_p / mu

    fronts = []
    for eps_s0 in p["concentrations"]:
        eps_g0 = 1.0 - eps_s0
        u_r = u_t * eps_g0 ** n
        sigma_s = -u_t * eps_g0 ** (n + 1)
        sigma_f = u_t * eps_s0 * eps_g0 ** (n + 1) / (eps_max - eps_s0)
        fronts.append({
            "eps_s0": eps_s0,
            "settling_front": y0 + sigma_s * t,
            "filling_front": sigma_f * t,
            "hindered_velocity": u_r,
        })

    return {"terminal_velocity": u_t, "reynolds_number": Re_t, "fronts": fronts}


def correct_mms(config):
    """MMS verification with correct (positive) source term."""
    mms = config["mms"]
    alpha = mms["diffusivity"]
    A = mms["amplitude_A"]
    B = mms["amplitude_B"]
    k = mms["wavenumber"]
    L = mms["domain_length"]
    grid_levels = mms["grid_levels"]

    kpi_L = k * math.pi / L
    l2_norms = {}

    for N in grid_levels:
        h = L / N
        n_int = N - 1
        x = [(i + 1) * h for i in range(n_int)]
        u_exact = [A + B * math.sin(kpi_L * xi) for xi in x]

        source = [alpha * B * kpi_L ** 2 * math.sin(kpi_L * xi) for xi in x]

        u_left = A + B * math.sin(0.0)
        u_right = A + B * math.sin(kpi_L * L)

        coeff = alpha / h ** 2
        b_d = [2.0 * coeff] * n_int
        c_d = [-coeff] * n_int
        a_d = [-coeff] * n_int
        d_v = list(source)
        d_v[0] += coeff * u_left
        d_v[-1] += coeff * u_right

        for i in range(1, n_int):
            w = a_d[i] / b_d[i - 1]
            b_d[i] -= w * c_d[i - 1]
            d_v[i] -= w * d_v[i - 1]

        u_num = [0.0] * n_int
        u_num[-1] = d_v[-1] / b_d[-1]
        for i in range(n_int - 2, -1, -1):
            u_num[i] = (d_v[i] - c_d[i] * u_num[i + 1]) / b_d[i]

        err_sq = sum((u_num[j] - u_exact[j]) ** 2 for j in range(n_int))
        l2_norms[str(N)] = math.sqrt(err_sq / n_int)

    orders = {}
    sl = sorted(grid_levels)
    for i in range(len(sl) - 1):
        N1, N2 = sl[i], sl[i + 1]
        r = N2 / N1
        e1, e2 = l2_norms[str(N1)], l2_norms[str(N2)]
        if e1 > 0 and e2 > 0:
            orders[f"{N1}_to_{N2}"] = round(math.log(e1 / e2) / math.log(r), 6)

    return {"l2_norms": l2_norms, "observed_orders": orders}


# =====================================================================
# Historical run classification (normalized DB schema)
# =====================================================================

def classify_runs(ref_drag, ref_settling, ref_mms):
    """Query normalized tables, reconstruct each run's results, classify."""
    conn = sqlite3.connect("/app/history.db")
    c = conn.cursor()

    c.execute("SELECT run_id FROM runs ORDER BY run_id")
    run_ids = [row[0] for row in c.fetchall()]

    audit = {}
    for run_id in run_ids:
        # Reconstruct drag results from drag_data table
        c.execute(
            "SELECT reynolds, cd_value FROM drag_data "
            "WHERE run_id = ? ORDER BY reynolds",
            (run_id,))
        run_drag = {f"Re_{row[0]}": row[1] for row in c.fetchall()}

        # Reconstruct settling results from settling_params + settling_fronts
        c.execute(
            "SELECT terminal_velocity, reynolds_number "
            "FROM settling_params WHERE run_id = ?",
            (run_id,))
        sp_row = c.fetchone()

        c.execute(
            "SELECT eps_s0, settling_front, filling_front, hindered_velocity "
            "FROM settling_fronts WHERE run_id = ? ORDER BY eps_s0",
            (run_id,))
        run_settling_fronts = [{
            "eps_s0": row[0],
            "settling_front": row[1],
            "filling_front": row[2],
            "hindered_velocity": row[3],
        } for row in c.fetchall()]

        # Reconstruct MMS results from mms_data table
        c.execute(
            "SELECT grid_level, l2_norm FROM mms_data "
            "WHERE run_id = ? ORDER BY grid_level",
            (run_id,))
        run_l2 = {str(row[0]): row[1] for row in c.fetchall()}

        # Compute MMS convergence orders from l2 norms
        run_orders = {}
        sl = sorted(int(k) for k in run_l2.keys())
        for i in range(len(sl) - 1):
            N1, N2 = sl[i], sl[i + 1]
            r = N2 / N1
            e1, e2 = run_l2[str(N1)], run_l2[str(N2)]
            if e1 > 0 and e2 > 0:
                run_orders[f"{N1}_to_{N2}"] = math.log(e1 / e2) / math.log(r)

        # Check drag coefficients
        drag_err = max(
            abs(run_drag[k] - ref_drag[k]) / max(abs(ref_drag[k]), 1e-12)
            for k in ref_drag if k in run_drag
        )

        # Check settling front positions
        settle_err = 0.0
        for rf, sf in zip(ref_settling["fronts"], run_settling_fronts):
            settle_err = max(
                settle_err,
                abs(rf["settling_front"] - sf["settling_front"]),
                abs(rf["filling_front"] - sf["filling_front"]),
            )

        # Check MMS convergence orders
        mms_ok = True
        if run_orders:
            for k, v in run_orders.items():
                if v < 1.5 or v > 2.5:
                    mms_ok = False
                    break
        else:
            mms_ok = False

        # Classify based on which component has errors
        if drag_err > 0.003:
            audit[str(run_id)] = {
                "status": "defective",
                "defect_type": "drag_correlation_exponent",
            }
        elif settle_err > 0.005:
            audit[str(run_id)] = {
                "status": "defective",
                "defect_type": "settling_shock_wave_velocity",
            }
        elif not mms_ok:
            audit[str(run_id)] = {
                "status": "defective",
                "defect_type": "mms_source_term_sign",
            }
        else:
            audit[str(run_id)] = {
                "status": "correct",
                "defect_type": None,
            }

    conn.close()
    return audit


# =====================================================================
# Convergence data export
# =====================================================================

def write_convergence_tsv(mms_data):
    """Write MMS L2 norms to TSV for gnuplot."""
    with open("/app/convergence.tsv", "w") as f:
        for N in sorted(int(k) for k in mms_data["l2_norms"].keys()):
            f.write(f"{N}\t{mms_data['l2_norms'][str(N)]}\n")


# =====================================================================
# Main
# =====================================================================

def main():
    config = load_config()

    drag = correct_drag(config)
    settling = correct_settling(config)
    mms = correct_mms(config)

    write_convergence_tsv(mms)

    audit = classify_runs(drag, settling, mms)

    report = {
        "verification": {
            "drag": drag,
            "settling": settling,
            "mms": mms,
        },
        "audit": audit,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")
    print("Convergence data written to /app/convergence.tsv")


if __name__ == "__main__":
    main()
