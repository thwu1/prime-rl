"""Tests for shard hotspot remediation task.

Verifies that shard 80- was correctly subdivided, data integrity
is preserved, routing config is valid, circuit breaker works,
and VDiff report shows consistency.
"""


import pytest
import json
import yaml
import sys
import os
import importlib
import time

import pymysql
import pymysql.cursors


def get_mysql_connection(database=None):
    params = {
        'user': 'bench',
        'password': 'bench123',
        'unix_socket': '/var/run/mysqld/mysqld.sock',
    }
    if database:
        params['database'] = database
    return pymysql.connect(**params)


def get_row_count(database, table):
    conn = get_mysql_connection(database)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count


def get_all_keyspace_ids(database, table):
    conn = get_mysql_connection(database)
    cursor = conn.cursor()
    cursor.execute(f"SELECT keyspace_id FROM `{table}`")
    results = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return results


def database_exists(db_name):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute("SHOW DATABASES")
    dbs = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return db_name in dbs


def get_table_names(database):
    conn = get_mysql_connection(database)
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return tables


class TestShardDatabasesExist:
    """Verify the new shard databases were created correctly."""

    def test_shard1a_exists(self):
        assert database_exists('shard1a'), "Database shard1a must exist"

    def test_shard1b_exists(self):
        assert database_exists('shard1b'), "Database shard1b must exist"

    def test_shard0_still_exists(self):
        assert database_exists('shard0'), "Database shard0 must still exist"

    def test_old_shard1_empty_or_removed(self):
        if database_exists('shard1'):
            tables = get_table_names('shard1')
            if 'messages' in tables:
                assert get_row_count('shard1', 'messages') == 0, \
                    "shard1.messages should be empty after resharding"
            if 'subscriptions' in tables:
                assert get_row_count('shard1', 'subscriptions') == 0, \
                    "shard1.subscriptions should be empty after resharding"


class TestSchemaCorrectness:
    """Verify new shards have correct table structure."""

    def test_shard1a_has_messages(self):
        tables = get_table_names('shard1a')
        assert 'messages' in tables, "shard1a must have messages table"

    def test_shard1a_has_subscriptions(self):
        tables = get_table_names('shard1a')
        assert 'subscriptions' in tables, "shard1a must have subscriptions table"

    def test_shard1b_has_messages(self):
        tables = get_table_names('shard1b')
        assert 'messages' in tables, "shard1b must have messages table"

    def test_shard1b_has_subscriptions(self):
        tables = get_table_names('shard1b')
        assert 'subscriptions' in tables, "shard1b must have subscriptions table"


class TestDataDistribution:
    """Verify data is correctly distributed across shards by key range."""

    def test_shard0_keyspace_ids_in_range(self):
        """All rows in shard0 must have keyspace_id first byte < 0x80."""
        for table in ['messages', 'subscriptions']:
            kids = get_all_keyspace_ids('shard0', table)
            for kid in kids:
                assert kid[0] < 0x80, \
                    f"shard0.{table} has row with keyspace_id {kid.hex()} outside range -80"

    def test_shard1a_keyspace_ids_in_range(self):
        """All rows in shard1a must have keyspace_id first byte in [0x80, 0xc0)."""
        for table in ['messages', 'subscriptions']:
            kids = get_all_keyspace_ids('shard1a', table)
            for kid in kids:
                assert 0x80 <= kid[0] < 0xc0, \
                    f"shard1a.{table} has row with keyspace_id {kid.hex()} outside range 80-c0"

    def test_shard1b_keyspace_ids_in_range(self):
        """All rows in shard1b must have keyspace_id first byte >= 0xc0."""
        for table in ['messages', 'subscriptions']:
            kids = get_all_keyspace_ids('shard1b', table)
            for kid in kids:
                assert kid[0] >= 0xc0, \
                    f"shard1b.{table} has row with keyspace_id {kid.hex()} outside range c0-"

    def test_shard1a_not_empty(self):
        """shard1a must contain data."""
        assert get_row_count('shard1a', 'messages') > 0, "shard1a.messages must not be empty"
        assert get_row_count('shard1a', 'subscriptions') > 0, "shard1a.subscriptions must not be empty"

    def test_shard1b_not_empty(self):
        """shard1b must contain data."""
        assert get_row_count('shard1b', 'messages') > 0, "shard1b.messages must not be empty"
        assert get_row_count('shard1b', 'subscriptions') > 0, "shard1b.subscriptions must not be empty"


