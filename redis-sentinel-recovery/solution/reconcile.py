#!/usr/bin/env python3
"""Reconcile divergent Redis datasets after split-brain event.
Implements dual-strategy conflict resolution: financial safety override + timestamp."""

import redis
import json

node_a = redis.Redis(host='127.0.0.1', port=6379, password='secretpass',
                     decode_responses=True)
node_b = redis.Redis(host='127.0.0.1', port=6380, password='secretpass',
                     decode_responses=True)

node_a.ping()
node_b.ping()

a_keys = set(node_a.keys('record:*'))
b_keys = set(node_b.keys('record:*'))

only_a = a_keys - b_keys
only_b = b_keys - a_keys
both = a_keys & b_keys

conflicts = []
node_a_wins = 0
node_b_wins = 0

for key in sorted(both, key=lambda k: int(k.split(':')[1])):
    a_raw = node_a.get(key)
    b_raw = node_b.get(key)
    a_data = json.loads(a_raw)
    b_data = json.loads(b_raw)

    if a_data == b_data:
        continue

    a_ts = a_data.get('updated_at', '')
    b_ts = b_data.get('updated_at', '')
    a_status = a_data.get('status', '')
    b_status = b_data.get('status', '')
    record_id = int(key.split(':')[1])

    # Financial safety override: refunded status always wins
    a_refunded = a_status == 'refunded'
    b_refunded = b_status == 'refunded'

    if b_refunded and not a_refunded:
        # B wins by financial safety
        node_a.set(key, json.dumps(b_data))
        node_b_wins += 1
        conflicts.append({
            "record_id": record_id,
            "winner": "node_b",
            "resolution_reason": "financial_safety",
            "node_a_updated_at": a_ts,
            "node_b_updated_at": b_ts
        })
    elif a_refunded and not b_refunded:
        # A wins by financial safety
        node_a_wins += 1
        conflicts.append({
            "record_id": record_id,
            "winner": "node_a",
            "resolution_reason": "financial_safety",
            "node_a_updated_at": a_ts,
            "node_b_updated_at": b_ts
        })
    elif a_ts > b_ts:
        # A wins by timestamp
        node_a_wins += 1
        conflicts.append({
            "record_id": record_id,
            "winner": "node_a",
            "resolution_reason": "timestamp",
            "node_a_updated_at": a_ts,
            "node_b_updated_at": b_ts
        })
    else:
        # B wins by timestamp
        node_a.set(key, json.dumps(b_data))
        node_b_wins += 1
        conflicts.append({
            "record_id": record_id,
            "winner": "node_b",
            "resolution_reason": "timestamp",
            "node_a_updated_at": a_ts,
            "node_b_updated_at": b_ts
        })

# Copy unique records from B to A
for key in sorted(only_b, key=lambda k: int(k.split(':')[1])):
    b_raw = node_b.get(key)
    node_a.set(key, b_raw)

total = len(node_a.keys('record:*'))

report = {
    "total_records": total,
    "conflicts": {
        "total": len(conflicts),
        "node_a_wins": node_a_wins,
        "node_b_wins": node_b_wins,
        "details": sorted(conflicts, key=lambda c: c['record_id'])
    },
    "unique_records": {
        "from_node_a": len(only_a),
        "from_node_b": len(only_b)
    }
}

with open('/app/reconciliation_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"Reconciliation complete:")
print(f"  Total records: {report['total_records']}")
print(f"  Conflicts resolved: {report['conflicts']['total']}")
print(f"  A wins: {node_a_wins}, B wins: {node_b_wins}")
print(f"  Financial safety overrides: {sum(1 for c in conflicts if c['resolution_reason'] == 'financial_safety')}")
print(f"  Unique from A: {len(only_a)}, Unique from B: {len(only_b)}")
