
import json
import csv
import os
import pytest
import psycopg2
from collections import defaultdict


REFERENCE_PATH = "/app/data/bank_settlements.csv"
FUND_FLOWS_PATH = "/app/config/fund_flows.json"
THRESHOLDS_PATH = "/app/config/thresholds.json"
OUTPUT_PATH = "/app/output/dq_report.json"


def _load_events():
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


def _load_reference():
    refs = {}
    with open(REFERENCE_PATH) as f:
        for r in csv.DictReader(f):
            refs[r["transaction_id"]] = r["expected_fund_flow"]
    return refs


def _compute_expected():
    events = _load_events()
    with open(FUND_FLOWS_PATH) as f:
        fund_flows = json.load(f)
    with open(THRESHOLDS_PATH) as f:
        thresholds = json.load(f)
    refs = _load_reference()

    by_flow_txn = defaultdict(lambda: defaultdict(list))
    for e in events:
        by_flow_txn[e["fund_flow"]][e["transaction_id"]].append(e)

    # --- Clearing ---
    clearing = {}
    total_uncleared_all = 0
    total_txns_all = 0
    tol = thresholds["clearing_balance_tolerance"]

    for flow, cfg in fund_flows.items():
        intermediate = set(cfg["intermediate_accounts"])
        n_exp_types = len(cfg["events"])
        txns = by_flow_txn[flow]
        uncleared = []

        for tid, evts in txns.items():
            bals = defaultdict(float)
            for e in evts:
                if e["account_to"] in intermediate:
                    bals[(e["account_to"], e["business_id"], e["currency"])] += e["amount"]
                if e["account_from"] in intermediate:
                    bals[(e["account_from"], e["business_id"], e["currency"])] -= e["amount"]

            if any(abs(v) > tol for v in bals.values()):
                types_seen = set(e["event_type"] for e in evts)
                if len(types_seen) < n_exp_types:
                    cause = "missing_counterpart"
                elif len(evts) > n_exp_types:
                    cause = "duplicate"
                else:
                    if len(set(e["amount"] for e in evts)) > 1:
                        cause = "amount_mismatch"
                    elif len(set(e["business_id"] for e in evts)) > 1:
                        cause = "property_mismatch"
                    else:
                        cause = "unknown"
                uncleared.append({"transaction_id": tid, "root_cause": cause})

        total = len(txns)
        score = round(1.0 - len(uncleared) / total, 6) if total > 0 else 1.0
        clearing[flow] = {
            "score": score,
            "total": total,
            "uncleared": {u["transaction_id"]: u["root_cause"] for u in uncleared},
        }
        total_uncleared_all += len(uncleared)
        total_txns_all += total

    # --- Timeliness ---
    threshold_h = thresholds["timeliness_threshold_hours"]
    late = set()
    for flow in fund_flows:
        for tid, evts in by_flow_txn[flow].items():
            if len(evts) >= 2:
                times = sorted(e["created_at"] for e in evts)
                if (times[-1] - times[0]).total_seconds() / 3600 > threshold_h:
                    late.add(tid)

    # --- Completeness ---
    all_txn_ids = set()
    for ft in by_flow_txn.values():
        all_txn_ids.update(ft.keys())
    missing = set(tid for tid in refs if tid not in all_txn_ids)

    # --- Scores ---
    clearing_score = 1.0 - total_uncleared_all / total_txns_all if total_txns_all else 1.0
    timeliness_score = 1.0 - len(late) / total_txns_all if total_txns_all else 1.0
    completeness_score = (len(refs) - len(missing)) / len(refs) if refs else 1.0
    overall = (clearing_score + timeliness_score + completeness_score) / 3

    return {
        "clearing": clearing,
        "late": late,
        "missing": missing,
        "total_events": len(events),
        "total_transactions": total_txns_all,
        "overall_dq": overall,
        "total_expected_refs": len(refs),
    }


@pytest.fixture(scope="module")
def expected():
    return _compute_expected()


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(OUTPUT_PATH), f"Output not found at {OUTPUT_PATH}"
    with open(OUTPUT_PATH) as f:
        return json.load(f)


# ---- Structure tests ----

class TestStructure:
    def test_top_level_keys(self, report):
        for k in ("summary", "clearing", "timeliness", "completeness"):
            assert k in report, f"Missing top-level key: {k}"

    def test_summary_keys(self, report):
        for k in ("total_events", "total_transactions", "overall_dq_score"):
            assert k in report["summary"], f"Missing summary key: {k}"

    def test_clearing_flows(self, report):
        for flow in ("charge_lifecycle", "refund_lifecycle", "payout_lifecycle"):
            assert flow in report["clearing"], f"Missing clearing flow: {flow}"