class TestDataIntegrity:
    """Verify no data loss or duplication during resharding."""

    @pytest.fixture(autouse=True)
    def load_original_counts(self):
        with open('/app/original_counts.json') as f:
            self.original = json.load(f)

    def test_total_message_count(self):
        orig_total = self.original['shard0.messages'] + self.original['shard1.messages']
        new_total = sum(get_row_count(db, 'messages') for db in ['shard0', 'shard1a', 'shard1b'])
        assert new_total == orig_total, \
            f"Total messages: {new_total}, expected {orig_total} (data loss or duplication)"

    def test_total_subscription_count(self):
        orig_total = self.original['shard0.subscriptions'] + self.original['shard1.subscriptions']
        new_total = sum(get_row_count(db, 'subscriptions') for db in ['shard0', 'shard1a', 'shard1b'])
        assert new_total == orig_total, \
            f"Total subscriptions: {new_total}, expected {orig_total} (data loss or duplication)"

    def test_shard0_message_count_unchanged(self):
        current = get_row_count('shard0', 'messages')
        assert current == self.original['shard0.messages'], \
            f"shard0.messages changed: {current} vs original {self.original['shard0.messages']}"

    def test_shard0_subscription_count_unchanged(self):
        current = get_row_count('shard0', 'subscriptions')
        assert current == self.original['shard0.subscriptions'], \
            f"shard0.subscriptions changed: {current} vs original {self.original['shard0.subscriptions']}"

    def test_no_cross_shard_channel_duplication(self):
        """No channel should have messages in multiple shards."""
        shard_channels = {}
        for db in ['shard0', 'shard1a', 'shard1b']:
            conn = get_mysql_connection(db)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT channel_id FROM messages")
            shard_channels[db] = {row[0] for row in cursor.fetchall()}
            cursor.close()
            conn.close()

        dbs = list(shard_channels.keys())
        for i in range(len(dbs)):
            for j in range(i + 1, len(dbs)):
                overlap = shard_channels[dbs[i]] & shard_channels[dbs[j]]
                assert len(overlap) == 0, \
                    f"Channels {overlap} appear in both {dbs[i]} and {dbs[j]}"


