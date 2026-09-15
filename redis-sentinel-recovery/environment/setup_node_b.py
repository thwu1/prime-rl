#!/usr/bin/env python3
"""Populate Node B with its dataset for the split-brain scenario."""
import redis
import json

r = redis.Redis(host='127.0.0.1', port=6380, password='secretpass', decode_responses=True)
r.ping()

# Original records 1-100 (same baseline as Node A before partition)
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

# B-side updates during partition
updates_b = {
    15: {"status": "refunded", "updated_at": "2024-01-15T14:45:00Z"},
    47: {"status": "refunded", "updated_at": "2024-01-15T14:50:00Z"},
    71: {"status": "refunded", "updated_at": "2024-01-15T15:00:00Z"},
    92: {"amount": 750.00, "updated_at": "2024-01-15T15:30:00Z"},
}
for rec_id, changes in updates_b.items():
    raw = r.get(f"record:{rec_id}")
    data = json.loads(raw)
    data.update(changes)
    r.set(f"record:{rec_id}", json.dumps(data))

# B-side records 101-110 (different data from A's 101-110)
b_overlap_timestamps = {
    101: "2024-01-15T14:05:00Z",
    102: "2024-01-15T14:02:00Z",
    103: "2024-01-15T14:20:00Z",
    104: "2024-01-15T14:12:00Z",
    105: "2024-01-15T14:35:00Z",
    106: "2024-01-15T14:28:00Z",
    107: "2024-01-15T14:50:00Z",
    108: "2024-01-15T14:42:00Z",
    109: "2024-01-15T15:05:00Z",
    110: "2024-01-15T14:58:00Z",
}
for i in range(101, 111):
    data = {
        "id": i,
        "customer": f"customer_{i:03d}",
        "email": f"customer_{i:03d}@example.com",
        "amount": round(300.0 + i * 5.0, 2),
        "status": "confirmed",
        "region": ["eu-west", "ap-south", "us-east", "us-west"][i % 4],
        "source": "node_b",
        "created_at": b_overlap_timestamps[i],
        "updated_at": b_overlap_timestamps[i]
    }
    r.set(f"record:{i}", json.dumps(data))

# B-side unique records 121-130
b_unique_timestamps = {
    121: "2024-01-15T14:10:00Z",
    122: "2024-01-15T14:18:00Z",
    123: "2024-01-15T14:26:00Z",
    124: "2024-01-15T14:34:00Z",
    125: "2024-01-15T14:42:00Z",
    126: "2024-01-15T14:50:00Z",
    127: "2024-01-15T14:58:00Z",
    128: "2024-01-15T15:06:00Z",
    129: "2024-01-15T15:14:00Z",
    130: "2024-01-15T15:22:00Z",
}
for i in range(121, 131):
    data = {
        "id": i,
        "customer": f"customer_{i:03d}",
        "email": f"customer_{i:03d}@example.com",
        "amount": round(400.0 + i * 4.0, 2),
        "status": "confirmed",
        "region": ["eu-west", "ap-south", "us-east", "us-west"][i % 4],
        "source": "node_b",
        "created_at": b_unique_timestamps[i],
        "updated_at": b_unique_timestamps[i]
    }
    r.set(f"record:{i}", json.dumps(data))

r.save()
print(f"Node B populated with {r.dbsize()} keys")
