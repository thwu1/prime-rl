#!/usr/bin/env python3
"""Populate shard databases with deterministic test data."""

import hashlib
import struct
import random
import json
import pymysql

random.seed(42)


def compute_keyspace_id(channel_id):
    key_bytes = struct.pack('>Q', channel_id)
    h = hashlib.md5(key_bytes).digest()
    return h[:8]


def get_shard_db(keyspace_id):
    if keyspace_id[0] < 0x80:
        return 'shard0'
    return 'shard1'


def main():
    conn = pymysql.connect(
        user='bench',
        password='bench123',
        unix_socket='/var/run/mysqld/mysqld.sock',
        autocommit=False
    )
    cursor = conn.cursor()

    channels = list(range(1, 2001))
    batch_size = 500

    # Generate messages: 10 per channel = 20000 total
    msg_batches = {'shard0': [], 'shard1': []}
    for channel_id in channels:
        kid = compute_keyspace_id(channel_id)
        db = get_shard_db(kid)
        workspace_id = random.randint(1, 100)
        for j in range(10):
            user_id = random.randint(1, 5000)
            content = f"Message {j} in channel {channel_id}"
            msg_batches[db].append((channel_id, user_id, workspace_id, content, kid))

    for db, rows in msg_batches.items():
        sql = f"INSERT INTO {db}.messages (channel_id, user_id, workspace_id, content, keyspace_id) VALUES (%s, %s, %s, %s, %s)"
        for i in range(0, len(rows), batch_size):
            cursor.executemany(sql, rows[i:i + batch_size])
        conn.commit()

    # Generate subscriptions: 10000 total
    sub_batches = {'shard0': [], 'shard1': []}
    for i in range(10000):
        channel_id = random.choice(channels)
        kid = compute_keyspace_id(channel_id)
        db = get_shard_db(kid)
        user_id = random.randint(1, 5000)
        thread_id = random.choice([None] * 3 + [random.randint(1, 50000)])
        workspace_id = random.randint(1, 100)
        sub_batches[db].append((user_id, channel_id, thread_id, workspace_id, 'active', kid))

    for db, rows in sub_batches.items():
        sql = f"INSERT INTO {db}.subscriptions (user_id, channel_id, thread_id, workspace_id, status, keyspace_id) VALUES (%s, %s, %s, %s, %s, %s)"
        for i in range(0, len(rows), batch_size):
            cursor.executemany(sql, rows[i:i + batch_size])
        conn.commit()

    # Record original counts for verification
    counts = {}
    for db in ['shard0', 'shard1']:
        for table in ['messages', 'subscriptions']:
            cursor.execute(f"SELECT COUNT(*) FROM {db}.{table}")
            counts[f"{db}.{table}"] = cursor.fetchone()[0]

    with open('/app/original_counts.json', 'w') as f:
        json.dump(counts, f, indent=2)

    print(f"Data populated: {counts}")

    cursor.close()
    conn.close()


if __name__ == '__main__':
    main()
