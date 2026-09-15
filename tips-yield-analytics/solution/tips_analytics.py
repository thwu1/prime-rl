#!/usr/bin/env python3
"""
Treasury TIPS Analytics Pipeline.

"""

import argparse
import calendar
import csv
import json
import sqlite3
import sys
from datetime import datetime

DB_PATH = "/app/treasury.db"
DATA_DIR = "/app/data"
BUILD_DIR = "/app/build"

NOMINAL_TENORS = [
    ("BC_1MONTH", 1 / 12), ("BC_2MONTH", 2 / 12), ("BC_3MONTH", 3 / 12),
    ("BC_4MONTH", 4 / 12), ("BC_6MONTH", 6 / 12), ("BC_1YEAR", 1.0),
    ("BC_2YEAR", 2.0), ("BC_3YEAR", 3.0), ("BC_5YEAR", 5.0),
    ("BC_7YEAR", 7.0), ("BC_10YEAR", 10.0), ("BC_20YEAR", 20.0),
    ("BC_30YEAR", 30.0),
]

REAL_TENORS = [
    ("TC_5YEAR", 5.0), ("TC_7YEAR", 7.0), ("TC_10YEAR", 10.0),
    ("TC_20YEAR", 20.0), ("TC_30YEAR", 30.0),
]

H15_TENOR_MAP = {
    "RIFLGFCM01_N.B": ("1 Mo", 1 / 12),
    "RIFLGFCM03_N.B": ("3 Mo", 3 / 12),
    "RIFLGFCM06_N.B": ("6 Mo", 6 / 12),
    "RIFLGFCY01_N.B": ("1 Yr", 1.0),
    "RIFLGFCY02_N.B": ("2 Yr", 2.0),
    "RIFLGFCY03_N.B": ("3 Yr", 3.0),
    "RIFLGFCY05_N.B": ("5 Yr", 5.0),
    "RIFLGFCY07_N.B": ("7 Yr", 7.0),
    "RIFLGFCY10_N.B": ("10 Yr", 10.0),
    "RIFLGFCY20_N.B": ("20 Yr", 20.0),
    "RIFLGFCY30_N.B": ("30 Yr", 30.0),
}


def load_wide_csv(filepath, tenor_list):
    rows = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            date = parts[0]
            for i, (_, tenor) in enumerate(tenor_list):
                val = parts[i + 1].strip()
                if val:
                    rows.append((date, tenor, float(val)))
    return rows


def load_h15(filepath):
    rows = []
    with open(filepath) as f:
        reader = csv.reader(f)
        header = None
        for row in reader:
            if row and row[0].strip().startswith("Time Period"):
                header = [h.strip() for h in row]
                break
        if not header:
            return rows
        series_codes = header[1:]
        for row in reader:
            if not row:
                continue
            date = row[0].strip()
            for i, code in enumerate(series_codes):
                val_str = row[i + 1].strip() if i + 1 < len(row) else ""
                if val_str and val_str != "ND":
                    rows.append((date, code, float(val_str)))
    return rows


def load_cpi(filepath):
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = datetime.strptime(row["observation_date"], "%Y-%m-%d").date()
            rows.append((d.year, d.month, float(row["CPIAUCNS"])))
    return rows


def load_tips_json(filepath):
    with open(filepath) as f:
        data = json.load(f)
    rows = []
    seen = set()
    for rec in data:
        key = (rec["cusip"], rec["issueDate"])
        if key in seen:
            continue
        seen.add(key)
        if not rec.get("refCpiOnIssueDate") or not rec.get("refCpiOnDatedDate"):
            continue
        rows.append((
            rec["cusip"], rec["issueDate"], rec["maturityDate"],
            float(rec["interestRate"]),
            float(rec["refCpiOnIssueDate"]), float(rec["refCpiOnDatedDate"]),
            float(rec["indexRatioOnIssueDate"]),
        ))
    return rows


