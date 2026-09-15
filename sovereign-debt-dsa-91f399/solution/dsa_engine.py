#!/usr/bin/env python3
"""
Sovereign Debt Sustainability Analysis Engine.

"""

import copy
import json
import os
import sqlite3
import subprocess
import tomllib


def load_data_from_sqlite():
    """Load and pivot data from the SQLite dump."""
    conn = sqlite3.connect(":memory:")
    with open("/app/data/schema.sql") as f:
        conn.executescript(f.read())

    countries = {}
    for row in conn.execute(
        "SELECT id, name, base_year, initial_debt_to_gdp, fc_debt_share, endogenous_rate "
        "FROM countries ORDER BY id"
    ):
        countries[row[0]] = {
            "country_name": row[1],
            "base_year": row[2],
            "initial_debt_to_gdp": row[3],
            "fc_debt_share": row[4],
            "endogenous_rate": bool(row[5]),
            "macro_projections": [],
            "contingent_liabilities": {},
            "stress_scenario": {},
        }

    # Pivot EAV macro_variables into per-year dicts
    for cid in countries:
        is_endogenous = countries[cid]["endogenous_rate"]
        rate_var = "base_interest_rate" if is_endogenous else "effective_interest_rate"

        year_offsets = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT year_offset FROM macro_variables "
                "WHERE country_id = ? ORDER BY year_offset",
                (cid,),
            )
        ]

        for yoff in year_offsets:
            var_map = {}
            for vname, val in conn.execute(
                "SELECT variable, value FROM macro_variables "
                "WHERE country_id = ? AND year_offset = ?",
                (cid, yoff),
            ):
                var_map[vname] = val

            ds_row = conn.execute(
                "SELECT amortization, interest_revenue FROM debt_service "
                "WHERE country_id = ? AND year_offset = ?",
                (cid, yoff),
            ).fetchone()

            countries[cid]["macro_projections"].append(
                {
                    "real_gdp_growth": var_map["real_gdp_growth"],
                    "inflation_domestic": var_map["inflation_domestic"],
                    "inflation_foreign": var_map["inflation_foreign"],
                    "interest_rate": var_map[rate_var],
                    "real_exchange_rate_change": var_map["real_exchange_rate_change"],
                    "primary_balance": var_map["primary_balance"],
                    "sfa": var_map["sfa"],
                    "amortization": ds_row[0],
                    "interest_revenue": ds_row[1],
                }
            )

        # Contingent liabilities
        for yoff, amount in conn.execute(
            "SELECT year_offset, shock_amount FROM contingent_liabilities "
            "WHERE country_id = ?",
            (cid,),
        ):
            countries[cid]["contingent_liabilities"][yoff] = amount

        # Stress parameters
        for param, val in conn.execute(
            "SELECT parameter, value FROM stress_parameters WHERE country_id = ?",
            (cid,),
        ):
            countries[cid]["stress_scenario"][param] = val

    conn.close()
    return list(countries.values())


def load_config():
    """Parse TOML configuration."""
    with open("/app/data/config.toml", "rb") as f:
        return tomllib.load(f)


