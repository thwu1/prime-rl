#!/usr/bin/env python3
import redis
import json

r = redis.Redis(host='127.0.0.1', port=6379, password='secretpass', decode_responses=True)
r.ping()

for i in range(1, 51):
    data = {
        'id': i,
        'customer': f'customer_{i:03d}',
        'amount': round(10.0 + i * 2.5, 2),
        'status': 'completed',
        'region': ['us-east', 'us-west', 'eu-west', 'ap-south'][i % 4]
    }
    r.set(f'record:{i}', json.dumps(data))

print(f"Populated {r.dbsize()} keys in master")

pending = []
for i in range(51, 76):
    data = {
        'id': i,
        'customer': f'customer_{i:03d}',
        'amount': round(10.0 + i * 2.5, 2),
        'status': 'pending',
        'region': ['us-east', 'us-west', 'eu-west', 'ap-south'][i % 4]
    }
    pending.append({'key': f'record:{i}', 'value': data})

with open('/app/recovery/pending_writes.json', 'w') as f:
    json.dump(pending, f, indent=2)

print(f"Generated {len(pending)} pending writes to /app/recovery/pending_writes.json")