def cmd_load(args):
    conn = sqlite3.connect(DB_PATH)

    nom_rows = load_wide_csv(f"{BUILD_DIR}/nominal.csv", NOMINAL_TENORS)
    conn.executemany(
        "INSERT OR REPLACE INTO nominal_yields(date, tenor, rate) VALUES (?,?,?)",
        nom_rows,
    )

    real_rows = load_wide_csv(f"{BUILD_DIR}/real.csv", REAL_TENORS)
    conn.executemany(
        "INSERT OR REPLACE INTO real_yields(date, tenor, rate) VALUES (?,?,?)",
        real_rows,
    )

    h15_rows = load_h15(f"{DATA_DIR}/h15_rates.csv")
    conn.executemany(
        "INSERT OR REPLACE INTO h15_rates(date, series_id, rate) VALUES (?,?,?)",
        h15_rows,
    )

    cpi_rows = load_cpi(f"{DATA_DIR}/cpi_u_nsa.csv")
    conn.executemany(
        "INSERT OR REPLACE INTO cpi_monthly(year, month, value) VALUES (?,?,?)",
        cpi_rows,
    )

    tips_rows = load_tips_json(f"{DATA_DIR}/tips_securities.json")
    conn.executemany(
        "INSERT OR REPLACE INTO tips_securities"
        "(cusip, issue_date, maturity_date, interest_rate,"
        " ref_cpi_issue, ref_cpi_dated, index_ratio_issue)"
        " VALUES (?,?,?,?,?,?,?)",
        tips_rows,
    )

    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_PATH)


def month_offset(year, month, offset):
    month += offset
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def compute_ref_cpi(date_str, conn):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    D = calendar.monthrange(d.year, d.month)[1]
    y3, m3 = month_offset(d.year, d.month, -3)
    y2, m2 = month_offset(d.year, d.month, -2)

    row3 = conn.execute(
        "SELECT value FROM cpi_monthly WHERE year=? AND month=?", (y3, m3)
    ).fetchone()
    row2 = conn.execute(
        "SELECT value FROM cpi_monthly WHERE year=? AND month=?", (y2, m2)
    ).fetchone()

    if not row3 or not row2:
        raise ValueError(f"CPI data insufficient for {date_str}")

    cpi_m3 = row3[0]
    cpi_m2 = row2[0]
    return cpi_m3 + (d.day - 1) / D * (cpi_m2 - cpi_m3)


def cmd_ref_cpi(args):
    conn = get_db()
    try:
        val = compute_ref_cpi(args.date, conn)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()
    print(json.dumps({"date": args.date, "ref_cpi": round(val, 6)}))


def cmd_index_ratio(args):
    conn = get_db()
    try:
        ref_settlement = compute_ref_cpi(args.date, conn)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        conn.close()
        sys.exit(1)

    row = conn.execute(
        "SELECT ref_cpi_dated FROM tips_securities WHERE cusip=? LIMIT 1",
        (args.cusip,),
    ).fetchone()
    conn.close()

    if not row:
        print(f"CUSIP {args.cusip} not found", file=sys.stderr)
        sys.exit(1)

    ref_base = row[0]
    ratio = ref_settlement / ref_base
    floored = max(1.0, ratio)
    print(json.dumps({
        "date": args.date,
        "cusip": args.cusip,
        "ref_cpi_settlement": round(ref_settlement, 6),
        "ref_cpi_base": ref_base,
        "index_ratio": round(ratio, 6),
        "floored_index_ratio": round(floored, 6),
    }))


def load_yields_from_db(conn, curve_type, date_str):
    dt = datetime.strptime(date_str, "%m/%d/%Y")
    db_date = dt.strftime("%Y-%m-%d")

    table = "nominal_yields" if curve_type == "nominal" else "real_yields"
    rows = conn.execute(
        f"SELECT tenor, rate FROM {table} WHERE date=? ORDER BY tenor",
        (db_date,),
    ).fetchall()

    if not rows:
        raise ValueError(f"Date {date_str} not found in {curve_type} yields")

    tenors = [r[0] for r in rows]
    yields_list = [r[1] for r in rows]
    return tenors, yields_list


def interp_spot(t, spot_tenors, spot_rates):
    if not spot_tenors:
        raise ValueError("No spot rates available")
    if t <= spot_tenors[0]:
        return spot_rates[0]
    if t >= spot_tenors[-1]:
        return spot_rates[-1]
    for i in range(len(spot_tenors) - 1):
        if spot_tenors[i] <= t <= spot_tenors[i + 1]:
            frac = (t - spot_tenors[i]) / (spot_tenors[i + 1] - spot_tenors[i])
            return spot_rates[i] + frac * (spot_rates[i + 1] - spot_rates[i])
    return spot_rates[-1]


def discount_factor(t, z):
    if t <= 0:
        return 1.0
    return 1.0 / (1.0 + z / 200.0) ** (2.0 * t)


