
import sys
sys.path.insert(0, '/app')

import sqlite3
import struct
import os
import shutil
import tempfile
import pytest
import xxhash

from config import SOURCE_SHARDS, TARGET_SHARDS, TABLES, SHARDING_KEY, TABLE_PKS
from schema import SCHEMA_SQL


# ========================
# VIndex Tests
# ========================

def test_vindex_correctness():
    """compute_keyspace_id must produce correct xxhash64-based keyspace IDs."""
    from vindex import compute_keyspace_id

    test_values = [1, 42, 100, 999, 12345, 67890, 2**16, 2**32 - 1]
    for val in test_values:
        result = compute_keyspace_id(val)
        assert isinstance(result, bytes) and len(result) == 8, (
            f"Keyspace ID must be 8 bytes, got {type(result).__name__} len={len(result)}"
        )

        # Reference: Vitess packs input as big-endian uint64, runs xxhash64,
        # packs output as big-endian uint64
        expected_hash = xxhash.xxh64(struct.pack('>Q', val)).intdigest()
        expected = struct.pack('>Q', expected_hash)
        assert result == expected, (
            f"Value {val}: got {result.hex()}, expected {expected.hex()}"
        )


def test_vindex_distribution():
    """Hash vindex must distribute keys roughly evenly across 4 shard ranges."""
    from vindex import get_shard_for_value

    shard_ranges = [("", "40"), ("40", "80"), ("80", "c0"), ("c0", "")]
    counts = {}
    n = 10000

    for i in range(n):
        shard = get_shard_for_value(i, shard_ranges)
        counts[shard] = counts.get(shard, 0) + 1

    assert len(counts) == 4, f"Expected 4 shards in distribution, got {len(counts)}: {counts}"
    for shard, count in counts.items():
        ratio = count / n
        assert 0.20 <= ratio <= 0.30, (
            f"Shard {shard}: {ratio:.2%} of keys (expected ~25%)"
        )


def test_shard_routing_boundaries():
    """get_shard_for_ksid must correctly map boundary keyspace IDs."""
    from vindex import get_shard_for_ksid

    shard_ranges = [("", "40"), ("40", "80"), ("80", "c0"), ("c0", "")]

    test_cases = [
        (0x0000000000000000, "-40"),
        (0x3FFFFFFFFFFFFFFF, "-40"),
        (0x4000000000000000, "40-80"),
        (0x7FFFFFFFFFFFFFFF, "40-80"),
        (0x8000000000000000, "80-c0"),
        (0xBFFFFFFFFFFFFFFF, "80-c0"),
        (0xC000000000000000, "c0-"),
        (0xFFFFFFFFFFFFFFFF, "c0-"),
    ]

    for ksid_int, expected_shard in test_cases:
        ksid = struct.pack('>Q', ksid_int)
        result = get_shard_for_ksid(ksid, shard_ranges)
        assert result == expected_shard, (
            f"ksid {ksid_int:#018x}: got '{result}', expected '{expected_shard}'"
        )


# ========================
# Reshard Tests
# ========================

@pytest.fixture(scope="module")
def resharded_dbs(tmp_path_factory):
    """Run reshard on a copy of the databases and return paths."""
    tmp_dir = str(tmp_path_factory.mktemp("reshard"))

    # Copy source databases
    src_copies = {}
    for shard_name, orig_path in SOURCE_SHARDS.items():
        new_path = os.path.join(tmp_dir, os.path.basename(orig_path))
        shutil.copy2(orig_path, new_path)
        src_copies[shard_name] = new_path

    # Create empty target databases with schema
    tgt_copies = {}
    for shard_name, orig_path in TARGET_SHARDS.items():
        new_path = os.path.join(tmp_dir, os.path.basename(orig_path))
        conn = sqlite3.connect(new_path)
        conn.executescript(SCHEMA_SQL)
        conn.close()
        tgt_copies[shard_name] = new_path

    # Run reshard
    from reshard import execute_reshard
    result = execute_reshard(source_shards=src_copies, target_shards=tgt_copies)

    return {
        'source': src_copies,
        'target': tgt_copies,
        'result': result,
    }


