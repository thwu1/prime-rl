#!/usr/bin/env python3
"""

Reference solution: Ternary LLE solver using original UNIFAC model.
Parameters extracted from a normalized SQLite database.
Ternary phase diagram generated via gnuplot.
"""

import json
import math
import sqlite3
import subprocess
import sys

import numpy as np
from scipy.optimize import fsolve, brentq


# -----------------------------------------------------------------------
# Database parameter extraction
# -----------------------------------------------------------------------

def load_params_from_sql(sql_path="/app/unifac_params.sql"):
    """Load UNIFAC parameters from SQL dump into in-memory SQLite.
    Returns (subgroups, interactions, conn) where conn is kept open
    for compound lookups."""
    conn = sqlite3.connect(":memory:")
    with open(sql_path) as f:
        conn.executescript(f.read())
    return conn


def query_subgroups(conn):
    """Returns dict: subgroup_name -> {main_group, Rk, Qk}."""
    rows = conn.execute(
        "SELECT s.name, mg.name, s.rk, s.qk "
        "FROM subgroups s JOIN main_groups mg ON s.main_group_id = mg.id"
    ).fetchall()
    return {r[0]: {"main_group": r[1], "Rk": r[2], "Qk": r[3]} for r in rows}


def query_interactions(conn):
    """Returns dict: (main_group_m, main_group_n) -> a_mn.
    Uses highest-priority source for each pair via correlated subquery."""
    rows = conn.execute("""
        SELECT mg1.name, mg2.name, ip.a_value
        FROM interaction_params ip
        JOIN main_groups mg1 ON ip.source_group_id = mg1.id
        JOIN main_groups mg2 ON ip.target_group_id = mg2.id
        JOIN parameter_sources ps ON ip.param_source_id = ps.id
        WHERE ps.priority = (
            SELECT MAX(ps2.priority)
            FROM interaction_params ip2
            JOIN parameter_sources ps2 ON ip2.param_source_id = ps2.id
            WHERE ip2.source_group_id = ip.source_group_id
              AND ip2.target_group_id = ip.target_group_id
        )
    """).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def query_compound_groups(conn, compound_names):
    """Returns list of component dicts: [{name, groups: {subgroup: count}}].
    Looks up each compound by name in the compounds table."""
    components = []
    for name in compound_names:
        row = conn.execute(
            "SELECT id FROM compounds WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Compound '{name}' not found in database")
        cid = row[0]
        groups = {}
        for sg_name, cnt in conn.execute(
            "SELECT s.name, cs.count "
            "FROM compound_subgroups cs "
            "JOIN subgroups s ON cs.subgroup_id = s.id "
            "WHERE cs.compound_id = ?",
            (cid,),
        ):
            groups[sg_name] = cnt
        components.append({"name": name, "groups": groups})
    return components


# -----------------------------------------------------------------------
# UNIFAC activity-coefficient model
# -----------------------------------------------------------------------