def compute_trajectory(d_init, alpha, projections, contingent_liabilities,
                       risk_premium, precision, pb_adjustment=0.0):
    """Compute baseline trajectory, decomposition, GFN, and debt-stabilizing PB."""
    baseline_trajectory = [d_init]
    decomposition = []
    gfn_list = []
    ds_pb_list = []

    for t, proj in enumerate(projections):
        g = proj["real_gdp_growth"]
        pi_d = proj["inflation_domestic"]
        pi_f = proj["inflation_foreign"]
        i_nom = proj["interest_rate"] + risk_premium
        z = proj["real_exchange_rate_change"]
        pb = proj["primary_balance"] + pb_adjustment
        sfa = proj["sfa"]
        amort = proj["amortization"]
        int_rev = proj["interest_revenue"]

        year_offset = t + 1
        if year_offset in contingent_liabilities:
            sfa += contingent_liabilities[year_offset]

        d_prev = baseline_trajectory[-1]
        d_f_prev = alpha * d_prev

        rho = (1 + g) * (1 + pi_d)
        r = (1 + i_nom) / (1 + pi_d) - 1

        # Decomposition sub-components
        real_interest = r / (1 + g) * d_prev
        real_growth = -g / (1 + g) * d_prev
        real_exchange_rate = z * d_f_prev / ((1 + g) * (1 + pi_f))
        relative_inflation = (pi_d - pi_f) / ((1 + pi_f) * rho) * d_f_prev

        auto = real_interest + real_growth + real_exchange_rate + relative_inflation
        pbc = -pb
        delta_d = auto + pbc + sfa
        d_new = d_prev + delta_d
        baseline_trajectory.append(d_new)

        decomposition.append(
            {
                "year": year_offset,
                "change_in_debt": round(delta_d, precision),
                "real_interest_rate": round(real_interest, precision),
                "real_growth": round(real_growth, precision),
                "real_exchange_rate": round(real_exchange_rate, precision),
                "relative_inflation": round(relative_inflation, precision),
                "automatic_debt_dynamics": round(auto, precision),
                "primary_balance_contribution": round(pbc, precision),
                "sfa": round(sfa, precision),
            }
        )

        # Gross financing needs
        interest_expense = i_nom * d_prev / rho
        gfn = (-pb) + interest_expense + amort - int_rev
        gfn_list.append(round(gfn, precision))

        # Debt-stabilizing primary balance (z=0, sfa=0 assumption)
        ds_pb = (real_interest + real_growth) + relative_inflation
        ds_pb_list.append(round(ds_pb, precision))

    baseline_trajectory = [round(x, precision) for x in baseline_trajectory]

    return baseline_trajectory, decomposition, gfn_list, ds_pb_list


def compute_stress_trajectory(d_init, alpha, projections, contingent_liabilities,
                              stress, risk_premium, config):
    """Compute stress trajectory using baseline-converged risk premium."""
    growth_shock_yrs = set(config["stress_rules"]["growth_shock_years"])
    pb_shock_yrs = set(config["stress_rules"]["primary_balance_shock_years"])
    fx_shock_yrs = set(config["stress_rules"]["fx_shock_years"])
    ir_shock_rule = config["stress_rules"]["interest_rate_shock_years"]
    precision = config["output"]["decimal_places"]

    stressed_trajectory = [d_init]

    for t, proj in enumerate(projections):
        g = proj["real_gdp_growth"]
        pi_d = proj["inflation_domestic"]
        pi_f = proj["inflation_foreign"]
        i_nom = proj["interest_rate"] + risk_premium
        z = proj["real_exchange_rate_change"]
        pb = proj["primary_balance"]
        sfa = proj["sfa"]

        year = t + 1
        if year in contingent_liabilities:
            sfa += contingent_liabilities[year]

        if year in growth_shock_yrs:
            g += stress["growth_shock"]
        if year in pb_shock_yrs:
            pb += stress["pb_shock"]
        if year in fx_shock_yrs:
            z += stress["fx_shock"]
        if ir_shock_rule == "all" or (isinstance(ir_shock_rule, list) and year in ir_shock_rule):
            i_nom += stress["interest_rate_shock"]

        d_prev = stressed_trajectory[-1]
        d_f_prev = alpha * d_prev

        rho = (1 + g) * (1 + pi_d)
        r = (1 + i_nom) / (1 + pi_d) - 1

        rex = z * d_f_prev / ((1 + g) * (1 + pi_f))
        igd = (r - g) / (1 + g) * d_prev
        rinf = (pi_d - pi_f) / ((1 + pi_f) * rho) * d_f_prev

        delta_d = rex + igd + rinf - pb + sfa
        stressed_trajectory.append(d_prev + delta_d)

    return [round(x, precision) for x in stressed_trajectory]


