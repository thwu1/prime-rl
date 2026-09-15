#!/usr/bin/env python3
"""Load sorted set workload data into Redis.

Reproduces the production workload snapshot for analysis.
Requires Redis to be running on localhost:6379.
"""
import redis
import random
import sys


def main():
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        print("ERROR: Redis is not running on localhost:6379", file=sys.stderr)
        sys.exit(1)

    # Clear any existing data
    r.flushall()

    # Apply production configuration snapshot
    r.config_set('zset-max-listpack-entries', 500)
    r.config_set('zset-max-listpack-value', 64)

    random.seed(42)

    # Leaderboard sorted sets: 50 entries each (5 sets)
    for g in range(1, 6):
        key = f'leaderboard:game_{g}'
        members = {}
        for i in range(50):
            name = f'player_{i:04d}'
            score = round(random.uniform(0, 10000), 2)
            members[name] = score
        r.zadd(key, members)

    # Timeline sorted sets: 300 entries each (5 sets)
    for u in range(1, 6):
        key = f'timeline:user_{u}'
        members = {}
        for i in range(300):
            name = f'evt_{i:06d}'
            score = round(random.uniform(0, 1e6), 2)
            members[name] = score
        r.zadd(key, members)

    # Index sorted sets: 200 entries each (5 sets)
    for p in range(1, 6):
        key = f'index:product_{p}'
        members = {}
        for i in range(200):
            name = f'item_{i:05d}'
            score = round(random.uniform(0, 50000), 2)
            members[name] = score
        r.zadd(key, members)

    # Cache sorted sets: 450 entries each (5 sets)
    for c in range(1, 6):
        key = f'cache:scores_{c}'
        members = {}
        for i in range(450):
            name = f'sc_{i:05d}'
            score = round(random.uniform(-1000, 1000), 2)
            members[name] = score
        r.zadd(key, members)

    # Analytics sorted sets: 1000 entries each (5 sets)
    for d in range(1, 6):
        key = f'analytics:daily_{d}'
        members = {}
        for i in range(1000):
            name = f'metric_{i:06d}'
            score = round(random.uniform(0, 1e8), 2)
            members[name] = score
        r.zadd(key, members)

    # Non-sorted-set keys (various other data types in production)
    r.set('config:version', '2.1.0')
    r.hset('meta:stats', mapping={'total_sets': '25', 'last_update': '2024-03-15'})
    r.lpush('log:recent', 'startup complete', 'config loaded', 'data synced')

    total = r.dbsize()
    zset_count = sum(1 for k in r.keys('*') if r.type(k) == 'zset')
    config_val = r.config_get('zset-max-listpack-entries')
    print(f"Loaded {total} keys ({zset_count} sorted sets)")
    print(f"zset-max-listpack-entries = {config_val.get('zset-max-listpack-entries')}")


if __name__ == '__main__':
    main()
