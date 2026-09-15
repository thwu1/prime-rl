#!/usr/bin/env python3
"""
Solution for shard hotspot remediation: subdivide the overloaded shard
into two equal sub-shards, migrate data, update routing, add circuit
breaker, and verify consistency.
"""


import json
import sys
import os

import pymysql
import pymysql.cursors
import yaml

sys.path.insert(0, '/app')
from vhash import compute_keyspace_id, keyspace_id_in_range


def get_connection(database=None):
    params = {
        'user': 'bench',
        'password': 'bench123',
        'unix_socket': '/var/run/mysqld/mysqld.sock',
    }
    if database:
        params['database'] = database
    return pymysql.connect(**params)


def create_shard_databases():
    """Create shard1a and shard1b with schema copied from shard1."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("CREATE DATABASE IF NOT EXISTS shard1a")
    cursor.execute("CREATE DATABASE IF NOT EXISTS shard1b")

    # Get table list from shard1
    cursor.execute("SHOW TABLES FROM shard1")
    tables = [row[0] for row in cursor.fetchall()]

    for table in tables:
        # Create identical tables in new shards using LIKE
        cursor.execute(f"DROP TABLE IF EXISTS shard1a.`{table}`")
        cursor.execute(f"CREATE TABLE shard1a.`{table}` LIKE shard1.`{table}`")
        cursor.execute(f"DROP TABLE IF EXISTS shard1b.`{table}`")
        cursor.execute(f"CREATE TABLE shard1b.`{table}` LIKE shard1.`{table}`")

    conn.commit()
    cursor.close()
    conn.close()
    print("Created shard1a and shard1b databases with schema from shard1")


def migrate_data():
    """Migrate data from shard1 to shard1a (80-c0) and shard1b (c0-)."""
    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    for table in ['messages', 'subscriptions']:
        cursor.execute(f"SELECT * FROM shard1.`{table}`")
        rows = cursor.fetchall()

        if not rows:
            print(f"  {table}: no rows to migrate")
            continue

        columns = list(rows[0].keys())
        col_names = ', '.join([f'`{c}`' for c in columns])
        placeholders = ', '.join(['%s'] * len(columns))

        batch_1a = []
        batch_1b = []

        for row in rows:
            kid = row['keyspace_id']
            first_byte = kid[0]
            values = tuple(row[c] for c in columns)

            if first_byte < 0xc0:
                batch_1a.append(values)
            else:
                batch_1b.append(values)

        # Insert into shard1a in batches
        insert_sql_1a = f"INSERT INTO shard1a.`{table}` ({col_names}) VALUES ({placeholders})"
        batch_size = 1000
        for i in range(0, len(batch_1a), batch_size):
            cursor.executemany(insert_sql_1a, batch_1a[i:i + batch_size])
        conn.commit()

        # Insert into shard1b in batches
        insert_sql_1b = f"INSERT INTO shard1b.`{table}` ({col_names}) VALUES ({placeholders})"
        for i in range(0, len(batch_1b), batch_size):
            cursor.executemany(insert_sql_1b, batch_1b[i:i + batch_size])
        conn.commit()

        print(f"  {table}: {len(batch_1a)} rows -> shard1a, {len(batch_1b)} rows -> shard1b")

    # Truncate original shard1 tables
    plain_cursor = conn.cursor()
    for table in ['messages', 'subscriptions']:
        plain_cursor.execute(f"TRUNCATE TABLE shard1.`{table}`")
    conn.commit()
    plain_cursor.close()

    cursor.close()
    conn.close()
    print("Migration complete, shard1 tables truncated")


def update_config():
    """Update /app/config.yaml with new 3-shard topology."""
    config = {
        'keyspace': 'main',
        'shards': [
            {
                'name': '-80',
                'range_start': '',
                'range_end': '80',
                'database': 'shard0',
            },
            {
                'name': '80-c0',
                'range_start': '80',
                'range_end': 'c0',
                'database': 'shard1a',
            },
            {
                'name': 'c0-',
                'range_start': 'c0',
                'range_end': '',
                'database': 'shard1b',
            },
        ],
        'mysql': {
            'user': 'bench',
            'password': 'bench123',
            'socket': '/var/run/mysqld/mysqld.sock',
        },
    }

    with open('/app/config.yaml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    print("Updated config.yaml with 3-shard topology")


def write_circuit_breaker():
    """Write circuit breaker implementation to /app/circuit_breaker.py."""
    code = '''\
"""Circuit breaker pattern for shard query routing.

