#!/usr/bin/env python3
"""
Complete orbital mechanics mission planner pipeline.
Reads missions from SQLite database, computes results, writes JSON output.
"""

import json
import math
import sqlite3
import sys
import tomllib

sys.path.insert(0, "/app/lib")
import orbital as orb


def load_config(config_path):
    """Load mission configuration from TOML file."""
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    return {
        "db_path": raw["database"]["path"],
        "output_path": raw["output"]["path"],
        "mission_ids": raw["missions"]["ids"],
    }


def query_missions(db_path, mission_ids):
    """Query mission parameters from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results = []
    for mid in mission_ids:
        row = conn.execute(
            """
            SELECT m.id, m.type, b.mu, b.radius, b.j2, m.params
            FROM missions m
            JOIN bodies b ON m.body_id = b.id
            WHERE m.id = ?
            """,
            (mid,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Mission '{mid}' not found in database")
        results.append(dict(row))
    conn.close()
    return results


def dispatch(mission):
    """Dispatch a mission to the appropriate solver and return results dict."""
    mtype = mission["type"]
    mu = mission["mu"]
    body_radius = mission["radius"]
    body_j2 = mission["j2"]
    params = mission["params"]

    if mtype == "rv2coe":
        p, ecc, inc, raan, argp, nu = orb.rv2coe(
            mu, params["r"], params["v"]
        )
        return {
            "p_km": float(p),
            "ecc": float(ecc),
            "inc_deg": math.degrees(inc),
            "raan_deg": math.degrees(raan),
            "argp_deg": math.degrees(argp),
            "nu_deg": math.degrees(nu),
        }

    elif mtype == "coe2rv":
        r, v = orb.coe2rv(
            mu,
            params["p"],
            params["ecc"],
            math.radians(params["inc_deg"]),
            math.radians(params["raan_deg"]),
            math.radians(params["argp_deg"]),
            math.radians(params["nu_deg"]),
        )
        return {"r_km": r.tolist(), "v_km_s": v.tolist()}

    elif mtype == "lambert":
        v0, v = orb.lambert_solve(
            mu,
            params["r0"],
            params["r"],
            params["tof_s"],
            params.get("prograde", True),
        )
        return {"v0_km_s": v0.tolist(), "v_km_s": v.tolist()}

    elif mtype == "hohmann":
        dv_a, dv_b, t = orb.hohmann(mu, params["r_i"], params["r_f"])
        return {
            "dv_a_km_s": dv_a,
            "dv_b_km_s": dv_b,
            "dv_total_km_s": dv_a + dv_b,
            "t_trans_s": t,
        }

    elif mtype == "bielliptic":
        dv_a, dv_b, dv_c, t1, t2 = orb.bielliptic(
            mu, params["r_i"], params["r_b"], params["r_f"]
        )
        return {
            "dv_a_km_s": dv_a,
            "dv_b_km_s": dv_b,
            "dv_c_km_s": dv_c,
            "dv_total_km_s": dv_a + dv_b + dv_c,
            "t_trans1_s": t1,
            "t_trans2_s": t2,
        }

    elif mtype == "j2_correction":
        delta_t, delta_v = orb.j2_correction(
            mu,
            body_radius,
            body_j2,
            params["max_delta_r"],
            params["a"],
            params["ecc"],
            math.radians(params["inc_deg"]),
        )
        return {"delta_t_s": delta_t, "delta_v_km_s": delta_v}

    elif mtype == "plane_change":
        delta_inc = math.radians(
            abs(params["inc_final_deg"] - params["inc_initial_deg"])
        )
        dv = orb.plane_change_dv(mu, params["a"], delta_inc)
        return {"dv_km_s": dv}

    elif mtype == "mission_budget":
        delta_inc = math.radians(params["inc_change_deg"])
        dv_depart, dv_arrive = orb.mission_budget(
            mu, params["r_i"], params["r_f"], delta_inc
        )
        if dv_depart <= dv_arrive:
            optimal = "depart"
            dv_opt = dv_depart
        else:
            optimal = "arrive"
            dv_opt = dv_arrive
        return {
            "dv_depart_total_km_s": dv_depart,
            "dv_arrive_total_km_s": dv_arrive,
            "optimal_strategy": optimal,
            "dv_optimal_km_s": dv_opt,
        }

    else:
        raise ValueError(f"Unknown mission type: {mtype}")


def main():
    config = load_config("/app/config.toml")
    missions_raw = query_missions(config["db_path"], config["mission_ids"])

    results = {}
    for m in missions_raw:
        mid = m["id"]
        m["params"] = json.loads(m["params"])
        results[mid] = dispatch(m)

    with open(config["output_path"], "w") as f:
        json.dump(results, f, indent=2)

    print(f"Processed {len(results)} missions -> {config['output_path']}")


if __name__ == "__main__":
    main()
