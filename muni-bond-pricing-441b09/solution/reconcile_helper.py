#!/usr/bin/env python3
"""
Reconciliation helper: imports CSV data into SQLite, computes G-33 valuations
by invoking muni_calc.py, and populates discrepancies table.

Called by reconcile.sh with the database path as argument.
"""

import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile


def run_muni_calc(spec):
    """Invoke the muni_calc.py CLI and return parsed JSON output."""
    fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(spec, f)
        result = subprocess.run(
            ["python3", "/app/muni_calc.py", path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"muni_calc.py failed: {result.stderr}")
        return json.loads(result.stdout)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def parse_vendor_value(s):
    """Parse a vendor report value: empty string -> None, else float."""
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return s


def values_differ(cv, vv):
    """Check if two values differ, handling None and float comparison."""
    if cv is None and vv is None:
        return False
    if cv is None or vv is None:
        return True
    if isinstance(cv, (int, float)) and isinstance(vv, (int, float)):
        return abs(cv - vv) > 1e-9
    return str(cv) != str(vv)


def main():
    db_path = sys.argv[1]
    conn = sqlite3.connect(db_path)

    # Load call schedules from JSON
    with open("/app/data/call_schedules.json") as f:
        call_schedules = json.load(f)

    # Import trades from pipe-delimited CSV into trades table
    with open("/app/data/trades.csv") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            conn.execute(
                "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["trade_id"],
                    row["security_type"],
                    float(row["coupon_rate"]),
                    row["settlement_date"],
                    row["maturity_date"],
                    row["dated_date"],
                    row["first_coupon_date"],
                    int(row["frequency"]),
                    float(row["redemption_value"]),
                    row["compute"],
                    float(row["yield_input"]) if row["yield_input"].strip() else None,
                    float(row["price_input"]) if row["price_input"].strip() else None,
                    float(row["discount_rate"]) if row["discount_rate"].strip() else None,
                ),
            )

    # Import vendor values from pipe-delimited CSV into vendor_values table
    with open("/app/data/vendor_report.csv") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            conn.execute(
                "INSERT INTO vendor_values VALUES (?,?,?,?,?,?,?)",
                (
                    row["trade_id"],
                    parse_vendor_value(row["accrued_interest"]),
                    parse_vendor_value(row["dollar_price"]),
                    parse_vendor_value(row["yield"]),
                    parse_vendor_value(row["yield_to_worst"]),
                    row["worst_date"].strip() if row["worst_date"].strip() else None,
                    parse_vendor_value(row["worst_rv"]),
                ),
            )

    conn.commit()

    # Compute G-33 values for each trade via muni_calc.py
    cursor = conn.execute("SELECT * FROM trades")
    columns = [d[0] for d in cursor.description]
    trades = [dict(zip(columns, r)) for r in cursor.fetchall()]

    for trade in trades:
        tid = trade["trade_id"]

        # Build muni_calc input spec
        spec = {
            "security_type": trade["security_type"],
            "coupon_rate": trade["coupon_rate"],
            "settlement_date": trade["settlement_date"],
            "maturity_date": trade["maturity_date"],
            "dated_date": trade["dated_date"],
            "first_coupon_date": trade["first_coupon_date"],
            "frequency": trade["frequency"],
            "redemption_value": trade["redemption_value"],
            "compute": trade["compute"],
            "yield_input": trade["yield_input"],
            "price_input": trade["price_input"],
            "discount_rate": trade.get("discount_rate"),
            "call_schedule": call_schedules.get(tid, []),
        }

        computed = run_muni_calc(spec)

        conn.execute(
            "INSERT INTO computed_values VALUES (?,?,?,?,?,?,?)",
            (
                tid,
                computed["accrued_interest"],
                computed["dollar_price"],
                computed["yield"],
                computed["yield_to_worst"],
                computed["worst_date"],
                computed["worst_rv"],
            ),
        )

    conn.commit()

    # Find discrepancies by comparing computed vs vendor values
    # Iterate fields in alphabetical order so GROUP_CONCAT produces sorted output
    compare_fields = [
        "accrued_interest",
        "dollar_price",
        "worst_date",
        "worst_rv",
        "yield",
        "yield_to_worst",
    ]

    rows = conn.execute(
        """
        SELECT c.trade_id,
            c.accrued_interest, v.accrued_interest,
            c.dollar_price,     v.dollar_price,
            c.yield,            v.yield,
            c.yield_to_worst,   v.yield_to_worst,
            c.worst_date,       v.worst_date,
            c.worst_rv,         v.worst_rv
        FROM computed_values c
        JOIN vendor_values v ON c.trade_id = v.trade_id
        ORDER BY c.trade_id
        """
    ).fetchall()

    field_indices = {
        "accrued_interest": (1, 2),
        "dollar_price": (3, 4),
        "yield": (5, 6),
        "yield_to_worst": (7, 8),
        "worst_date": (9, 10),
        "worst_rv": (11, 12),
    }

    for row in rows:
        tid = row[0]
        for field in compare_fields:
            ci, vi = field_indices[field]
            cv = row[ci]
            vv = row[vi]
            if values_differ(cv, vv):
                conn.execute(
                    "INSERT INTO discrepancies VALUES (?,?,?,?)",
                    (
                        tid,
                        field,
                        str(vv) if vv is not None else None,
                        str(cv) if cv is not None else None,
                    ),
                )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
