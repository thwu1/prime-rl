#!/usr/bin/env python3
"""
Compliance pipeline: batch APR processing with APOR rate-spread analysis.
Processes all loan JSON files, enriches with APOR data, stores in SQLite,
and writes a JSON compliance summary to stdout.
"""

import calendar
import csv
import json
import os
import sqlite3
import subprocess
from datetime import date

LOANS_DIR = "/app/loans"
APOR_CSV = "/app/reference/apor_rates.csv"
DB_PATH = "/app/results.db"
APR_TOOL = "/app/regz_apr"


def parse_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def add_months(d, n):
    total_m = d.month + n
    year = d.year + (total_m - 1) // 12
    month = ((total_m - 1) % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)


def compute_term_end(loan):
    """Compute the term end date: later of last payment and last advance."""
    last_pay = None
    for g in loan["payment_groups"]:
        d = parse_date(g["first_date"])
        last_in_group = add_months(d, (g["count"] - 1) * g["period_months"])
        if last_pay is None or last_in_group > last_pay:
            last_pay = last_in_group

    last_adv = max(parse_date(a["date"]) for a in loan["advances"])

    if last_pay is None:
        return last_adv
    return max(last_pay, last_adv)


def compute_term_years(loan):
    """Compute term in years: max(1, round(days / 365.25))."""
    consummation = parse_date(loan["consummation_date"])
    term_end = compute_term_end(loan)
    days = (term_end - consummation).days
    if days <= 0:
        return 1
    return max(1, round(days / 365.25))


def load_apor_rates():
    """Load APOR rates from CSV. Returns dict: term_years -> apor_pct."""
    rates = {}
    with open(APOR_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rates[int(row["term_years"])] = float(row["apor_pct"])
    return rates


def find_nearest_apor(term_years, apor_rates):
    """Find nearest APOR rate. Ties go to shorter term."""
    available = sorted(apor_rates.keys())
    best = available[0]
    best_diff = abs(term_years - best)
    for t in available[1:]:
        diff = abs(term_years - t)
        if diff < best_diff or (diff == best_diff and t < best):
            best = t
            best_diff = diff
    return apor_rates[best]


def main():
    apor_rates = load_apor_rates()

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE loan_results (
            id TEXT PRIMARY KEY,
            computed_apr REAL NOT NULL,
            transaction_type TEXT NOT NULL CHECK(transaction_type IN ('regular','irregular')),
            tolerance_pct REAL NOT NULL,
            disclosed_apr REAL,
            within_tolerance INTEGER,
            term_years INTEGER NOT NULL,
            apor_rate REAL NOT NULL,
            rate_spread REAL NOT NULL,
            high_cost INTEGER NOT NULL CHECK(high_cost IN (0,1))
        )
    """)

    all_results = []

    for fname in sorted(os.listdir(LOANS_DIR)):
        if not fname.endswith(".json"):
            continue

        loan_path = os.path.join(LOANS_DIR, fname)

        proc = subprocess.run(
            [APR_TOOL, loan_path],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            continue

        apr_result = json.loads(proc.stdout.strip())

        with open(loan_path) as f:
            loan = json.load(f)

        term_years = compute_term_years(loan)
        apor_rate = find_nearest_apor(term_years, apor_rates)
        rate_spread = round(apr_result["computed_apr"] - apor_rate, 2)
        high_cost = 1 if rate_spread > 6.5 else 0

        wt = apr_result["within_tolerance"]
        wt_int = None if wt is None else (1 if wt else 0)

        conn.execute(
            "INSERT INTO loan_results VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                apr_result["id"],
                apr_result["computed_apr"],
                apr_result["transaction_type"],
                apr_result["tolerance_pct"],
                apr_result.get("disclosed_apr"),
                wt_int,
                term_years,
                apor_rate,
                rate_spread,
                high_cost,
            ),
        )

        all_results.append({
            "id": apr_result["id"],
            "transaction_type": apr_result["transaction_type"],
            "within_tolerance": apr_result["within_tolerance"],
            "rate_spread": rate_spread,
            "high_cost": high_cost,
        })

    conn.commit()
    conn.close()

    total = len(all_results)
    regular = sum(1 for r in all_results if r["transaction_type"] == "regular")
    irregular = total - regular
    hc = sum(1 for r in all_results if r["high_cost"] == 1)
    failures = sorted(
        r["id"] for r in all_results if r["within_tolerance"] is False
    )
    avg_spread = (
        round(sum(r["rate_spread"] for r in all_results) / total, 2)
        if total > 0
        else 0.0
    )

    summary = {
        "total_loans": total,
        "regular_count": regular,
        "irregular_count": irregular,
        "high_cost_count": hc,
        "tolerance_failures": failures,
        "avg_rate_spread": avg_spread,
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