def compute_risk_assessment(d_init, trajectory, gfn_list, config):
    """Determine risk signal from threshold conditions."""
    precision = config["output"]["decimal_places"]
    gfn_threshold = config["risk_thresholds"]["gfn_threshold"]
    debt_ceiling = config["risk_thresholds"]["terminal_debt_ceiling"]
    min_conditions = config["risk_thresholds"]["high_signal_min_conditions"]

    d_T = trajectory[-1]
    avg_gfn = sum(gfn_list) / len(gfn_list)
    debt_stabilizes = d_T <= d_init

    conditions = 0
    if d_T > d_init:
        conditions += 1
    if avg_gfn >= gfn_threshold:
        conditions += 1
    if d_T >= debt_ceiling:
        conditions += 1

    if conditions >= min_conditions:
        signal = "high"
    elif conditions == 0:
        signal = "low"
    else:
        signal = "moderate"

    return {
        "debt_stabilizes_baseline": debt_stabilizes,
        "avg_gfn": round(avg_gfn, precision),
        "terminal_debt": d_T,
        "signal": signal,
    }


def converge_endogenous_rate(d_init, alpha, projections, contingent_liabilities,
                              config, pb_adjustment=0.0):
    """Iterate the trajectory until the terminal debt (and risk premium) converges."""
    beta1 = config["risk_premium"]["beta1"]
    d_threshold = config["risk_premium"]["d_threshold"]
    tol = config["risk_premium"]["convergence_tol"]
    max_iter = config["risk_premium"]["max_iterations"]
    precision = config["output"]["decimal_places"]

    risk_premium = 0.0
    prev_d_T = None

    for iteration in range(1, max_iter + 1):
        trajectory, decomposition, gfn_list, ds_pb_list = compute_trajectory(
            d_init, alpha, projections, contingent_liabilities,
            risk_premium, precision, pb_adjustment
        )
        d_T = trajectory[-1]

        if prev_d_T is not None and abs(d_T - prev_d_T) < tol:
            break

        new_premium = max(0.0, beta1 * (d_T - d_threshold))
        risk_premium = new_premium
        prev_d_T = d_T

    return trajectory, decomposition, gfn_list, ds_pb_list, risk_premium, iteration


def find_consolidation_adjustment(country, config):
    """Binary search for minimum constant PB adjustment to move signal from high to <= moderate."""
    d_init = country["initial_debt_to_gdp"]
    alpha = country["fc_debt_share"]
    projections = country["macro_projections"]
    cl = country["contingent_liabilities"]
    is_endogenous = country["endogenous_rate"]

    search_precision = config["consolidation"]["search_precision"]
    max_adj = config["consolidation"]["max_adjustment"]
    precision = config["output"]["decimal_places"]

    def signal_for_adjustment(adj):
        if is_endogenous:
            traj, _, gfn_list, _, _, _ = converge_endogenous_rate(
                d_init, alpha, projections, cl, config, pb_adjustment=adj
            )
        else:
            traj, _, gfn_list, _ = compute_trajectory(
                d_init, alpha, projections, cl,
                risk_premium=0.0, precision=precision, pb_adjustment=adj
            )
        ra = compute_risk_assessment(d_init, traj, gfn_list, config)
        return ra["signal"], traj[-1]

    lo = 0.0
    hi = max_adj

    while hi - lo > search_precision:
        mid = (lo + hi) / 2.0
        signal, _ = signal_for_adjustment(mid)
        if signal != "high":
            hi = mid
        else:
            lo = mid

    _, terminal_debt = signal_for_adjustment(hi)
    return round(hi, precision), round(terminal_debt, precision)


