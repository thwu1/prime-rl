#!/usr/bin/env python3
"""Interactive test harness for the deterministic simulation framework.

This harness provides quick smoke-tests for individual subsystems.
For comprehensive fault injection campaigns, use campaign.py instead.

Usage::

    python3 harness.py --test all          # run every check
    python3 harness.py --test determinism  # determinism only
    python3 harness.py --test partition    # partition symmetry only
    python3 harness.py --test replication  # committed-write durability only
    python3 harness.py --test buggify     # buggify determinism only

See also:
    campaign.py   — parameterised fault injection campaigns
    checker/      — safety property checker for trace databases
    detsim/tracer.py — SQLite trace logger
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detsim.rng import DetRng
from detsim.engine import SimEngine
from detsim.network import Network
from detsim.buggify import Buggify
from replication.protocol import Replica


# ── helpers ─────────────────────────────────────────────────────────────────

def make_cluster(seed, n=3, latency=(0.005, 0.050)):
    """Create a fresh simulation cluster with *n* replica nodes."""
    rng = DetRng(seed)
    eng = SimEngine(rng)
    net = Network(eng, rng, latency=latency)
    nodes = [Replica(i, list(range(n)), net, eng) for i in range(n)]
    return rng, eng, net, nodes


# ── checks ──────────────────────────────────────────────────────────────────

def check_determinism(seed):
    """Run the same seed twice and compare traces."""
    traces = []
    for _ in range(2):
        _rng, eng, _net, nodes = make_cluster(seed)
        nodes[0].become_primary()
        for i in range(5):
            nodes[0].write(f"k{i}", f"v{i}")
        eng.run(until=2.0)
        traces.append(eng.trace)
    return traces[0] == traces[1], traces


def check_buggify_determinism(seed):
    """Check that buggify decisions are deterministic for a given seed."""
    results = []
    for _ in range(2):
        rng = DetRng(seed)
        bug = Buggify(rng)
        bug.enable()
        decisions = [bug.should_fault() for _ in range(50)]
        results.append(decisions)
    return results[0] == results[1], results


def check_partition_symmetry():
    """Verify partition(a,b) blocks both directions."""
    rng = DetRng(0)
    eng = SimEngine(rng)
    net = Network(eng, rng)
    net.partition(1, 2)
    fwd = net.is_partitioned(1, 2)
    rev = net.is_partitioned(2, 1)
    return fwd and rev, fwd, rev


def run_replication_scenario(seed):
    """Run a partition / heal / sync scenario and check committed data."""
    _rng, eng, net, nodes = make_cluster(seed, n=3)

    nodes[0].become_primary()
    nodes[0].write("a", "1")
    eng.run(until=0.2)
    nodes[0].write("b", "2")
    eng.run(until=0.5)

    committed = {}
    for k in ("a", "b"):
        v = nodes[0].read(k)
        if v is not None:
            committed[k] = v

    net.partition(0, 1)
    net.partition(0, 2)
    nodes[0].write("c", "3")
    eng.run(until=0.7)

    nodes[1].become_primary()
    nodes[1].write("d", "4")
    eng.run(until=1.2)

    net.heal(0, 1)
    net.heal(0, 2)
    nodes[1].initiate_sync()
    eng.run(until=2.5)

    ok = True
    missing = []
    for n in nodes:
        for key, val in committed.items():
            actual = n.read(key)
            if actual != val:
                ok = False
                missing.append((n.nid, key, val, actual))
    return ok, nodes, committed, missing


# ── main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--test",
        choices=["determinism", "buggify", "partition", "replication", "all"],
        default="all",
    )
    parser.add_argument("--seeds", type=str, default="0-19",
                        help="Seed range (e.g. 0-49)")
    args = parser.parse_args()

    any_fail = False

    if args.test in ("determinism", "all"):
        print("=== Determinism Check ===")
        for s in range(20):
            ok, traces = check_determinism(s)
            status = "PASS" if ok else "FAIL"
            print(f"  Seed {s:>3}: {status}", end="")
            if not ok:
                any_fail = True
                print(f"  (trace lengths: {len(traces[0])} vs {len(traces[1])})")
            else:
                print()

    if args.test in ("buggify", "all"):
        print("\n=== Buggify Determinism Check ===")
        for s in range(10):
            ok, _ = check_buggify_determinism(s)
            status = "PASS" if ok else "FAIL"
            print(f"  Seed {s:>3}: {status}")
            if not ok:
                any_fail = True

    if args.test in ("partition", "all"):
        print("\n=== Partition Symmetry Check ===")
        ok, fwd, rev = check_partition_symmetry()
        print(f"  partition(1,2): 1->2={fwd}, 2->1={rev}  -> {'PASS' if ok else 'FAIL'}")
        if not ok:
            any_fail = True

    if args.test in ("replication", "all"):
        print("\n=== Replication Correctness Check ===")
        start, end = (int(x) for x in args.seeds.split("-"))
        failures = 0
        for s in range(start, end + 1):
            ok, _nodes, _committed, missing = run_replication_scenario(s)
            if not ok:
                failures += 1
                for nid, key, exp, got in missing:
                    print(f"  Seed {s:>3}: FAIL  node {nid} missing key='{key}' "
                          f"(expected='{exp}', got='{got}')")
        total = end - start + 1
        if failures == 0:
            print(f"  All {total} seeds: PASS")
        else:
            any_fail = True
            print(f"  {failures}/{total} seeds FAILED")

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
