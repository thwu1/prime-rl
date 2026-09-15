#!/usr/bin/env python3
"""
Enrichment helper: reads APR results NDJSON + APOR fixed-width data + loan
JSONs, computes term-based rate-spread analysis, outputs enriched NDJSON.
"""

import calendar
import json
import os
import re
from datetime import date


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


def parse_apor_fixed(path):
    """Parse APOR rates from fixed-width Fed G.19 format."""
    rates = {}
    with open(path) as f:
        for line in f:
            m = re.match(r"\s+(\d+)\s+([\d.]+)", line)
            if m:
                rates[int(m.group(1))] = float(m.group(2))
    return rates


def compute_term_end(loan):
    """Compute term end date: later of last payment and last advance."""
    last_pay = None
    for g in loan["payment_groups"]:
        d = parse_date(g["first_date"])
        last_in_group = add_months(d, (g["count"] - 1) * g["period_months"])
        if last_pay is None or last_in_group > last_pay:
            last_pay = last_in_group
    last_adv = max(parse_date(a["date"]) for a in loan["advances"])
    return max(last_pay, last_adv) if last_pay else last_adv


def compute_term_years(loan):
    """Compute term in years: max(1, round(days / 365.25))."""
    consummation = parse_date(loan["consummation_date"])
    term_end = compute_term_end(loan)
    days = (term_end - consummation).days
    if days <= 0:
        return 1
    return max(1, round(days / 365.25))


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
    apor_rates = parse_apor_fixed("/app/reference/apor_fixed.dat")

    # Read APR results from compute stage
    apr_results = {}
    with open("/app/build/apr_results.ndjson") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                apr_results[obj["id"]] = obj

    # Process each loan and enrich with APOR data
    enriched = []
    loans_dir = "/app/loans"
    for fname in sorted(os.listdir(loans_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(loans_dir, fname)) as f:
            loan = json.load(f)

        loan_id = loan["id"]
        if loan_id not in apr_results:
            continue

        apr = apr_results[loan_id]
        term_years = compute_term_years(loan)
        apor_rate = find_nearest_apor(term_years, apor_rates)
        rate_spread = round(apr["computed_apr"] - apor_rate, 2)
        high_cost = 1 if rate_spread > 6.5 else 0

        wt = apr["within_tolerance"]
        wt_int = None if wt is None else (1 if wt else 0)

        enriched_obj = {
            "id": loan_id,
            "computed_apr": apr["computed_apr"],
            "transaction_type": apr["transaction_type"],
            "tolerance_pct": apr["tolerance_pct"],
            "disclosed_apr": apr.get("disclosed_apr"),
            "within_tolerance": wt_int,
            "term_years": term_years,
            "apor_rate": apor_rate,
            "rate_spread": rate_spread,
            "high_cost": high_cost,
        }
        enriched.append(enriched_obj)

    with open("/app/build/enriched.ndjson", "w") as f:
        for obj in enriched:
            f.write(json.dumps(obj) + "\n")


if __name__ == "__main__":
    main()
