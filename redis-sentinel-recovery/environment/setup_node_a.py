#!/usr/bin/env python3
"""Populate Node A with its dataset for the split-brain scenario."""
import redis
import json

r = redis.Redis(host='127.0.0.1', port=6379, password='secretpass', decode_responses=True)
r.ping()

# Original records 1-100 (baseline, same as Node B before partition)
for i in range(1, 101):
    data = {
        "id": i,
        "customer": f"customer_{i:03d}",
        "email": f"customer_{i:03d}@example.com",
        "amount": round(100.0 + i * 7.5, 2),
        "status": "completed",
        "region": ["us-east", "us-west", "eu-west", "ap-south"][i % 4],
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T10:00:00Z"
    }
    r.set(f"record:{i}", json.dumps(data))

# A-side updates during partition (records modified only on Node A or with
# different values than Node B's modifications)
updates_a = {
    15: {"status": "cancelled", "updated_at": "2024-01-15T14:30:00Z"},
    32: {"amount": 500.00, "updated_at": "2024-01-15T14:45:00Z"},
    47: {"status": "cancelled", "updated_at": "2024-01-15T15:10:00Z"},
    63: {"region": "eu-central", "updated_at": "2024-01-15T15:25:00Z"},
    88: {"status": "cancelled", "updated_at": "2024-01-15T13:50:00Z"},
}
for rec_id, changes in updates_a.items():
    raw = r.get(f"record:{rec_id}")
    data = json.loads(raw)
    data.update(changes)
    r.set(f"record:{rec_id}", json.dumps(data))

# A-side new records 101-120 (created during partition)
a_timestamps = {
    101: "2024-01-15T14:00:00Z",
    102: "2024-01-15T14:10:00Z",
    103: "2024-01-15T14:15:00Z",
    104: "2024-01-15T14:25:00Z",
    105: "2024-01-15T14:30:00Z",
    106: "2024-01-15T14:40:00Z",
    107: "2024-01-15T14:45:00Z",
    108: "2024-01-15T14:55:00Z",
    109: "2024-01-15T15:00:00Z",
    110: "2024-01-15T15:10:00Z",
    111: "2024-01-15T15:15:00Z",
    112: "2024-01-15T15:20:00Z",
    113: "2024-01-15T15:25:00Z",
    114: "2024-01-15T15:30:00Z",
    115: "2024-01-15T15:35:00Z",
    116: "2024-01-15T15:40:00Z",
    117: "2024-01-15T15:45:00Z",
    118: "2024-01-15T15:50:00Z",
    119: "2024-01-15T15:55:00Z",
    120: "2024-01-15T16:00:00Z",
}
for i in range(101, 121):
    data = {
        "id": i,
        "customer": f"customer_{i:03d}",
        "email": f"customer_{i:03d}@example.com",
        "amount": round(200.0 + i * 3.0, 2),
        "status": "processing",
        "region": ["us-east", "us-west", "eu-west", "ap-south"][i % 4],
        "source": "node_a",
        "created_at": a_timestamps[i],
        "updated_at": a_timestamps[i]
    }
    r.set(f"record:{i}", json.dumps(data))

print(f"Node A populated with {r.dbsize()} keys")