def unifac_gamma(x, components, subgroups, interactions, T):
    nc = len(components)
    x = np.asarray(x, dtype=float).copy()
    x = np.maximum(x, 1e-15)
    x /= x.sum()

    r = np.zeros(nc)
    q = np.zeros(nc)
    for i, comp in enumerate(components):
        for sg_name, cnt in comp["groups"].items():
            r[i] += cnt * subgroups[sg_name]["Rk"]
            q[i] += cnt * subgroups[sg_name]["Qk"]

    # Combinatorial
    sum_rx = r @ x
    sum_qx = q @ x
    phi = r * x / sum_rx
    theta = q * x / sum_qx

    ln_gC = np.zeros(nc)
    for i in range(nc):
        px = phi[i] / x[i]
        pt = phi[i] / theta[i]
        ln_gC[i] = (math.log(px) + 1.0 - px
                     - 5.0 * q[i] * (math.log(pt) + 1.0 - pt))

    # Residual
    all_sgs = []
    sg_set = set()
    for comp in components:
        for sg in comp["groups"]:
            if sg not in sg_set:
                all_sgs.append(sg)
                sg_set.add(sg)
    nsg = len(all_sgs)
    sg_idx = {sg: k for k, sg in enumerate(all_sgs)}
    main_g = [subgroups[sg]["main_group"] for sg in all_sgs]
    Qk = np.array([subgroups[sg]["Qk"] for sg in all_sgs])

    nu = np.zeros((nc, nsg))
    for i, comp in enumerate(components):
        for sg_name, cnt in comp["groups"].items():
            nu[i, sg_idx[sg_name]] = cnt

    psi = np.ones((nsg, nsg))
    for m in range(nsg):
        for n in range(nsg):
            a_mn = interactions.get((main_g[m], main_g[n]), 0.0)
            psi[m, n] = math.exp(-a_mn / T)

    def _ln_Gamma(Xk):
        sQX = Qk @ Xk
        if sQX < 1e-30:
            return np.zeros(nsg)
        th = Qk * Xk / sQX
        ln_G = np.zeros(nsg)
        denom_m = np.array([th @ psi[:, m] for m in range(nsg)])
        for k in range(nsg):
            s1 = th @ psi[:, k]
            s2 = 0.0
            for m in range(nsg):
                if denom_m[m] > 1e-30:
                    s2 += th[m] * psi[k, m] / denom_m[m]
            if s1 > 1e-30:
                ln_G[k] = Qk[k] * (1.0 - math.log(s1) - s2)
        return ln_G

    Xmix = np.zeros(nsg)
    for k in range(nsg):
        for i in range(nc):
            Xmix[k] += nu[i, k] * x[i]
    Xmix_tot = Xmix.sum()
    if Xmix_tot > 0:
        Xmix /= Xmix_tot
    ln_G_mix = _ln_Gamma(Xmix)

    ln_G_pure = np.zeros((nc, nsg))
    for i in range(nc):
        tot_i = nu[i].sum()
        Xp = nu[i] / tot_i if tot_i > 0 else np.zeros(nsg)
        ln_G_pure[i] = _ln_Gamma(Xp)

    ln_gR = np.zeros(nc)
    for i in range(nc):
        for k in range(nsg):
            ln_gR[i] += nu[i, k] * (ln_G_mix[k] - ln_G_pure[i, k])

    return np.exp(ln_gC + ln_gR)


# -----------------------------------------------------------------------
# LLE flash solver
# -----------------------------------------------------------------------

def _rachford_rice(beta, z, K):
    return sum(z[i] * (K[i] - 1.0) / (1.0 + beta * (K[i] - 1.0))
               for i in range(len(z)))


