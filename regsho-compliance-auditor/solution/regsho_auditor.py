#!/usr/bin/env python3
"""FINRA Reg SHO Compliance Auditor.

Verifies short interest data, reconciles multi-venue short sale volumes,
and monitors threshold securities for close-out requirements.
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict


def parse_si_csv(filepath):
    """Parse FINRA consolidated short interest CSV with 14 fields."""
    records = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "symbolCode": row["symbolCode"],
                "issueName": row["issueName"],
                "currentShortPositionQuantity": int(row["currentShortPositionQuantity"]),
                "previousShortPositionQuantity": int(row["previousShortPositionQuantity"]),
                "stockSplitFlag": row.get("stockSplitFlag", "").strip() or None,
                "averageDailyVolumeQuantity": int(row["averageDailyVolumeQuantity"]),
                "daysToCoverQuantity": float(row["daysToCoverQuantity"]),
                "revisionFlag": row.get("revisionFlag", "").strip() or None,
                "changePercent": float(row["changePercent"]),
                "changePreviousNumber": int(row["changePreviousNumber"]),
                "settlementDate": row["settlementDate"],
                "marketClassCode": row["marketClassCode"],
            })
    return records


def compute_dtc(current, avg_daily_volume):
    """Compute days-to-cover with FINRA rules."""
    if avg_daily_volume == 0:
        return 999.99
    ratio = current / avg_daily_volume
    rounded = round(ratio, 2)
    if rounded > 999.99:
        return 999.99
    if ratio < 1.0 and ratio > 0:
        return 1.00
    return rounded


def compute_change_percent(current, previous):
    """Compute percentage change from previous period."""
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def is_dtc_cap_applied(current, avg_daily_volume):
    """Check if the 999.99 DTC cap was applied."""
    if avg_daily_volume == 0:
        return True
    ratio = current / avg_daily_volume
    rounded = round(ratio, 2)
    return rounded > 999.99


def is_dtc_floor_applied(current, avg_daily_volume):
    """Check if the 1.00 DTC floor was applied."""
    if avg_daily_volume == 0:
        return False
    ratio = current / avg_daily_volume
    return 0 < ratio < 1.0


def field_passes(reported, computed, tolerance=0.015):
    """Check if a computed value matches the reported value within tolerance."""
    if reported is None and computed is None:
        return True
    if reported is None or computed is None:
        return False
    return abs(reported - computed) <= tolerance


def verify_si(filepath, output_path):
    """Verify short interest computed fields."""
    records = parse_si_csv(filepath)

    dtc_cap_symbols = []
    dtc_floor_symbols = []
    output_records = []
    pass_count = 0
    fail_count = 0

    for rec in records:
        symbol = rec["symbolCode"]
        current = rec["currentShortPositionQuantity"]
        previous = rec["previousShortPositionQuantity"]
        avg_vol = rec["averageDailyVolumeQuantity"]

        # Compute values
        computed_change = current - previous
        computed_pct = compute_change_percent(current, previous)
        computed_dtc = compute_dtc(current, avg_vol)

        # Reported values
        reported_change = rec["changePreviousNumber"]
        reported_pct = rec["changePercent"]
        reported_dtc = rec["daysToCoverQuantity"]

        # Check passes
        change_pass = (computed_change == reported_change)
        pct_pass = field_passes(reported_pct, computed_pct)
        dtc_pass = field_passes(reported_dtc, computed_dtc)

        all_pass = change_pass and pct_pass and dtc_pass
        if all_pass:
            pass_count += 1
        else:
            fail_count += 1

        # Track cap/floor
        if is_dtc_cap_applied(current, avg_vol):
            dtc_cap_symbols.append(symbol)
        if is_dtc_floor_applied(current, avg_vol):
            dtc_floor_symbols.append(symbol)

        output_records.append({
            "symbol": symbol,
            "changePreviousNumber": {
                "reported": reported_change,
                "computed": computed_change,
                "pass": change_pass,
            },
            "changePercent": {
                "reported": reported_pct,
                "computed": computed_pct,
                "pass": pct_pass,
            },
            "daysToCoverQuantity": {
                "reported": reported_dtc,
                "computed": computed_dtc,
                "pass": dtc_pass,
            },
        })

    report = {
        "total_records": len(records),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "dtc_cap_symbols": dtc_cap_symbols,
        "dtc_floor_symbols": dtc_floor_symbols,
        "records": output_records,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)


def parse_venue_file(filepath):
    """Parse a pipe-delimited venue short sale volume file.

    Skips the header and any trailing non-data lines (record count).
    Returns dict mapping symbol -> {short_volume, short_exempt_volume,
    total_volume, market}.
    """
    records = {}
    with open(filepath) as f:
        header = f.readline()  # skip header
        for line in f:
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) != 6:
                continue
            date_str, symbol, short_vol, short_exempt, total_vol, market = parts
            try:
                sv = float(short_vol)
                se = float(short_exempt)
                tv = float(total_vol)
            except ValueError:
                continue
            records[symbol] = {
                "short_volume": sv,
                "short_exempt_volume": se,
                "total_volume": tv,
                "market": market,
            }
    return records


def derive_venue_name(filepath):
    """Derive venue identifier from filename (portion before _volume)."""
    basename = os.path.basename(filepath)
    name_no_ext = os.path.splitext(basename)[0]
    idx = name_no_ext.lower().find("_volume")
    if idx >= 0:
        return name_no_ext[:idx].upper()
    return name_no_ext.upper()


def reconcile_venues(filepaths, output_path):
    """Reconcile per-venue short sale volumes."""
    venue_data = {}  # venue_name -> {symbol -> record}
    venues = []

    for fp in filepaths:
        venue = derive_venue_name(fp)
        venues.append(venue)
        venue_data[venue] = parse_venue_file(fp)

    # Aggregate across venues
    all_symbols = set()
    for vd in venue_data.values():
        all_symbols.update(vd.keys())

    symbols_output = []
    multi_count = 0
    single_count = 0

    for symbol in sorted(all_symbols):
        agg_short = 0.0
        agg_exempt = 0.0
        agg_total = 0.0
        sym_venues = []
        venue_breakdown = {}

        for venue in venues:
            if symbol in venue_data[venue]:
                rec = venue_data[venue][symbol]
                agg_short += rec["short_volume"]
                agg_exempt += rec["short_exempt_volume"]
                agg_total += rec["total_volume"]
                sym_venues.append(venue)
                venue_breakdown[venue] = {
                    "short_volume": rec["short_volume"],
                    "total_volume": rec["total_volume"],
                }

        # Truncate to integers (floor toward zero)
        trunc_short = int(math.floor(agg_short))
        trunc_exempt = int(math.floor(agg_exempt))
        trunc_total = int(math.floor(agg_total))

        # Short ratio
        if trunc_total > 0:
            short_ratio = round(trunc_short / trunc_total, 6)
        else:
            short_ratio = 0.0

        if len(sym_venues) > 1:
            multi_count += 1
        else:
            single_count += 1

        symbols_output.append({
            "symbol": symbol,
            "short_volume": trunc_short,
            "short_exempt_volume": trunc_exempt,
            "total_volume": trunc_total,
            "short_ratio": short_ratio,
            "venues": sym_venues,
            "venue_breakdown": venue_breakdown,
        })

    report = {
        "total_symbols": len(all_symbols),
        "venues": sorted(venues),
        "multi_venue_count": multi_count,
        "single_venue_count": single_count,
        "symbols": symbols_output,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)


def parse_threshold_csv(filepath):
    """Parse the Reg SHO threshold securities list CSV."""
    records = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "tradeDate": row["tradeDate"].strip(),
                "symbol": row["issueSymbolIdentifier"].strip(),
                "issueName": row["issueName"].strip(),
                "marketClassCode": row["marketClassCode"].strip(),
                "regShoThresholdFlag": row["regShoThresholdFlag"].strip(),
                "rule4320Flag": row["rule4320Flag"].strip(),
            })
    return records


def threshold_monitor(filepath, output_path):
    """Monitor threshold securities for Reg SHO close-out requirements."""
    records = parse_threshold_csv(filepath)

    # Determine full settlement-day sequence from ALL dates
    all_dates = sorted(set(r["tradeDate"] for r in records))
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    # Track symbols and their flags
    # For regSho tracking: symbol -> set of dates
    regsho_dates = defaultdict(set)
    # Track which symbols have which flags (across all records)
    has_regsho = set()
    has_rule4320 = set()

    for r in records:
        sym = r["symbol"]
        if r["regShoThresholdFlag"] == "Y":
            regsho_dates[sym].add(r["tradeDate"])
            has_regsho.add(sym)
        if r["rule4320Flag"] == "Y":
            has_rule4320.add(sym)

    # Analyze consecutive settlement days for each regSho symbol
    closeout_triggered = []
    per_symbol = {}

    for sym in sorted(regsho_dates.keys()):
        dates = sorted(regsho_dates[sym])
        indices = [date_to_idx[d] for d in dates]

        max_consecutive = 1
        current_run = 1
        trigger_date = None
        trigger_count = None

        for i in range(1, len(indices)):
            if indices[i] == indices[i - 1] + 1:
                current_run += 1
            else:
                current_run = 1

            max_consecutive = max(max_consecutive, current_run)

            if current_run >= 5 and trigger_date is None:
                trigger_date = dates[i]
                trigger_count = current_run

        if len(indices) == 1:
            max_consecutive = 1

        closeout_required = trigger_date is not None

        per_symbol[sym] = {
            "dates_on_list": dates,
            "max_consecutive_days": max_consecutive,
            "closeout_required": closeout_required,
            "trigger_date": trigger_date,
        }

        if closeout_required:
            closeout_triggered.append({
                "symbol": sym,
                "trigger_date": trigger_date,
                "consecutive_days_at_trigger": trigger_count,
            })

    # Identify rule4320_only symbols
    rule4320_only = sorted(has_rule4320 - has_regsho)

    report = {
        "date_range": [all_dates[0], all_dates[-1]] if all_dates else [],
        "settlement_days": len(all_dates),
        "securities_tracked": len(regsho_dates),
        "closeout_triggered": sorted(closeout_triggered, key=lambda x: x["symbol"]),
        "rule4320_only": rule4320_only,
        "per_symbol": per_symbol,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="FINRA Reg SHO Compliance Auditor"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # verify-si
    p_si = subparsers.add_parser("verify-si",
                                 help="Verify consolidated short interest data")
    p_si.add_argument("csv_path", help="Path to consolidated SI CSV")

    # reconcile-venues
    p_rv = subparsers.add_parser("reconcile-venues",
                                 help="Reconcile per-venue short sale volumes")
    p_rv.add_argument("venue_files", nargs="+",
                      help="Paths to venue volume files")

    # threshold-monitor
    p_tm = subparsers.add_parser("threshold-monitor",
                                 help="Monitor threshold securities")
    p_tm.add_argument("csv_path", help="Path to threshold list CSV")

    args = parser.parse_args()

    output_dir = "/app/output"

    if args.command == "verify-si":
        verify_si(args.csv_path,
                  os.path.join(output_dir, "si_verification.json"))
    elif args.command == "reconcile-venues":
        reconcile_venues(args.venue_files,
                         os.path.join(output_dir, "venue_reconciliation.json"))
    elif args.command == "threshold-monitor":
        threshold_monitor(args.csv_path,
                          os.path.join(output_dir, "threshold_report.json"))


if __name__ == "__main__":
    main()