def test_reshard_completes(resharded_dbs):
    """Reshard must complete with success=True."""
    assert resharded_dbs['result']['success'] is True


def test_reshard_no_data_loss(resharded_dbs):
    """Total row count per table must match between source and target."""
    for table in TABLES:
        source_count = 0
        for db_path in resharded_dbs['source'].values():
            conn = sqlite3.connect(db_path)
            source_count += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.close()

        target_count = 0
        for db_path in resharded_dbs['target'].values():
            conn = sqlite3.connect(db_path)
            target_count += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.close()

        assert source_count == target_count, (
            f"Table {table}: source has {source_count} rows, target has {target_count}"
        )


def test_reshard_correct_placement(resharded_dbs):
    """Every row in each target shard must have a keyspace ID within that shard's range."""
    from vindex import compute_keyspace_id

    target_ranges = {
        '-40': (0, 0x4000000000000000),
        '40-80': (0x4000000000000000, 0x8000000000000000),
        '80-c0': (0x8000000000000000, 0xC000000000000000),
        'c0-': (0xC000000000000000, 1 << 64),
    }

    for shard_name, db_path in resharded_dbs['target'].items():
        start, end = target_ranges[shard_name]
        conn = sqlite3.connect(db_path)

        for table in TABLES:
            rows = conn.execute(f"SELECT {SHARDING_KEY} FROM {table}").fetchall()
            for (ws_id,) in rows:
                ksid = compute_keyspace_id(ws_id)
                ksid_int = struct.unpack('>Q', ksid)[0]
                assert start <= ksid_int < end, (
                    f"Row with {SHARDING_KEY}={ws_id} (ksid={ksid_int:#018x}) "
                    f"in shard {shard_name} [{start:#018x}, {end:#018x})"
                )
        conn.close()


def test_reshard_no_duplicates(resharded_dbs):
    """No primary key should appear in more than one target shard."""
    for table in TABLES:
        pk = TABLE_PKS[table]
        all_ids = []
        for db_path in resharded_dbs['target'].values():
            conn = sqlite3.connect(db_path)
            rows = conn.execute(f"SELECT {pk} FROM {table}").fetchall()
            all_ids.extend([r[0] for r in rows])
            conn.close()

        duplicates = len(all_ids) - len(set(all_ids))
        assert duplicates == 0, (
            f"Table {table}: {duplicates} duplicate {pk} values across target shards"
        )


# ========================
# VDiff Tests
# ========================

def test_vdiff_consistent(resharded_dbs):
    """VDiff must report consistent=True after a correct reshard."""
    from vdiff import run_vdiff

    result = run_vdiff(
        source_shards=resharded_dbs['source'],
        target_shards=resharded_dbs['target']
    )

    assert result.consistent is True, f"VDiff errors: {result.errors}"
    assert len(result.errors) == 0


def test_vdiff_detects_missing_row(resharded_dbs):
    """VDiff must detect when a row is missing from target."""
    tmp_dir = tempfile.mkdtemp()

    # Create a copy of target shards with one row deleted
    modified_targets = {}
    for shard_name, db_path in resharded_dbs['target'].items():
        new_path = os.path.join(tmp_dir, os.path.basename(db_path))
        shutil.copy2(db_path, new_path)
        modified_targets[shard_name] = new_path

    # Delete a user row from the first non-empty target shard
    deleted = False
    for shard_name, db_path in modified_targets.items():
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            conn.execute("DELETE FROM users WHERE user_id = (SELECT MIN(user_id) FROM users)")
            conn.commit()
            deleted = True
            conn.close()
            break
        conn.close()

    assert deleted, "Could not find a non-empty target shard to modify"

    from vdiff import run_vdiff
    result = run_vdiff(
        source_shards=resharded_dbs['source'],
        target_shards=modified_targets
    )

    assert result.consistent is False, "VDiff should detect missing row"
    assert len(result.errors) > 0, "VDiff should report at least one error"

    shutil.rmtree(tmp_dir)


