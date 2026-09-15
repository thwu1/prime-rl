#!/usr/bin/env python3
"""Trade reconciliation tool: compares G-33 valuations against vendor report."""

import csv
import json
import os
import subprocess
import tempfile


def parse_csv(path, delimiter="|"):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            rows.append(row)
    return rows


def parse_vendor_value(s):
    """Parse a vendor report value: empty -> None, else float."""
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return s


def run_muni_calc(spec):
    fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(spec, f)
        result = subprocess.run(
            ["python3", "/app/muni_calc.py", path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"muni_calc.py failed: {result.stderr}"
            )
        return json.loads(result.stdout)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def build_spec(trade, call_schedules):
    """Build a muni_calc input spec from a CSV trade row."""
    tid = trade["trade_id"]
    spec = {
        "security_type": trade["security_type"],
        "coupon_rate": float(trade["coupon_rate"]),
        "settlement_date": trade["settlement_date"],
        "maturity_date": trade["maturity_date"],
        "dated_date": trade["dated_date"],
        "first_coupon_date": trade["first_coupon_date"],
        "frequency": int(trade["frequency"]),
        "redemption_value": float(trade["redemption_value"]),
        "compute": trade["compute"],
        "yield_input": float(trade["yield_input"]) if trade["yield_input"].strip() else None,
        "price_input": float(trade["price_input"]) if trade["price_input"].strip() else None,
        "discount_rate": float(trade["discount_rate"]) if trade["discount_rate"].strip() else None,
        "call_schedule": call_schedules.get(tid, []),
    }
    return spec


def values_differ(v1, v2):
    """Check if two values differ, handling None and float comparison."""
    if v1 is None and v2 is None:
        return False
    if v1 is None or v2 is None:
        return True
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        return abs(v1 - v2) > 1e-9
    return str(v1) != str(v2)


def main():
    trades = parse_csv("/app/data/trades.csv")
    vendor = parse_csv("/app/data/vendor_report.csv")

    with open("/app/data/call_schedules.json") as f:
        call_schedules = json.load(f)

    vendor_by_id = {}
    for row in vendor:
        tid = row["trade_id"]
        vendor_by_id[tid] = {
            "accrued_interest": parse_vendor_value(row["accrued_interest"]),
            "dollar_price": parse_vendor_value(row["dollar_price"]),
            "yield": parse_vendor_value(row["yield"]),
            "yield_to_worst": parse_vendor_value(row["yield_to_worst"]),
            "worst_date": row["worst_date"].strip() if row["worst_date"].strip() else None,
            "worst_rv": parse_vendor_value(row["worst_rv"]),
        }

    discrepancies = []
    compare_fields = [
        "accrued_interest", "dollar_price", "yield",
        "yield_to_worst", "worst_date", "worst_rv",
    ]

    for trade in trades:
        tid = trade["trade_id"]
        spec = build_spec(trade, call_schedules)
        computed = run_muni_calc(spec)
        vend = vendor_by_id.get(tid, {})

        for field in compare_fields:
            cv = computed.get(field)
            vv = vend.get(field)
            if values_differ(cv, vv):
                discrepancies.append({
                    "trade_id": tid,
                    "field": field,
                    "vendor_value": vv,
                    "correct_value": cv,
                })

    discrepancies.sort(key=lambda d: (d["trade_id"], d["field"]))

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/discrepancies.json", "w") as f:
        json.dump(discrepancies, f, indent=2)


if __name__ == "__main__":
    main()
