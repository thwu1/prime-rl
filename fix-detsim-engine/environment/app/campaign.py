#!/usr/bin/env python3
"""Fault injection campaign runner for deterministic simulation.

Runs parameterized fault injection scenarios across multiple seeds,
records traces to SQLite, and checks safety properties.

Usage::

    python3 campaign.py --config config.json [--db traces.db] [--report report.json]

Config schema (JSON)::

    {
        "name":    "campaign-name",
        "seeds":   {"start": 0, "end": 49},
        "nodes":   3,
        "buggify": true,
        "latency": [0.005, 0.050],
        "phases": [
            {"at": 0.0,  "action": "elect",     "node": 0},
            {"at": 0.01, "action": "write",      "node": 0, "key": "k", "value": "v"},
            {"at": 0.5,  "action": "partition",  "nodes": [0, 1]},
            {"at": 1.0,  "action": "heal",       "nodes": [0, 1]},
            {"at": 1.1,  "action": "elect",      "node": 1},
            {"at": 1.2,  "action": "sync",       "node": 1},
            {"at": 2.5,  "action": "run_until"}
        ]
    }

Actions:
    elect       — promote ``node`` to primary at a new term
    write       — append key/value via ``node`` (must be primary)
    partition   — partition ``nodes[0]`` from ``nodes[1]``
    heal        — heal the partition between ``nodes``
    sync        — ``node`` (primary) sends SyncLog to all peers
    run_until   — advance simulation clock to ``at``
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detsim.rng import DetRng
from detsim.engine import SimEngine
from detsim.network import Network
from detsim.buggify import Buggify
from detsim.tracer import TraceDB
from replication.protocol import Replica
from checker.safety import SafetyChecker


def run_campaign(config, db_path="/app/traces.db", report_path=None):
    """Execute a fault injection campaign described by *config*."""
    seed_start = config["seeds"]["start"]
    seed_end = config["seeds"]["end"]
    n_nodes = config.get("nodes", 3)
    use_buggify = config.get("buggify", False)
    latency = tuple(config.get("latency", [0.005, 0.050]))
    phases = sorted(config.get("phases", []), key=lambda p: p["at"])

    tracer = TraceDB(db_path)
    results = {"name": config.get("name", "unnamed"), "seeds": {}}

    for seed in range(seed_start, seed_end + 1):
        tracer.clear_seed(seed)

        rng = DetRng(seed)
        eng = SimEngine(rng)
        net = Network(eng, rng, latency=latency)

        bug = Buggify(rng)
        if use_buggify:
            bug.enable()

        nodes = [Replica(i, list(range(n_nodes)), net, eng)
                 for i in range(n_nodes)]

        committed = {}

        for phase in phases:
            at = phase["at"]
            action = phase["action"]

            if action == "run_until":
                eng.run(until=at)

            elif action == "elect":
                eng.run(until=at)
                nid = phase["node"]
                nodes[nid].become_primary()
                tracer.log_event(at, seed, "elect", src=nid,
                                 detail={"term": nodes[nid].term})

            elif action == "write":
                eng.run(until=at)
                nid = phase["node"]
                key, val = phase["key"], phase["value"]
                idx = nodes[nid].write(key, val)
                tracer.log_event(at, seed, "write", src=nid,
                                 detail={"key": key, "value": val,
                                         "idx": idx})
                # Allow time for replication + majority ack
                eng.run(until=at + 0.20)
                if nodes[nid].read(key) == val:
                    committed[key] = val
                    tracer.log_event(at + 0.20, seed, "commit", src=nid,
                                     detail={"key": key, "value": val})

            elif action == "partition":
                eng.run(until=at)
                a, b = phase["nodes"]
                net.partition(a, b)
                tracer.log_event(at, seed, "partition", src=a, dst=b)

            elif action == "heal":
                eng.run(until=at)
                a, b = phase["nodes"]
                net.heal(a, b)
                tracer.log_event(at, seed, "heal", src=a, dst=b)

            elif action == "sync":
                eng.run(until=at)
                nid = phase["node"]
                nodes[nid].initiate_sync()
                tracer.log_event(at, seed, "sync", src=nid)
                eng.run(until=at + 0.5)

        # Final state snapshots
        for node in nodes:
            tracer.snapshot_node(eng.now, seed, node)

        tracer.flush()

        results["seeds"][str(seed)] = {
            "committed": committed,
            "node_stores": {str(n.nid): dict(n.store) for n in nodes},
            "trace_len": len(eng.trace),
        }

    # Safety check
    checker = SafetyChecker(db_path)
    check = checker.check_all_seeds(seed_start, seed_end)
    results["safety_check"] = {
        "total_seeds": check["total_seeds"],
        "seeds_with_violations": check["seeds_with_violations"],
    }

    if report_path:
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Report written to {report_path}")

    tracer.close()

    print(f"\nCampaign '{config.get('name', 'unnamed')}' complete:")
    print(f"  Seeds: {seed_start}-{seed_end}")
    print(f"  Violations: {check['seeds_with_violations']}"
          f"/{check['total_seeds']}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", required=True,
                        help="Path to JSON campaign config")
    parser.add_argument("--db", default="/app/traces.db",
                        help="SQLite trace database path (default: /app/traces.db)")
    parser.add_argument("--report", default=None,
                        help="Path for JSON report output")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    results = run_campaign(config, db_path=args.db, report_path=args.report)

    if results["safety_check"]["seeds_with_violations"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
