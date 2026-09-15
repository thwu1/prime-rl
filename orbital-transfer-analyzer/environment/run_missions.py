#!/usr/bin/env python3
"""
Orbital mechanics mission planner pipeline.
Reads missions from SQLite database, computes results, writes JSON output.
"""

import json
import math
import sys

sys.path.insert(0, "/app/lib")


def load_config(config_path):
    """Load mission configuration from TOML file.

    Must return dict with keys:
        db_path (str), output_path (str), mission_ids (list of str)
    """
    # TODO: Implement TOML config loading
    # Hint: Python 3.11+ has tomllib in the standard library
    raise NotImplementedError("Config loading not implemented")


def query_missions(db_path, mission_ids):
    """Query mission parameters from SQLite database.

    Must join missions table with bodies table to get mu, radius, j2.

    Returns list of dicts with keys:
        id, type, mu, radius, j2, params (JSON string)
    """
    # TODO: Implement database queries using sqlite3
    raise NotImplementedError("Database queries not implemented")


def dispatch(mission):
    """Dispatch a mission to the appropriate solver and return results dict.

    mission: dict with id, type, mu, radius, j2, params (parsed JSON dict)
    """
    import orbital as orb

    mtype = mission["type"]
    mu = mission["mu"]
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

    elif mtype == "hohmann":
        dv_a, dv_b, t = orb.hohmann(mu, params["r_i"], params["r_f"])
        return {
            "dv_a_km_s": dv_a,
            "dv_b_km_s": dv_b,
            "dv_total_km_s": dv_a + dv_b,
            "t_trans_s": t,
        }

    # TODO: Add dispatch for remaining mission types:
    #   coe2rv, lambert, bielliptic, j2_correction, plane_change, mission_budget

    else:
        raise NotImplementedError(
            f"Mission type '{mtype}' dispatch not implemented"
        )


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
