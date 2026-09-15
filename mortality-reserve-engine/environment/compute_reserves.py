#!/usr/bin/env python3
"""Compute actuarial net premium reserves from mortality database.

Reads mortality data from SQLite, applies generational mortality projection,
and computes prospective reserves for a portfolio of term life policies.
"""

import argparse
import json
import sqlite3


def get_base_rate(conn, table_id, issue_age, duration):
    """Look up base mortality rate from select or ultimate table."""
    if duration < 25:
        row = conn.execute(
            "SELECT qx FROM select_rates "
            "WHERE table_id=? AND issue_age=? AND duration=?",
            (table_id, issue_age, duration)
        ).fetchone()
        if row is not None:
            return row[0]
    # Fall back to ultimate table
    attained_age = issue_age + duration - 1
    row = conn.execute(
        "SELECT qx FROM ultimate_rates "
        "WHERE table_id=? AND attained_age=?",
        (table_id, attained_age)
    ).fetchone()
    if row is None:
        raise ValueError(
            f"No rate: table_id={table_id}, issue_age={issue_age}, "
            f"duration={duration}, attained_age={attained_age}"
        )
    return row[0]


def get_improvement(conn, table_id, age, year):
    """Look up improvement factor from database."""
    row = conn.execute(
        "SELECT rate FROM improvement_factors "
        "WHERE table_id=? AND age=? AND year=?",
        (table_id, age, year)
    ).fetchone()
    if row is not None:
        return row[0]
    # For years beyond the data range, use the maximum available year
    if year > 2037:
        row = conn.execute(
            "SELECT rate FROM improvement_factors "
            "WHERE table_id=? AND age=? AND year=2037",
            (table_id, age)
        ).fetchone()
        if row is not None:
            return row[0]
    return 0.0


def project_rate(conn, q_base, imp_table_id, attained_age, calendar_year,
                 base_year):
    """Apply cumulative improvement factors to project a base rate."""
    cumulative = 1.0
    for t in range(base_year, calendar_year + 1):
        imp = get_improvement(conn, imp_table_id, attained_age, t)
        cumulative *= (1.0 - imp)
    return q_base * cumulative


def compute_projected_rates(conn, table_id, imp_table_id, issue_age,
                            start_dur, count, start_year, base_year):
    """Build array of generationally-projected mortality rates."""
    rates = []
    for k in range(count):
        dur = start_dur + k
        att_age = issue_age + dur - 1
        cal_yr = start_year + k
        qb = get_base_rate(conn, table_id, issue_age, dur)
        rates.append(
            project_rate(conn, qb, imp_table_id, att_age, cal_yr, base_year)
        )
    return rates


def compute_annuity(projected_qx, interest_rate):
    """Compute temporary life annuity value."""
    v = 1.0 / (1.0 + interest_rate)
    result = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        result += kpx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return result


def compute_insurance_pv(projected_qx, interest_rate):
    """Compute present value of term life insurance benefits."""
    v = 1.0 / (1.0 + interest_rate)
    result = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        result += kpx * qx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return result


def run_valuation(conn, val_cfg, base_year, rate_override=None):
    """Compute valuation outputs for a single policy."""
    ia = val_cfg["issue_age"]
    iy = val_cfg["issue_year"]
    term = val_cfg["term_years"]
    rate = rate_override if rate_override is not None else val_cfg["annual_interest_rate"]
    vy = val_cfg["valuation_year"]
    fa = val_cfg["face_amount"]
    tid = val_cfg["table_id"]
    imp_tid = val_cfg["improvement_table_id"]

    elapsed = vy - iy
    remaining = term - elapsed

    # Projected qx from valuation date forward
    val_qx = compute_projected_rates(
        conn, tid, imp_tid, ia, elapsed + 1, remaining, vy, base_year
    )
    ann_val = compute_annuity(val_qx, rate)
    ins_val = compute_insurance_pv(val_qx, rate)

    # At-issue projected qx for premium calculation
    issue_qx = compute_projected_rates(
        conn, tid, imp_tid, ia, 1, term, iy, base_year
    )
    ann_issue = compute_annuity(issue_qx, rate)
    ins_issue = compute_insurance_pv(issue_qx, rate)

    premium = ins_issue / ann_issue
    reserve = ins_val - premium * ann_val

    return {
        "projected_qx": val_qx,
        "annuity_due": ann_val,
        "insurance_pv": ins_val,
        "annual_premium": premium,
        "reserve": reserve,
        "face_amount": fa,
    }


def main():
    parser = argparse.ArgumentParser(description="Compute actuarial reserves")
    parser.add_argument("--db", required=True, help="Path to mortality database")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--output", required=True, help="Path to output results JSON")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    conn = sqlite3.connect(args.db)
    base_year = config["base_year"]
    stress_bps = config["stress_bps"]

    results = {}
    total = 0.0
    total_up = 0.0
    total_down = 0.0

    for val in config["valuations"]:
        base_rate = val["annual_interest_rate"]

        r = run_valuation(conn, val, base_year)
        r_up = run_valuation(conn, val, base_year,
                              rate_override=base_rate + stress_bps * 0.0001)
        r_down = run_valuation(conn, val, base_year,
                                rate_override=base_rate - stress_bps * 0.0001)

        results[val["id"]] = {
            "projected_qx": r["projected_qx"],
            "annuity_due": r["annuity_due"],
            "insurance_pv": r["insurance_pv"],
            "annual_premium": r["annual_premium"],
            "reserve": r["reserve"],
            "reserve_up": r_up["reserve"],
            "reserve_down": r_down["reserve"],
        }
        total += r["face_amount"] * r["reserve"]
        total_up += r["face_amount"] * r_up["reserve"]
        total_down += r["face_amount"] * r_down["reserve"]

    results["total_reserve"] = total
    results["total_reserve_up"] = total_up
    results["total_reserve_down"] = total_down

    conn.close()

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"=== Results written to {args.output} ===")


if __name__ == "__main__":
    main()
