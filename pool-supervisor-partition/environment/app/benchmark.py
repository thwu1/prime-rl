#!/usr/bin/env python3
"""
Benchmark tool for the connection pool supervisor.

Demonstrates performance under normal and burst traffic patterns,
and tests whether critical registry traffic survives a burst.

Usage:
    python3 benchmark.py

"""

import asyncio
import sys
import time

from supervisor import ConnectionPoolSupervisor


async def run_normal_test(pool):
    """20 sequential requests under normal load."""
    successes = 0
    for i in range(20):
        result = await pool.request_connection(f"sfu-{i}.example.com")
        if result is not None:
            successes += 1
            await pool.release_connection(result)
    return successes, 20


async def run_burst_test(pool, n=500):
    """Concurrent burst of *n* connection requests."""
    destinations = [
        f"sfu-{i % 50}.region-{i % 3}.example.com" for i in range(n)
    ]

    async def make_request(dest):
        result = await pool.request_connection(dest)
        return result is not None

    results = await asyncio.gather(*[make_request(d) for d in destinations])
    return sum(results), n


async def run_registry_test(pool, burst_size=400):
    """Test critical registry requests during ongoing burst traffic."""
    burst_dests = [f"sfu-{i}.example.com" for i in range(burst_size)]

    async def _burst():
        return await asyncio.gather(
            *[pool.request_connection(d) for d in burst_dests]
        )

    burst_task = asyncio.create_task(_burst())
    await asyncio.sleep(0.005)  # let burst start filling the queue

    reg_successes = 0
    for _ in range(10):
        result = await pool.request_connection(
            "registry.internal", timeout=2.0, priority="critical"
        )
        if result is not None:
            reg_successes += 1

    await burst_task
    return reg_successes, 10


async def main():
    print("=" * 60)
    print("Connection Pool Supervisor Benchmark")
    print("=" * 60)

    # ---- Normal load ----
    pool = ConnectionPoolSupervisor(name="bench", max_connections=500)
    await pool.start()
    ok, total = await run_normal_test(pool)
    print(f"\n[Normal Load]  {ok}/{total} succeeded")
    await pool.stop()

    # ---- Burst load ----
    pool = ConnectionPoolSupervisor(name="bench", max_connections=500)
    await pool.start()
    t0 = time.monotonic()
    ok, total = await run_burst_test(pool, 500)
    elapsed = time.monotonic() - t0
    stats = pool.get_stats()
    pct = ok / total * 100
    print(f"\n[Burst Load]   {ok}/{total} succeeded ({pct:.1f}%) in {elapsed:.2f}s")
    print(
        f"               deferred_peak={stats['deferred_peak']}, "
        f"mailbox_peak={stats['mailbox_peak']}"
    )
    await pool.stop()

    # ---- Registry during burst ----
    pool = ConnectionPoolSupervisor(name="bench", max_connections=500)
    await pool.start()
    reg_ok, reg_total = await run_registry_test(pool)
    print(f"\n[Registry]     {reg_ok}/{reg_total} succeeded during burst")
    await pool.stop()

    # ---- Summary ----
    print(f"\n{'=' * 60}")
    print("Pass criteria:")
    print(
        f"  Burst success rate > 85%:  "
        f"{'PASS' if pct > 85 else 'FAIL'}  ({pct:.1f}%)"
    )
    print(
        f"  Registry success > 80%:    "
        f"{'PASS' if reg_ok / reg_total > 0.8 else 'FAIL'}  "
        f"({reg_ok}/{reg_total})"
    )
    print(
        f"  Deferred peak < 200:       "
        f"{'PASS' if stats['deferred_peak'] < 200 else 'FAIL'}  "
        f"({stats['deferred_peak']})"
    )
    print("=" * 60)

    ok_all = (
        pct > 85
        and reg_ok / reg_total > 0.8
        and stats["deferred_peak"] < 200
    )
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
