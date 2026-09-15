#!/usr/bin/env python3
"""Import pending customer records that arrived during the Redis outage."""

import redis
import json

PENDING_FILE = '/app/recovery/pending_writes.json'

r = redis.Redis(host='127.0.0.1', port=6379, password='secretpass',
                decode_responses=True)

with open(PENDING_FILE) as f:
    pending = json.load(f)

imported = 0
for item in pending:
    r.set(item['key'], json.dumps(item['value']))
    imported += 1

print(f"Imported {imported} records from {PENDING_FILE}")
print(f"Total records in Redis: {r.dbsize()}")