Protects database shards from cascading failures by tracking failure rates
and temporarily blocking requests to unhealthy shards.

State machine:
  closed -> open (after failure_threshold failures)
  open -> half_open (after recovery_timeout seconds)
  half_open -> closed (on success) or open (on failure)
"""

import time
import threading


class CircuitBreaker:
    """Thread-safe circuit breaker for database shard protection."""

    def __init__(self, failure_threshold=5, recovery_timeout=30.0,
                 half_open_max_requests=1):
        self._lock = threading.Lock()
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_requests = half_open_max_requests

        self._state = 'closed'
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_requests = 0

    @property
    def state(self):
        with self._lock:
            self._check_state_transition()
            return self._state

    def _check_state_transition(self):
        """Auto-transition from open to half_open after recovery timeout."""
        if self._state == 'open':
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._state = 'half_open'
                self._half_open_requests = 0

    def allow_request(self):
        """Check if a request should be allowed through.

        Returns True if allowed, False if the circuit is open.
        """
        with self._lock:
            self._check_state_transition()

            if self._state == 'closed':
                return True
            elif self._state == 'open':
                return False
            elif self._state == 'half_open':
                if self._half_open_requests < self._half_open_max_requests:
                    self._half_open_requests += 1
                    return True
                return False
        return False

    def record_success(self):
        """Record a successful request. Resets to closed if in half_open."""
        with self._lock:
            if self._state == 'half_open':
                self._state = 'closed'
            self._failure_count = 0

    def record_failure(self):
        """Record a failed request. Opens the circuit if threshold reached."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == 'half_open':
                self._state = 'open'
                self._half_open_requests = 0
            elif self._failure_count >= self._failure_threshold:
                self._state = 'open'

    def reset(self):
        """Manually reset to closed state."""
        with self._lock:
            self._state = 'closed'
            self._failure_count = 0
            self._half_open_requests = 0
'''

    with open('/app/circuit_breaker.py', 'w') as f:
        f.write(code)

    print("Wrote circuit breaker to /app/circuit_breaker.py")


def run_vdiff():
    """Run VDiff consistency verification and write report."""
    with open('/app/original_counts.json') as f:
        original = json.load(f)

    conn = get_connection()
    cursor = conn.cursor()

    report = {}

    for table in ['messages', 'subscriptions']:
        source_count = original[f'shard1.{table}']

        cursor.execute(f"SELECT COUNT(*) FROM shard1a.`{table}`")
        count_1a = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM shard1b.`{table}`")
        count_1b = cursor.fetchone()[0]

        target_count = count_1a + count_1b

        # Verify keyspace_id routing correctness
        misrouted = 0

        cursor.execute(f"SELECT keyspace_id FROM shard1a.`{table}`")
        for (kid,) in cursor.fetchall():
            if not (0x80 <= kid[0] < 0xc0):
                misrouted += 1

        cursor.execute(f"SELECT keyspace_id FROM shard1b.`{table}`")
        for (kid,) in cursor.fetchall():
            if kid[0] < 0xc0:
                misrouted += 1

        consistent = (source_count == target_count) and (misrouted == 0)

        report[table] = {
            'consistent': consistent,
            'source_row_count': source_count,
            'target_row_count': target_count,
        }

    cursor.close()
    conn.close()

    with open('/app/vdiff_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("VDiff report:")
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    print("=== Shard Hotspot Remediation ===")

    print("\n[1/5] Creating new shard databases...")
    create_shard_databases()

    print("\n[2/5] Migrating data from shard1...")
    migrate_data()

    print("\n[3/5] Updating routing configuration...")
    update_config()

    print("\n[4/5] Writing circuit breaker module...")
    write_circuit_breaker()

    print("\n[5/5] Running VDiff consistency verification...")
    run_vdiff()

    print("\n=== Remediation complete ===")