# ========================
# Forget User Tests
# ========================

@pytest.fixture
def forget_user_dbs(tmp_path):
    """Create temporary copies of source databases for forget_user tests."""
    connections = {}
    for shard_name, db_path in SOURCE_SHARDS.items():
        tmp_db = str(tmp_path / os.path.basename(db_path))
        shutil.copy2(db_path, tmp_db)
        connections[shard_name] = sqlite3.connect(tmp_db)
    yield connections
    for conn in connections.values():
        conn.close()


def _find_user_with_multiple_channels(connections):
    """Find a user with thread subscriptions in at least 3 distinct channels."""
    for conn in connections.values():
        rows = conn.execute(
            "SELECT user_id, COUNT(DISTINCT channel_id) AS ch "
            "FROM thread_subscriptions WHERE status = 'active' "
            "GROUP BY user_id HAVING ch >= 3 "
            "ORDER BY ch DESC LIMIT 1"
        ).fetchall()
        if rows:
            return rows[0][0], rows[0][1]
    return None, 0


def test_forget_user_correctness(forget_user_dbs):
    """forget_user must deactivate all subscriptions for the user."""
    from jobs import forget_user, clear_notification_log
    clear_notification_log()

    user_id, ch_count = _find_user_with_multiple_channels(forget_user_dbs)
    assert user_id is not None, "Test data must have a user with subs in >= 3 channels"

    # Count active subs before
    active_before = 0
    for conn in forget_user_dbs.values():
        active_before += conn.execute(
            "SELECT COUNT(*) FROM thread_subscriptions "
            "WHERE user_id = ? AND status = 'active'",
            (user_id,)
        ).fetchone()[0]

    assert active_before > 0, "User must have active subscriptions"

    result = forget_user(user_id, forget_user_dbs)

    # All subs must now be inactive
    active_after = 0
    for conn in forget_user_dbs.values():
        active_after += conn.execute(
            "SELECT COUNT(*) FROM thread_subscriptions "
            "WHERE user_id = ? AND status = 'active'",
            (user_id,)
        ).fetchone()[0]

    assert active_after == 0, f"{active_after} subscriptions still active after forget_user"
    assert result['deactivated_subs'] == active_before, (
        f"Reported {result['deactivated_subs']} deactivated but expected {active_before}"
    )


def test_forget_user_efficiency(forget_user_dbs):
    """forget_user must use O(shards) queries, not O(shards * channels)."""
    from jobs import forget_user, clear_notification_log
    clear_notification_log()

    user_id, ch_count = _find_user_with_multiple_channels(forget_user_dbs)
    assert user_id is not None and ch_count >= 3, (
        f"Need user in >= 3 channels, found ch_count={ch_count}"
    )

    result = forget_user(user_id, forget_user_dbs)

    num_shards = len(forget_user_dbs)
    # Optimized: O(shards) queries. Allow a small constant factor.
    max_queries = num_shards * 4
    assert result['query_count'] <= max_queries, (
        f"Query count {result['query_count']} exceeds limit {max_queries} "
        f"for {num_shards} shards (user in {ch_count} channels). "
        f"The implementation likely has O(shards * channels) complexity."
    )


def test_forget_user_no_notifications(forget_user_dbs):
    """forget_user must not send notifications to deactivated users."""
    from jobs import forget_user, clear_notification_log
    clear_notification_log()

    user_id, _ = _find_user_with_multiple_channels(forget_user_dbs)
    assert user_id is not None

    result = forget_user(user_id, forget_user_dbs)

    assert result['notifications_sent'] == 0, (
        f"Sent {result['notifications_sent']} notifications to a deactivated user"
    )