def lle_flash(z, components, subgroups, interactions, T,
              max_ss=600, tol_ss=1e-11, tol_newton=1e-12):
    nc = len(z)
    z = np.asarray(z, dtype=float)

    x_I = np.array([0.98, z[1] * 0.3 if z[1] > 1e-10 else 1e-6, 0.0])
    x_I[2] = 1.0 - x_I[0] - x_I[1]
    if x_I[2] < 1e-6:
        x_I[2] = 1e-6
        x_I /= x_I.sum()

    x_II = np.array([0.0, z[1] * 0.7 if z[1] > 1e-10 else 1e-6, 0.95])
    x_II[0] = 1.0 - x_II[1] - x_II[2]
    if x_II[0] < 1e-6:
        x_II[0] = 1e-6
        x_II /= x_II.sum()

    beta = 0.5

    for it in range(max_ss):
        gI = unifac_gamma(x_I, components, subgroups, interactions, T)
        gII = unifac_gamma(x_II, components, subgroups, interactions, T)
        K = gI / gII

        try:
            fl = _rachford_rice(1e-12, z, K)
            fh = _rachford_rice(1.0 - 1e-12, z, K)
            if fl * fh < 0:
                beta = brentq(lambda b: _rachford_rice(b, z, K),
                              1e-12, 1.0 - 1e-12)
            else:
                beta = 0.5
        except Exception:
            beta = 0.5

        x_I_new = z / (1.0 + beta * (K - 1.0))
        x_II_new = K * x_I_new

        x_I_new = np.maximum(x_I_new, 1e-15)
        x_II_new = np.maximum(x_II_new, 1e-15)
        x_I_new /= x_I_new.sum()
        x_II_new /= x_II_new.sum()

        diff = max(np.max(np.abs(x_I_new - x_I)),
                   np.max(np.abs(x_II_new - x_II)))

        alpha = min(1.0, 0.2 + 0.8 * it / 80.0)
        x_I = alpha * x_I_new + (1.0 - alpha) * x_I
        x_II = alpha * x_II_new + (1.0 - alpha) * x_II
        x_I /= x_I.sum()
        x_II /= x_II.sum()

        if diff < tol_ss and it > 30:
            break

    # Newton refinement
    def equations(v):
        x1I, x2I, x1II, x2II, b = v
        x3I = 1.0 - x1I - x2I
        x3II = 1.0 - x1II - x2II
        xI = np.array([x1I, x2I, x3I])
        xII = np.array([x1II, x2II, x3II])
        xI = np.maximum(xI, 1e-15)
        xII = np.maximum(xII, 1e-15)
        gI = unifac_gamma(xI, components, subgroups, interactions, T)
        gII = unifac_gamma(xII, components, subgroups, interactions, T)
        return [
            xI[0] * gI[0] - xII[0] * gII[0],
            xI[1] * gI[1] - xII[1] * gII[1],
            xI[2] * gI[2] - xII[2] * gII[2],
            z[0] - b * xI[0] - (1.0 - b) * xII[0],
            z[1] - b * xI[1] - (1.0 - b) * xII[1],
        ]

    x0 = [x_I[0], x_I[1], x_II[0], x_II[1], beta]
    try:
        sol, info, ier, msg = fsolve(equations, x0, full_output=True)
        if ier == 1:
            x1I, x2I, x1II, x2II, beta = sol
            x_I = np.array([x1I, x2I, 1.0 - x1I - x2I])
            x_II = np.array([x1II, x2II, 1.0 - x1II - x2II])
    except Exception:
        pass

    # Label phases
    gI = unifac_gamma(x_I, components, subgroups, interactions, T)
    gII = unifac_gamma(x_II, components, subgroups, interactions, T)

    if x_I[0] >= x_II[0]:
        x_aq, x_org = x_I.copy(), x_II.copy()
        g_aq, g_org = gI.copy(), gII.copy()
    else:
        x_aq, x_org = x_II.copy(), x_I.copy()
        g_aq, g_org = gII.copy(), gI.copy()

    denom = x_aq[0] - x_org[0]
    if abs(denom) > 1e-10:
        beta_aq = (z[0] - x_org[0]) / denom
    else:
        beta_aq = 0.5
    beta_aq = max(1e-6, min(1.0 - 1e-6, beta_aq))

    return x_aq, x_org, beta_aq, g_aq, g_org


def binary_mutual_solubility(components, subgroups, interactions, T):
    z = np.array([0.5, 1e-12, 0.5 - 1e-12])
    x_aq, x_org, _, _, _ = lle_flash(
        z, components, subgroups, interactions, T,
        max_ss=800, tol_ss=1e-12,
    )
    return float(x_org[0]), float(x_aq[2])


# -----------------------------------------------------------------------
# Gnuplot ternary phase diagram
# -----------------------------------------------------------------------