def compute_dsa(country, config):
    """Run the full debt sustainability analysis for one country."""
    d_init = country["initial_debt_to_gdp"]
    alpha = country["fc_debt_share"]
    projections = country["macro_projections"]
    stress = country["stress_scenario"]
    cl = country["contingent_liabilities"]
    is_endogenous = country["endogenous_rate"]
    precision = config["output"]["decimal_places"]

    # Baseline with possible endogenous rate convergence
    if is_endogenous:
        trajectory, decomposition, gfn_list, ds_pb_list, risk_premium, iterations = \
            converge_endogenous_rate(d_init, alpha, projections, cl, config)
    else:
        trajectory, decomposition, gfn_list, ds_pb_list = compute_trajectory(
            d_init, alpha, projections, cl,
            risk_premium=0.0, precision=precision
        )
        risk_premium = 0.0
        iterations = 1

    # Stress trajectory (uses baseline premium)
    stressed_trajectory = compute_stress_trajectory(
        d_init, alpha, projections, cl, stress, risk_premium, config
    )

    # Risk assessment
    risk_assessment = compute_risk_assessment(d_init, trajectory, gfn_list, config)

    # Consolidation path (only for high-signal countries)
    if risk_assessment["signal"] == "high":
        adj_pp, adj_terminal = find_consolidation_adjustment(country, config)
        consolidation = {
            "required": True,
            "adjustment_pp": adj_pp,
            "adjusted_terminal_debt": adj_terminal,
        }
    else:
        consolidation = {
            "required": False,
            "adjustment_pp": 0.0,
            "adjusted_terminal_debt": 0.0,
        }

    return {
        "country_name": country["country_name"],
        "baseline": {
            "debt_trajectory": trajectory,
            "decomposition": decomposition,
            "gfn": gfn_list,
            "debt_stabilizing_pb": ds_pb_list,
        },
        "stress": {
            "debt_trajectory": stressed_trajectory,
        },
        "risk_assessment": risk_assessment,
        "convergence": {
            "iterations": iterations,
            "risk_premium_applied": round(risk_premium, precision),
        },
        "consolidation": consolidation,
    }


def generate_chart(results, output_path):
    """Write gnuplot data and script, then render a PNG trajectory chart."""
    data_file = "/app/output/trajectories.dat"
    script_file = "/app/output/plot.gp"

    with open(data_file, "w") as f:
        headers = ["Year"]
        for r in results:
            headers.append(f"{r['country_name']}_baseline")
            headers.append(f"{r['country_name']}_stress")
        f.write("\t".join(headers) + "\n")

        num_points = len(results[0]["baseline"]["debt_trajectory"])
        for i in range(num_points):
            row = [str(i)]
            for r in results:
                row.append(str(r["baseline"]["debt_trajectory"][i]))
                row.append(str(r["stress"]["debt_trajectory"][i]))
            f.write("\t".join(row) + "\n")

    plot_cmds = []
    col = 2
    for r in results:
        name = r["country_name"]
        plot_cmds.append(
            f"'{data_file}' using 1:{col} with linespoints title '{name} Baseline'"
        )
        col += 1
        plot_cmds.append(
            f"'{data_file}' using 1:{col} with linespoints title '{name} Stress'"
        )
        col += 1

    script = (
        f"set terminal png size 800,600\n"
        f"set output '{output_path}'\n"
        f"set title 'Debt-to-GDP Trajectories'\n"
        f"set xlabel 'Projection Year'\n"
        f"set ylabel 'Debt-to-GDP (% of GDP)'\n"
        f"set grid\n"
        f"set key outside right top\n"
        f"plot {', '.join(plot_cmds)}\n"
    )

    with open(script_file, "w") as f:
        f.write(script)

    subprocess.run(["gnuplot", script_file], check=True)


def main():
    config = load_config()
    countries = load_data_from_sqlite()
    results = [compute_dsa(c, config) for c in countries]

    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)

    generate_chart(results, "/app/output/trajectories.png")


if __name__ == "__main__":
    main()
