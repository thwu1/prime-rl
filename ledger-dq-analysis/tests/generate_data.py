#!/usr/bin/env python3
"""Generate deterministic ledger event data with injected DQ issues.
Used at Docker build time and as runtime fallback. Deterministic via seed."""
import csv
import json
import random
import os
from datetime import datetime, timedelta

random.seed(42)

NUM_CHARGES = 5000
NUM_REFUNDS = 2000
NUM_PAYOUTS = 1000
NUM_MISSING_REF = 14

businesses = [f"biz_{i:04d}" for i in range(200)]
currencies_pool = ["usd"] * 70 + ["eur"] * 15 + ["gbp"] * 10 + ["jpy"] * 5
BASE = datetime(2024, 1, 1)

evt_counter = [0]


def eid():
    evt_counter[0] += 1
    return f"evt_{evt_counter[0]:08d}"


def ts(h):
    return (BASE + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S")


def amt():
    return round(random.uniform(5.0, 9999.99), 2)


# ---------------------------------------------------------------------------
# Deterministically select which transactions have which issues.
# Each set is mutually exclusive within a fund flow.
# ---------------------------------------------------------------------------

# Charges: 37 missing capture, 20 late, 6 duplicates
c_idx = list(range(NUM_CHARGES))
random.shuffle(c_idx)
MISSING_CAP = set(c_idx[:37])
rem = [i for i in c_idx if i not in MISSING_CAP]
random.shuffle(rem)
LATE_C = set(rem[:20])
rem2 = [i for i in rem if i not in LATE_C]
random.shuffle(rem2)
DUP_C = set(rem2[:6])

# Refunds: 19 amount mismatch, 11 late, 5 duplicates
r_idx = list(range(NUM_REFUNDS))
random.shuffle(r_idx)
AMT_MIS = set(r_idx[:19])
rem = [i for i in r_idx if i not in AMT_MIS]
random.shuffle(rem)
LATE_R = set(rem[:11])
rem2 = [i for i in rem if i not in LATE_R]
random.shuffle(rem2)
DUP_R = set(rem2[:5])

# Payouts: 23 business_id mismatch, 7 late, 3 duplicates
p_idx = list(range(NUM_PAYOUTS))
random.shuffle(p_idx)
BIZ_MIS = set(p_idx[:23])
rem = [i for i in p_idx if i not in BIZ_MIS]
random.shuffle(rem)
LATE_P = set(rem[:7])
rem2 = [i for i in rem if i not in LATE_P]
random.shuffle(rem2)
DUP_P = set(rem2[:3])

# ---------------------------------------------------------------------------
# Generate events
# ---------------------------------------------------------------------------
events = []
ref_ids = {}

for i in range(NUM_CHARGES):
    tid = f"ch_{i:06d}"
    biz = random.choice(businesses)
    a = amt()
    cur = random.choice(currencies_pool)
    t0 = i * 0.5
    ref_ids[tid] = "charge_lifecycle"

    events.append(dict(
        event_id=eid(), event_type="charge.created",
        fund_flow="charge_lifecycle", transaction_id=tid,
        account_from="external_source", account_to="charge_pending",
        amount=a, currency=cur, business_id=biz, timestamp=ts(t0)))

    if i in MISSING_CAP:
        continue

    delay = random.uniform(0.1, 4.0)
    if i in LATE_C:
        delay = random.uniform(25, 96)

    cap = dict(
        event_id=eid(), event_type="charge.captured",
        fund_flow="charge_lifecycle", transaction_id=tid,
        account_from="charge_pending", account_to="merchant_available",
        amount=a, currency=cur, business_id=biz, timestamp=ts(t0 + delay))
    events.append(cap)

    if i in DUP_C:
        dup = dict(cap)
        dup["event_id"] = eid()
        events.append(dup)

for i in range(NUM_REFUNDS):
    tid = f"rf_{i:06d}"
    biz = random.choice(businesses)
    a = amt()
    cur = random.choice(currencies_pool)
    t0 = NUM_CHARGES * 0.5 + i * 0.3
    ref_ids[tid] = "refund_lifecycle"

    events.append(dict(
        event_id=eid(), event_type="refund.initiated",
        fund_flow="refund_lifecycle", transaction_id=tid,
        account_from="merchant_available", account_to="refund_pending",
        amount=a, currency=cur, business_id=biz, timestamp=ts(t0)))

    delay = random.uniform(0.5, 6.0)
    if i in LATE_R:
        delay = random.uniform(25, 96)

    settled_amount = a
    if i in AMT_MIS:
        delta = random.uniform(1.0, min(a * 0.3, 500.0))
        if random.random() < 0.5:
            delta = -delta
        settled_amount = round(a + delta, 2)
        if settled_amount < 1.0:
            settled_amount = round(a + abs(delta), 2)

    sev = dict(
        event_id=eid(), event_type="refund.settled",
        fund_flow="refund_lifecycle", transaction_id=tid,
        account_from="refund_pending", account_to="external_destination",
        amount=settled_amount, currency=cur, business_id=biz,
        timestamp=ts(t0 + delay))
    events.append(sev)

    if i in DUP_R:
        dup = dict(sev)
        dup["event_id"] = eid()
        events.append(dup)

for i in range(NUM_PAYOUTS):
    tid = f"po_{i:06d}"
    biz = random.choice(businesses)
    a = amt()
    cur = random.choice(currencies_pool)
    t0 = NUM_CHARGES * 0.5 + NUM_REFUNDS * 0.3 + i * 0.4
    ref_ids[tid] = "payout_lifecycle"

    events.append(dict(
        event_id=eid(), event_type="payout.created",
        fund_flow="payout_lifecycle", transaction_id=tid,
        account_from="merchant_available", account_to="payout_pending",
        amount=a, currency=cur, business_id=biz, timestamp=ts(t0)))

    delay = random.uniform(1.0, 12.0)
    if i in LATE_P:
        delay = random.uniform(25, 96)

    comp_biz = biz
    if i in BIZ_MIS:
        others = [b for b in businesses if b != biz]
        comp_biz = random.choice(others)

    cev = dict(
        event_id=eid(), event_type="payout.completed",
        fund_flow="payout_lifecycle", transaction_id=tid,
        account_from="payout_pending", account_to="bank_settlement",
        amount=a, currency=cur, business_id=comp_biz,
        timestamp=ts(t0 + delay))
    events.append(cev)

    if i in DUP_P:
        dup = dict(cev)
        dup["event_id"] = eid()
        events.append(dup)

# Shuffle events to simulate real-world arrival disorder
random.shuffle(events)

# Add phantom reference IDs (expected upstream but no events exist)
for i in range(NUM_MISSING_REF):
    mid = f"ch_{NUM_CHARGES + i:06d}"
    ref_ids[mid] = "charge_lifecycle"

# ---------------------------------------------------------------------------
# Write output files
# ---------------------------------------------------------------------------
os.makedirs("/opt/ledger/data", exist_ok=True)
os.makedirs("/opt/ledger/config", exist_ok=True)

fields = ["event_id", "event_type", "fund_flow", "transaction_id",
          "account_from", "account_to", "amount", "currency",
          "business_id", "timestamp"]
with open("/opt/ledger/data/events.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for e in events:
        w.writerow(e)

with open("/opt/ledger/data/reference_ids.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["transaction_id", "expected_fund_flow"])
    for tid in sorted(ref_ids.keys()):
        w.writerow([tid, ref_ids[tid]])

with open("/opt/ledger/config/fund_flows.json", "w") as f:
    json.dump({
        "charge_lifecycle": {
            "events": ["charge.created", "charge.captured"],
            "intermediate_accounts": ["charge_pending"],
            "terminal_accounts": ["external_source", "merchant_available"],
            "description": "Funds flow from external source through charge_pending to merchant_available"
        },
        "refund_lifecycle": {
            "events": ["refund.initiated", "refund.settled"],
            "intermediate_accounts": ["refund_pending"],
            "terminal_accounts": ["merchant_available", "external_destination"],
            "description": "Funds flow from merchant_available through refund_pending to external_destination"
        },
        "payout_lifecycle": {
            "events": ["payout.created", "payout.completed"],
            "intermediate_accounts": ["payout_pending"],
            "terminal_accounts": ["merchant_available", "bank_settlement"],
            "description": "Funds flow from merchant_available through payout_pending to bank_settlement"
        }
    }, f, indent=2)

with open("/opt/ledger/config/thresholds.json", "w") as f:
    json.dump({
        "timeliness_threshold_hours": 24,
        "clearing_balance_tolerance": 0.01
    }, f, indent=2)

print(f"Generated {len(events)} events across {len(ref_ids)} referenced transactions")
