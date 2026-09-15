"""Tests for ClickHouse log compression optimization task.

Verifies that optimized tables achieve target compression ratio with proper
types, ordering, and Body reconstruction.
"""

import subprocess
import time
import pytest


def ch_query(query, retries=3):
    """Execute a ClickHouse query and return stdout."""
    for attempt in range(retries):
        result = subprocess.run(
            ['clickhouse-client', '--query', query],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return result.stdout.strip()
        if attempt < retries - 1:
            time.sleep(2)
    raise RuntimeError(
        f"ClickHouse query failed after {retries} attempts: {result.stderr}"
    )


@pytest.fixture(scope="session", autouse=True)
def ensure_clickhouse():
    """Ensure ClickHouse is running before tests."""
    try:
        ch_query("SELECT 1")
    except Exception:
        subprocess.run(
            ['clickhouse-server', '--daemon'],
            timeout=10, capture_output=True
        )
        time.sleep(5)
        for _ in range(30):
            try:
                ch_query("SELECT 1")
                return
            except Exception:
                time.sleep(1)
        pytest.fail("Could not start ClickHouse server")


def get_optimized_tables():
    """Return list of optimized table names."""
    raw = ch_query(
        "SELECT name FROM system.tables "
        "WHERE database='default' AND name LIKE 'optimized_%'"
    )
    return [t.strip() for t in raw.split('\n') if t.strip()]


def test_optimized_tables_exist():
    """At least one optimized table must exist."""
    tables = get_optimized_tables()
    assert len(tables) >= 1, (
        "No tables with prefix 'optimized_' found in the default database"
    )


def test_row_count_preserved():
    """Optimized tables must collectively contain >= 99% of raw_logs rows."""
    raw_count = int(ch_query("SELECT count() FROM raw_logs"))
    tables = get_optimized_tables()
    assert tables, "No optimized tables found"

    total = 0
    for t in tables:
        total += int(ch_query(f"SELECT count() FROM {t}"))

    threshold = int(raw_count * 0.99)
    assert total >= threshold, (
        f"Optimized tables have {total} rows total, "
        f"need >= {threshold} (99% of {raw_count})"
    )


def test_compression_ratio():
    """Compression ratio (raw_uncompressed / opt_compressed) must be >= 40."""
    raw_uncompressed = int(ch_query(
        "SELECT sum(data_uncompressed_bytes) FROM system.parts "
        "WHERE database='default' AND table='raw_logs' AND active"
    ))
    assert raw_uncompressed > 0, "raw_logs has no data"

    opt_compressed = int(ch_query(
        "SELECT sum(data_compressed_bytes) FROM system.parts "
        "WHERE database='default' AND table LIKE 'optimized_%' AND active"
    ))
    assert opt_compressed > 0, "Optimized tables have no compressed data"

    ratio = raw_uncompressed / opt_compressed
    assert ratio >= 40, (
        f"Compression ratio {ratio:.1f}x is below 40x target. "
        f"raw_uncompressed={raw_uncompressed}, opt_compressed={opt_compressed}"
    )


def test_specialized_types():
    """Optimized tables must use at least 3 specialized (non-String) types."""
    types_raw = ch_query(
        "SELECT DISTINCT type FROM system.columns "
        "WHERE database='default' AND table LIKE 'optimized_%'"
    )
    all_types = [t.strip() for t in types_raw.split('\n') if t.strip()]

    specialized_keywords = [
        'Int', 'UInt', 'Float', 'DateTime', 'Date',
        'IPv4', 'IPv6', 'LowCardinality', 'Decimal', 'Enum', 'UUID'
    ]
    specialized = [
        t for t in all_types
        if any(kw in t for kw in specialized_keywords)
    ]
    assert len(specialized) >= 3, (
        f"Need >= 3 specialized column types, found: {specialized}. "
        f"All types: {all_types}"
    )


def test_lowcardinality_used():
    """At least one column must use LowCardinality."""
    count = int(ch_query(
        "SELECT count() FROM system.columns "
        "WHERE database='default' AND table LIKE 'optimized_%' "
        "AND type LIKE '%LowCardinality%'"
    ))
    assert count >= 1, "No LowCardinality columns found in optimized tables"


def test_ordering_key():
    """At least one optimized table must have a non-trivial ORDER BY key."""
    tables = get_optimized_tables()
    assert tables, "No optimized tables found"

    has_nontrivial = False
    keys_found = []
    for t in tables:
        key = ch_query(
            f"SELECT sorting_key FROM system.tables "
            f"WHERE database='default' AND name='{t}'"
        )
        keys_found.append(f"{t}: {key}")
        if key and key != 'tuple()' and key != '':
            has_nontrivial = True

    assert has_nontrivial, (
        f"All optimized tables have trivial ORDER BY: {keys_found}"
    )


def test_body_reconstruction():
    """At least one optimized table must have a Body column returning data."""
    tables = get_optimized_tables()
    assert tables, "No optimized tables found"

    body_works = False
    for t in tables:
        has_body = int(ch_query(
            f"SELECT count() FROM system.columns "
            f"WHERE database='default' AND table='{t}' AND name='Body'"
        ))
        if has_body > 0:
            body_sample = ch_query(f"SELECT Body FROM {t} LIMIT 5")
            if body_sample and len(body_sample) > 20:
                body_works = True
                break

    assert body_works, (
        "No optimized table has a working Body column that returns "
        "reconstructed log content"
    )