# ---- Counts ----

class TestCounts:
    def test_total_events(self, report, expected):
        assert report["summary"]["total_events"] == expected["total_events"]

    def test_total_transactions(self, report, expected):
        assert report["summary"]["total_transactions"] == expected["total_transactions"]


# ---- Clearing ----

class TestChargeClearing:
    def test_score(self, report, expected):
        got = report["clearing"]["charge_lifecycle"]["score"]
        exp = expected["clearing"]["charge_lifecycle"]["score"]
        assert abs(got - exp) < 0.002, f"charge clearing score {got} != {exp}"

    def test_uncleared_ids_and_causes(self, report, expected):
        exp_map = expected["clearing"]["charge_lifecycle"]["uncleared"]
        got_list = report["clearing"]["charge_lifecycle"]["uncleared_transactions"]
        got_map = {u["transaction_id"]: u["root_cause"] for u in got_list}
        assert set(got_map.keys()) == set(exp_map.keys()), (
            f"charge ID mismatch: missing={set(exp_map) - set(got_map)}, "
            f"extra={set(got_map) - set(exp_map)}"
        )
        for tid, cause in exp_map.items():
            assert got_map[tid] == cause, f"{tid}: got {got_map[tid]}, exp {cause}"


class TestRefundClearing:
    def test_score(self, report, expected):
        got = report["clearing"]["refund_lifecycle"]["score"]
        exp = expected["clearing"]["refund_lifecycle"]["score"]
        assert abs(got - exp) < 0.002, f"refund clearing score {got} != {exp}"

    def test_uncleared_ids_and_causes(self, report, expected):
        exp_map = expected["clearing"]["refund_lifecycle"]["uncleared"]
        got_list = report["clearing"]["refund_lifecycle"]["uncleared_transactions"]
        got_map = {u["transaction_id"]: u["root_cause"] for u in got_list}
        assert set(got_map.keys()) == set(exp_map.keys()), (
            f"refund ID mismatch: missing={set(exp_map) - set(got_map)}, "
            f"extra={set(got_map) - set(exp_map)}"
        )
        for tid, cause in exp_map.items():
            assert got_map[tid] == cause, f"{tid}: got {got_map[tid]}, exp {cause}"


class TestPayoutClearing:
    def test_score(self, report, expected):
        got = report["clearing"]["payout_lifecycle"]["score"]
        exp = expected["clearing"]["payout_lifecycle"]["score"]
        assert abs(got - exp) < 0.002, f"payout clearing score {got} != {exp}"

    def test_uncleared_ids_and_causes(self, report, expected):
        exp_map = expected["clearing"]["payout_lifecycle"]["uncleared"]
        got_list = report["clearing"]["payout_lifecycle"]["uncleared_transactions"]
        got_map = {u["transaction_id"]: u["root_cause"] for u in got_list}
        assert set(got_map.keys()) == set(exp_map.keys()), (
            f"payout ID mismatch: missing={set(exp_map) - set(got_map)}, "
            f"extra={set(got_map) - set(exp_map)}"
        )
        for tid, cause in exp_map.items():
            assert got_map[tid] == cause, f"{tid}: got {got_map[tid]}, exp {cause}"


# ---- Timeliness ----

class TestTimeliness:
    def test_late_count(self, report, expected):
        assert report["timeliness"]["total_late"] == len(expected["late"])

    def test_late_ids(self, report, expected):
        got = set(report["timeliness"]["late_transactions"])
        assert got == expected["late"], (
            f"late mismatch: missing={expected['late'] - got}, extra={got - expected['late']}"
        )


# ---- Completeness ----

class TestCompleteness:
    def test_missing_count(self, report, expected):
        got = len(report["completeness"]["missing_transactions"])
        assert got == len(expected["missing"])

    def test_missing_ids(self, report, expected):
        got = set(report["completeness"]["missing_transactions"])
        assert got == expected["missing"], (
            f"missing mismatch: missing={expected['missing'] - got}, extra={got - expected['missing']}"
        )


# ---- Overall DQ ----

class TestOverallDQ:
    def test_overall_score(self, report, expected):
        got = report["summary"]["overall_dq_score"]
        exp = expected["overall_dq"]
        assert abs(got - exp) < 0.005, f"overall DQ {got} != {exp}"