def generate_phase_diagram(tie_lines, comp_names):
    """Generate a ternary phase diagram SVG using gnuplot."""
    sqrt3_2 = math.sqrt(3.0) / 2.0

    # Write tie-line data in Cartesian coordinates
    # Transform: X = x_acetone + x_toluene*0.5, Y = x_toluene*sqrt(3)/2
    with open("/app/tielines.dat", "w") as f:
        for tl in tie_lines:
            aq = tl["aqueous_phase"]
            org = tl["organic_phase"]
            x1 = aq[1] + aq[2] * 0.5
            y1 = aq[2] * sqrt3_2
            x2 = org[1] + org[2] * 0.5
            y2 = org[2] * sqrt3_2
            f.write(f"{x1:.8f} {y1:.8f} {x2:.8f} {y2:.8f}\n")

    gp_script = f"""set terminal svg size 800 700 enhanced font 'Arial,14'
set output '/app/phase_diagram.svg'
unset border
unset tics
unset key
set size ratio {sqrt3_2:.6f}
set xrange [-0.15:1.15]
set yrange [-0.10:1.00]

# Equilateral triangle boundary
set arrow from 0,0 to 1,0 nohead lw 2 lc rgb "black" front
set arrow from 1,0 to 0.5,{sqrt3_2:.6f} nohead lw 2 lc rgb "black" front
set arrow from 0.5,{sqrt3_2:.6f} to 0,0 nohead lw 2 lc rgb "black" front

# Vertex labels
set label "{comp_names[0]}" at -0.08,-0.04 font 'Arial,14'
set label "{comp_names[1]}" at 1.02,-0.04 font 'Arial,14'
set label "{comp_names[2]}" at 0.40,{sqrt3_2 + 0.04:.6f} font 'Arial,14'

set title "Ternary LLE Phase Diagram at 298.15 K" font 'Arial,16'

plot '/app/tielines.dat' using 1:2:($3-$1):($4-$2) with vectors nohead lw 1.5 lc rgb "blue", \\
     '/app/tielines.dat' using 1:2 with points pt 7 ps 1.5 lc rgb "red", \\
     '/app/tielines.dat' using 3:4 with points pt 7 ps 1.5 lc rgb "red"
"""
    with open("/app/ternary.gp", "w") as f:
        f.write(gp_script)

    subprocess.run(["gnuplot", "/app/ternary.gp"], check=True)
    print("Phase diagram written to /app/phase_diagram.svg")


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main():
    # Load system specification
    with open("/app/system.json") as f:
        system = json.load(f)

    T = system["temperature_K"]
    comp_names = system["components"]
    feeds = system["feeds"]

    # Extract UNIFAC parameters from SQL database
    conn = load_params_from_sql()
    sg = query_subgroups(conn)
    inter = query_interactions(conn)
    comps = query_compound_groups(conn, comp_names)
    conn.close()

    # Solve LLE for each feed
    results = {
        "system": {
            "components": comp_names,
            "temperature_K": T,
        },
        "tie_lines": [],
    }

    for feed in feeds:
        z = np.array(feed)
        x_aq, x_org, beta, g_aq, g_org = lle_flash(
            z, comps, sg, inter, T)

        K = {}
        for i, name in enumerate(comp_names):
            K[name] = float(x_org[i] / x_aq[i]) if x_aq[i] > 1e-15 else 1e15

        S = K[comp_names[1]] / K[comp_names[0]]

        results["tie_lines"].append({
            "feed": feed,
            "aqueous_phase": x_aq.tolist(),
            "organic_phase": x_org.tolist(),
            "activity_coefficients_aqueous": g_aq.tolist(),
            "activity_coefficients_organic": g_org.tolist(),
            "phase_fraction_aqueous": float(beta),
            "distribution_coefficients": K,
            "selectivity_solute_over_carrier": float(S),
        })

    # Binary mutual solubility
    w_in_org, t_in_aq = binary_mutual_solubility(comps, sg, inter, T)
    results["binary_mutual_solubility"] = {
        "water_in_organic": w_in_org,
        "toluene_in_aqueous": t_in_aq,
    }

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")

    # Generate ternary phase diagram via gnuplot
    generate_phase_diagram(results["tie_lines"], comp_names)


if __name__ == "__main__":
    main()