def price_bond(par_yield, tenor, spot_tenors, spot_rates):
    n_coupons = max(1, round(tenor * 2))
    coupon = par_yield / 2.0
    pv = 0.0
    for k in range(1, n_coupons + 1):
        t_k = k / 2.0
        z = interp_spot(t_k, spot_tenors, spot_rates)
        df = discount_factor(t_k, z)
        if k < n_coupons:
            pv += coupon * df
        else:
            pv += (100.0 + coupon) * df
    return pv


def bootstrap_curve(tenors, par_yields):
    spot_tenors = []
    spot_rates = []

    for tenor, par_yield in zip(tenors, par_yields):
        if tenor <= 0.5:
            spot_tenors.append(tenor)
            spot_rates.append(par_yield)
        else:
            lo, hi = -5.0, 30.0
            for _ in range(200):
                mid = (lo + hi) / 2.0
                temp_tenors = spot_tenors + [tenor]
                temp_rates = spot_rates + [mid]
                pv = price_bond(par_yield, tenor, temp_tenors, temp_rates)
                if pv > 100.0:
                    lo = mid
                else:
                    hi = mid
                if abs(hi - lo) < 1e-12:
                    break
            z_t = (lo + hi) / 2.0
            spot_tenors.append(tenor)
            spot_rates.append(z_t)

    disc_factors = [
        discount_factor(t, z) for t, z in zip(spot_tenors, spot_rates)
    ]

    max_error_bps = 0.0
    for tenor, par_yield in zip(tenors, par_yields):
        if tenor <= 0.5:
            continue
        reconstructed_price = price_bond(par_yield, tenor, spot_tenors, spot_rates)
        price_error = abs(reconstructed_price - 100.0)
        error_bps = price_error * 100.0
        if error_bps > max_error_bps:
            max_error_bps = error_bps

    return spot_tenors, spot_rates, disc_factors, max_error_bps


def forward_rate_5y5y(spot_tenors, spot_rates):
    z5 = interp_spot(5.0, spot_tenors, spot_rates)
    z10 = interp_spot(10.0, spot_tenors, spot_rates)
    df5 = discount_factor(5.0, z5)
    df10 = discount_factor(10.0, z10)
    ratio = df5 / df10
    fwd = 200.0 * (ratio ** (1.0 / 10.0) - 1.0)
    return fwd


def cmd_bootstrap(args):
    conn = get_db()
    try:
        tenors, par_yields = load_yields_from_db(conn, args.curve, args.date)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        conn.close()
        sys.exit(1)
    conn.close()

    spot_tenors, spot_rates, disc_factors, max_err = bootstrap_curve(
        tenors, par_yields
    )
    print(json.dumps({
        "date": args.date,
        "curve_type": args.curve,
        "tenors": [round(t, 6) for t in spot_tenors],
        "spot_rates": [round(r, 6) for r in spot_rates],
        "discount_factors": [round(d, 8) for d in disc_factors],
        "max_roundtrip_error_bps": round(max_err, 6),
    }))


def cmd_forward_breakeven(args):
    conn = get_db()
    try:
        nom_tenors, nom_yields = load_yields_from_db(conn, "nominal", args.date)
        real_tenors, real_yields = load_yields_from_db(conn, "real", args.date)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        conn.close()
        sys.exit(1)
    conn.close()

    par_be = {}
    for i, tenor in enumerate(real_tenors):
        tenor_key = str(int(tenor))
        nom_yield = None
        for j, nt in enumerate(nom_tenors):
            if abs(nt - tenor) < 0.01:
                nom_yield = nom_yields[j]
                break
        if nom_yield is None:
            raise ValueError(f"No nominal yield for tenor {tenor}")
        par_be[tenor_key] = round(nom_yield - real_yields[i], 2)

    nom_st, nom_sr, _, _ = bootstrap_curve(nom_tenors, nom_yields)
    real_st, real_sr, _, _ = bootstrap_curve(real_tenors, real_yields)

    fwd_nom = forward_rate_5y5y(nom_st, nom_sr)
    fwd_real = forward_rate_5y5y(real_st, real_sr)
    fwd_be = fwd_nom - fwd_real

    print(json.dumps({
        "par_breakeven": par_be,
        "forward_5y5y_nominal": round(fwd_nom, 4),
        "forward_5y5y_real": round(fwd_real, 4),
        "forward_5y5y_breakeven": round(fwd_be, 4),
    }))


