"""
Tests for connection pool supervisor fix.

Verifies that the ConnectionPoolSupervisor handles burst traffic with
high success rates, isolates critical registry traffic, keeps internal
queue depths bounded, maintains normal-load correctness, properly
configures partitioning via config.toml, records telemetry events to
SQLite, and produces diagnostic reports via diagnose.sh.

"""

import asyncio
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, "/app")

from supervisor import ConnectionPoolSupervisor  # noqa: E402


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

async def _make_pool(**kwargs):
    """Create, start, and return a ConnectionPoolSupervisor."""
    defaults = dict(name="test", max_connections=500, connection_timeout=5.0)
    defaults.update(kwargs)
    pool = ConnectionPoolSupervisor(**defaults)
    await pool.start()
    return pool


# -----------------------------------------------------------------------
# Behavioral tests
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_load():
    """Under normal sequential load every request must succeed."""
    pool = await _make_pool(max_connections=100)
    try:
        results = []
        for i in range(20):
            r = await pool.request_connection(f"dest-{i}.example.com")
            results.append(r is not None)
        success = sum(results)
        assert success == 20, f"Normal load: only {success}/20 succeeded"
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_burst_success_rate():
    """Under a burst of 500 concurrent requests, >85% must succeed."""
    pool = await _make_pool()
    try:
        dests = [
            f"sfu-{i % 50}.region-{i % 3}.example.com" for i in range(500)
        ]

        async def req(d):
            return (await pool.request_connection(d)) is not None

        results = await asyncio.gather(*[req(d) for d in dests])
        rate = sum(results) / len(results)
        assert rate > 0.85, (
            f"Burst success rate {rate:.2%} is below the 85% threshold. "
            f"Stats: {pool.get_stats()}"
        )
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_registry_during_burst():
    """Critical-priority registry requests must survive burst traffic."""
    pool = await _make_pool()
    try:
        # Fire a burst in the background
        burst_dests = [f"sfu-{i}.example.com" for i in range(500)]

        async def _burst():
            return await asyncio.gather(
                *[pool.request_connection(d) for d in burst_dests]
            )

        burst_task = asyncio.create_task(_burst())
        await asyncio.sleep(0.005)  # let burst start filling the queue

        # Send critical registry requests (sequential, 2s timeout each)
        reg_results = []
        for _ in range(10):
            r = await pool.request_connection(
                "registry.internal", timeout=2.0, priority="critical"
            )
            reg_results.append(r is not None)

        await burst_task

        rate = sum(reg_results) / len(reg_results)
        assert rate > 0.8, (
            f"Registry success rate {rate:.2%} is below 80% -- "
            f"critical traffic is being starved by burst traffic."
        )
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_queue_bounded():
    """No single supervisor queue should exceed 200 deferred messages."""
    pool = await _make_pool()
    try:
        dests = [f"sfu-{i % 50}.example.com" for i in range(500)]
        await asyncio.gather(
            *[pool.request_connection(d) for d in dests]
        )

        stats = pool.get_stats()
        assert "deferred_peak" in stats, (
            "get_stats() must return a dict with 'deferred_peak' key"
        )
        assert stats["deferred_peak"] < 200, (
            f"Deferred peak {stats['deferred_peak']} >= 200 -- "
            f"single-supervisor bottleneck still present."
        )
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_moderate_concurrent():
    """50 concurrent requests should achieve >95% success rate."""
    pool = await _make_pool(max_connections=200)
    try:
        dests = [f"sfu-{i}.example.com" for i in range(50)]
        results = await asyncio.gather(
            *[pool.request_connection(d) for d in dests]
        )
        successes = sum(1 for r in results if r is not None)
        rate = successes / 50
        assert rate > 0.95, (
            f"Moderate concurrent: {successes}/50 ({rate:.2%})"
        )
    finally:
        await pool.stop()


# -----------------------------------------------------------------------
# Configuration test
# -----------------------------------------------------------------------

def test_config_valid():
    """config.toml must have partitioning enabled with proper settings."""
    import tomllib
    with open("/app/config.toml", "rb") as f:
        config = tomllib.load(f)

    part = config.get("partitioning", {})
    assert part.get("enabled") is True, (
        "partitioning.enabled must be true"
    )
    assert part.get("num_partitions", 0) >= 4, (
        f"partitioning.num_partitions must be >= 4, "
        f"got {part.get('num_partitions')}"
    )

    prio = config.get("priority", {})
    assert prio.get("dedicated_partition") is True, (
        "priority.dedicated_partition must be true"
    )


# -----------------------------------------------------------------------
# Telemetry test
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telemetry_records():
    """After requests, SQLite telemetry DB must have event records."""
    import sqlite3

    db_path = "/app/telemetry.db"
    # Start clean
    if os.path.exists(db_path):
        os.remove(db_path)

    pool = await _make_pool()
    try:
        await asyncio.gather(
            *[pool.request_connection(f"dest-{i}.example.com")
              for i in range(20)]
        )
    finally:
        await pool.stop()

    assert os.path.exists(db_path), (
        "Telemetry database should be created at /app/telemetry.db"
    )
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM connection_events"
        ).fetchone()[0]
        assert count > 0, f"Expected telemetry events, got {count}"

        types = conn.execute(
            "SELECT DISTINCT event_type FROM connection_events"
        ).fetchall()
        type_names = {r[0] for r in types}
        assert "request" in type_names, (
            f"Expected 'request' events in telemetry, got {type_names}"
        )
        assert "connect" in type_names, (
            f"Expected 'connect' events in telemetry, got {type_names}"
        )
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Diagnostic script tests
# -----------------------------------------------------------------------

def test_diagnose_uses_tools():
    """diagnose.sh must use sqlite3 CLI and jq for processing."""
    with open("/app/diagnose.sh") as f:
        content = f.read()
    assert "sqlite3" in content, (
        "diagnose.sh must use the sqlite3 CLI tool"
    )
    assert "jq" in content, (
        "diagnose.sh must use jq for JSON formatting"
    )


@pytest.mark.asyncio
async def test_diagnose_output():
    """diagnose.sh must produce valid JSON with required fields."""
    db_path = "/app/telemetry.db"
    # Start clean
    if os.path.exists(db_path):
        os.remove(db_path)

    pool = await _make_pool()
    try:
        await asyncio.gather(
            *[pool.request_connection(f"dest-{i}.example.com")
              for i in range(20)]
        )
    finally:
        await pool.stop()

    result = subprocess.run(
        ["bash", "/app/diagnose.sh"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"diagnose.sh failed with exit code {result.returncode}: "
        f"{result.stderr}"
    )

    report = json.loads(result.stdout)

    assert "total_events" in report, (
        "Report must contain 'total_events'"
    )
    assert isinstance(report["total_events"], int), (
        f"total_events must be integer, got {type(report['total_events'])}"
    )
    assert report["total_events"] > 0, (
        "total_events must be > 0"
    )

    assert "events_by_type" in report, (
        "Report must contain 'events_by_type'"
    )
    assert isinstance(report["events_by_type"], list), (
        f"events_by_type must be array, got {type(report['events_by_type'])}"
    )

    for entry in report["events_by_type"]:
        assert "event_type" in entry, (
            f"Each events_by_type entry must have 'event_type': {entry}"
        )
        assert "count" in entry, (
            f"Each events_by_type entry must have 'count': {entry}"
        )

    type_names = {e["event_type"] for e in report["events_by_type"]}
    assert "request" in type_names, (
        f"events_by_type must include 'request' events, got {type_names}"
    )