class TestRoutingConfig:
    """Verify the routing configuration defines a valid partition."""

    def test_config_has_three_shards(self):
        with open('/app/config.yaml') as f:
            config = yaml.safe_load(f)
        assert len(config['shards']) == 3, \
            f"Expected 3 shards, got {len(config['shards'])}"

    def test_config_valid_partition(self):
        """Shard ranges must form a complete, non-overlapping partition."""
        with open('/app/config.yaml') as f:
            config = yaml.safe_load(f)

        ranges = []
        for s in config['shards']:
            ranges.append((s['range_start'], s['range_end']))

        # Sort by start bound
        ranges.sort(key=lambda r: bytes.fromhex(r[0].ljust(16, '0')) if r[0] else b'\x00' * 8)

        assert ranges[0][0] == "", f"First shard must start at '' (got '{ranges[0][0]}')"
        assert ranges[-1][1] == "", f"Last shard must end at '' (got '{ranges[-1][1]}')"

        for i in range(len(ranges) - 1):
            assert ranges[i][1] == ranges[i + 1][0], \
                f"Gap/overlap between shard ending at '{ranges[i][1]}' and starting at '{ranges[i + 1][0]}'"

    def test_config_databases_exist(self):
        """All databases referenced in config must exist."""
        with open('/app/config.yaml') as f:
            config = yaml.safe_load(f)
        for shard in config['shards']:
            db = shard['database']
            assert database_exists(db), f"Database '{db}' in config does not exist"

    def test_routing_correctness(self):
        """Spot-check that routing matches actual data location."""
        sys.path.insert(0, '/app')
        from vhash import compute_keyspace_id, keyspace_id_in_range

        with open('/app/config.yaml') as f:
            config = yaml.safe_load(f)

        import random
        random.seed(99)
        test_channels = random.sample(range(1, 2001), 100)

        for ch_id in test_channels:
            kid = compute_keyspace_id(ch_id)
            target_db = None
            for shard in config['shards']:
                if keyspace_id_in_range(kid, shard['range_start'], shard['range_end']):
                    target_db = shard['database']
                    break

            assert target_db is not None, f"No shard found for channel_id={ch_id}"

            conn = get_mysql_connection(target_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM messages WHERE channel_id = %s", (ch_id,))
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()

            assert count == 10, \
                f"channel_id={ch_id} routed to {target_db} but has {count} messages (expected 10)"


class TestCircuitBreaker:
    """Verify circuit breaker implementation."""

    def test_circuit_breaker_module_exists(self):
        assert os.path.exists('/app/circuit_breaker.py'), \
            "Circuit breaker module must exist at /app/circuit_breaker.py"

    def test_circuit_breaker_has_required_interface(self):
        sys.path.insert(0, '/app')
        if 'circuit_breaker' in sys.modules:
            del sys.modules['circuit_breaker']

        cb_module = importlib.import_module('circuit_breaker')
        assert hasattr(cb_module, 'CircuitBreaker'), "Must define CircuitBreaker class"

        cb = cb_module.CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
        assert hasattr(cb, 'state'), "CircuitBreaker must have 'state' attribute"
        normalized = cb.state.replace('-', '_')
        assert normalized == 'closed', f"Initial state must be 'closed', got '{cb.state}'"

    def test_circuit_breaker_allows_when_closed(self):
        sys.path.insert(0, '/app')
        if 'circuit_breaker' in sys.modules:
            del sys.modules['circuit_breaker']

        cb_module = importlib.import_module('circuit_breaker')
        cb = cb_module.CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.allow_request(), "Should allow requests when closed"

    def test_circuit_breaker_opens_on_failures(self):
        sys.path.insert(0, '/app')
        if 'circuit_breaker' in sys.modules:
            del sys.modules['circuit_breaker']

        cb_module = importlib.import_module('circuit_breaker')
        cb = cb_module.CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)

        for _ in range(3):
            cb.record_failure()

        normalized = cb.state.replace('-', '_')
        assert normalized == 'open', \
            f"Should be 'open' after 3 failures, got '{cb.state}'"

    def test_circuit_breaker_blocks_when_open(self):
        sys.path.insert(0, '/app')
        if 'circuit_breaker' in sys.modules:
            del sys.modules['circuit_breaker']

        cb_module = importlib.import_module('circuit_breaker')
        cb = cb_module.CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)

        cb.record_failure()
        cb.record_failure()

        assert not cb.allow_request(), "Should block requests when open"

    def test_circuit_breaker_half_open_after_timeout(self):
        sys.path.insert(0, '/app')
        if 'circuit_breaker' in sys.modules:
            del sys.modules['circuit_breaker']

        cb_module = importlib.import_module('circuit_breaker')
        cb = cb_module.CircuitBreaker(failure_threshold=2, recovery_timeout=0.5)

        cb.record_failure()
        cb.record_failure()
        normalized = cb.state.replace('-', '_')
        assert normalized == 'open', f"Expected 'open', got '{cb.state}'"

        time.sleep(0.7)

        allowed = cb.allow_request()
        assert allowed, "After recovery timeout, should allow a probe request"
        normalized = cb.state.replace('-', '_')
        assert normalized == 'half_open', \
            f"After recovery timeout + probe, state should be 'half_open', got '{cb.state}'"

    def test_circuit_breaker_closes_on_success_after_half_open(self):
        sys.path.insert(0, '/app')
        if 'circuit_breaker' in sys.modules:
            del sys.modules['circuit_breaker']

        cb_module = importlib.import_module('circuit_breaker')
        cb = cb_module.CircuitBreaker(failure_threshold=2, recovery_timeout=0.3)

        cb.record_failure()
        cb.record_failure()

        time.sleep(0.5)

        cb.allow_request()  # triggers half_open
        cb.record_success()  # should close the circuit

        normalized = cb.state.replace('-', '_')
        assert normalized == 'closed', \
            f"Should close after success in half_open, got '{cb.state}'"


class TestVDiffReport:
    """Verify VDiff consistency report."""

    def test_vdiff_report_exists(self):
        assert os.path.exists('/app/vdiff_report.json'), \
            "VDiff report must exist at /app/vdiff_report.json"

    def test_vdiff_report_valid_json(self):
        with open('/app/vdiff_report.json') as f:
            report = json.load(f)
        assert isinstance(report, dict)

    def test_vdiff_report_shows_consistency(self):
        with open('/app/vdiff_report.json') as f:
            report = json.load(f)

        for table in ['messages', 'subscriptions']:
            assert table in report, f"VDiff report must include '{table}' table"
            entry = report[table]
            assert entry.get('consistent') is True, \
                f"VDiff for {table} must show consistent=True"
            assert 'source_row_count' in entry, \
                f"VDiff for {table} must include source_row_count"
            assert 'target_row_count' in entry, \
                f"VDiff for {table} must include target_row_count"
            assert entry['source_row_count'] == entry['target_row_count'], \
                f"VDiff {table}: source ({entry['source_row_count']}) != target ({entry['target_row_count']})"

    def test_vdiff_counts_match_actual(self):
        """VDiff reported counts must match actual database state."""
        with open('/app/vdiff_report.json') as f:
            report = json.load(f)
        with open('/app/original_counts.json') as f:
            original = json.load(f)

        for table in ['messages', 'subscriptions']:
            assert report[table]['source_row_count'] == original[f'shard1.{table}'], \
                f"VDiff source_row_count for {table} doesn't match original shard1 count"
            actual_target = get_row_count('shard1a', table) + get_row_count('shard1b', table)
            assert report[table]['target_row_count'] == actual_target, \
                f"VDiff target_row_count for {table} ({report[table]['target_row_count']}) doesn't match actual ({actual_target})"