def cmd_validate(args):
    conn = get_db()

    tips = conn.execute(
        "SELECT cusip, issue_date, ref_cpi_issue, ref_cpi_dated, index_ratio_issue"
        " FROM tips_securities"
    ).fetchall()

    total_checked = 0
    passed = 0
    max_ref_error = 0.0
    max_ratio_error = 0.0
    failures = []

    for cusip, issue_date, golden_ref, base_ref, golden_ratio in tips:
        try:
            computed_ref = compute_ref_cpi(issue_date, conn)
        except (ValueError, KeyError):
            continue

        total_checked += 1
        computed_ratio = computed_ref / base_ref
        ref_error = abs(computed_ref - golden_ref)
        ratio_error = abs(computed_ratio - golden_ratio)

        if ref_error > max_ref_error:
            max_ref_error = ref_error
        if ratio_error > max_ratio_error:
            max_ratio_error = ratio_error

        if ref_error < 0.001 and ratio_error < 0.00005:
            passed += 1
        else:
            failures.append({
                "cusip": cusip,
                "issue_date": issue_date,
                "ref_cpi_error": round(ref_error, 8),
                "index_ratio_error": round(ratio_error, 8),
                "computed_ref_cpi": round(computed_ref, 6),
                "golden_ref_cpi": golden_ref,
                "computed_ratio": round(computed_ratio, 6),
                "golden_ratio": golden_ratio,
            })

    conn.close()
    print(json.dumps({
        "total_checked": total_checked,
        "passed": passed,
        "max_ref_cpi_error": round(max_ref_error, 8),
        "max_index_ratio_error": round(max_ratio_error, 8),
        "failures": failures,
    }))


def cmd_reconcile(args):
    date_str = args.date
    conn = get_db()

    nom_rows = conn.execute(
        "SELECT tenor, rate FROM nominal_yields WHERE date=? ORDER BY tenor",
        (date_str,),
    ).fetchall()

    if not nom_rows:
        print(f"Date {date_str} not found in nominal yields", file=sys.stderr)
        conn.close()
        sys.exit(1)

    xml_map = {r[0]: r[1] for r in nom_rows}

    h15_rows = conn.execute(
        "SELECT series_id, rate FROM h15_rates WHERE date=?",
        (date_str,),
    ).fetchall()

    if not h15_rows:
        print(f"Date {date_str} is non-trading in H.15", file=sys.stderr)
        conn.close()
        sys.exit(1)

    h15_map = {}
    for series_id, rate in h15_rows:
        if series_id in H15_TENOR_MAP:
            label, tenor = H15_TENOR_MAP[series_id]
            h15_map[tenor] = (label, rate)

    conn.close()

    diffs = {}
    matched = 0
    max_diff = 0.0

    for tenor in sorted(h15_map.keys()):
        label, h15_val = h15_map[tenor]
        if tenor in xml_map:
            matched += 1
            diff = abs(xml_map[tenor] - h15_val)
            diffs[label] = round(diff, 4)
            if diff > max_diff:
                max_diff = diff

    print(json.dumps({
        "date": date_str,
        "matched_tenors": matched,
        "max_abs_diff": round(max_diff, 4),
        "diffs": diffs,
    }))


def main():
    parser = argparse.ArgumentParser(description="Treasury TIPS Analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("load")

    p_ref = subparsers.add_parser("ref-cpi")
    p_ref.add_argument("--date", required=True)

    p_idx = subparsers.add_parser("index-ratio")
    p_idx.add_argument("--date", required=True)
    p_idx.add_argument("--cusip", required=True)

    p_boot = subparsers.add_parser("bootstrap")
    p_boot.add_argument("--date", required=True)
    p_boot.add_argument("--curve", required=True, choices=["nominal", "real"])

    p_fwd = subparsers.add_parser("forward-breakeven")
    p_fwd.add_argument("--date", required=True)

    subparsers.add_parser("validate")

    p_rec = subparsers.add_parser("reconcile")
    p_rec.add_argument("--date", required=True)

    args = parser.parse_args()

    handlers = {
        "load": cmd_load,
        "ref-cpi": cmd_ref_cpi,
        "index-ratio": cmd_index_ratio,
        "bootstrap": cmd_bootstrap,
        "forward-breakeven": cmd_forward_breakeven,
        "validate": cmd_validate,
        "reconcile": cmd_reconcile,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
