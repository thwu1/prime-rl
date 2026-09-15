#!/usr/bin/env python3
"""
Ledger Reconciliation — Solution

Connects to the PostgreSQL ledger database, analyzes clearing, timeliness,
and completeness, and writes the DQ report.
"""
import psycopg2
import csv
import json
import os
from collections import defaultdict


def load_events():
    conn = psycopg2.connect(dbname="ledger", user="ledger", host="localhost")
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, event_type, fund_flow, transaction_id, "
        "account_from, account_to, amount, currency, business_id, created_at "
        "FROM ledger_events"
    )
    rows = []
    for r in cur.fetchall():
        rows.append({
            "event_id": r[0],
            "event_type": r[1],
            "fund_flow": r[2],
            "transaction_id": r[3],
            "account_from": r[4],
            "account_to": r[5],
            "amount": float(r[6]),
            "currency": r[7],
            "business_id": r[8],
            "created_at": r[9],
        })
    conn.close()
    return rows


def load_reference(path="/app/data/bank_settlements.csv"):
    refs = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            refs[r["transaction_id"]] = r["expected_fund_flow"]
    return refs


def main():
    events = load_events()
    refs = load_reference()

    with open("/app/config/fund_flows.json") as f:
        fund_flows = json.load(f)
    with open("/app/config/thresholds.json") as f:
        thresholds = json.load(f)

    tol = thresholds["clearing_balance_tolerance"]
    threshold_h = thresholds["timeliness_threshold_hours"]

    # Group events by (fund_flow, transaction_id)
    by_flow_txn = defaultdict(lambda: defaultdict(list))
    for e in events:
        by_flow_txn[e["fund_flow"]][e["transaction_id"]].append(e)

    # ---- Clearing analysis ----
    clearing_result = {}
    total_uncleared_all = 0
    total_txns_all = 0

    for flow, cfg in fund_flows.items():
        intermediate = set(cfg["intermediate_accounts"])
        n_expected_types = len(cfg["events"])
        txns = by_flow_txn[flow]
        uncleared = []

        for tid, evts in txns.items():
            # Net balance per (intermediate_account, business_id, currency)
            balances = defaultdict(float)
            for e in evts:
                if e["account_to"] in intermediate:
                    balances[(e["account_to"], e["business_id"], e["currency"])] += e["amount"]
                if e["account_from"] in intermediate:
                    balances[(e["account_from"], e["business_id"], e["currency"])] -= e["amount"]

            if not any(abs(v) > tol for v in balances.values()):
                continue

            # Classify root cause
            types_seen = set(e["event_type"] for e in evts)
            if len(types_seen) < n_expected_types:
                cause = "missing_counterpart"
            elif len(evts) > n_expected_types:
                cause = "duplicate"
            else:
                amounts = set(e["amount"] for e in evts)
                biz_ids = set(e["business_id"] for e in evts)
                if len(amounts) > 1:
                    cause = "amount_mismatch"
                elif len(biz_ids) > 1:
                    cause = "property_mismatch"
                else:
                    cause = "unknown"

            uncleared.append({"transaction_id": tid, "root_cause": cause})

        total = len(txns)
        score = round(1.0 - len(uncleared) / total, 6) if total > 0 else 1.0
        clearing_result[flow] = {
            "score": score,
            "total_transactions": total,
            "uncleared_transactions": sorted(uncleared, key=lambda u: u["transaction_id"]),
        }
        total_uncleared_all += len(uncleared)
        total_txns_all += total

    # ---- Timeliness analysis ----
    late = []
    for flow in fund_flows:
        for tid, evts in by_flow_txn[flow].items():
            if len(evts) >= 2:
                times = sorted(e["created_at"] for e in evts)
                delta_h = (times[-1] - times[0]).total_seconds() / 3600
                if delta_h > threshold_h:
                    late.append(tid)

    # ---- Completeness analysis ----
    all_txn_ids = set()
    for ft in by_flow_txn.values():
        all_txn_ids.update(ft.keys())
    missing = sorted(tid for tid in refs if tid not in all_txn_ids)

    # ---- Scores ----
    clearing_score = 1.0 - total_uncleared_all / total_txns_all if total_txns_all else 1.0
    timeliness_score = 1.0 - len(late) / total_txns_all if total_txns_all else 1.0
    completeness_score = (len(refs) - len(missing)) / len(refs) if refs else 1.0
    overall = (clearing_score + timeliness_score + completeness_score) / 3

    # ---- Output ----
    os.makedirs("/app/output", exist_ok=True)
    report = {
        "summary": {
            "total_events": len(events),
            "total_transactions": total_txns_all,
            "overall_dq_score": round(overall, 6),
        },
        "clearing": clearing_result,
        "timeliness": {
            "threshold_hours": threshold_h,
            "total_late": len(late),
            "late_transactions": sorted(late),
        },
        "completeness": {
            "total_expected": len(refs),
            "total_found": len(refs) - len(missing),
            "missing_transactions": missing,
        },
    }

    with open("/app/output/dq_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"DQ report written. Overall={overall:.6f}, "
          f"clearing_issues={total_uncleared_all}, late={len(late)}, missing={len(missing)}")


if __name__ == "__main__":
    main()
