#!/usr/bin/env python3
"""kci-events - KernelCI Checkout Event Inspector

Usage: kci-events <command> [options]

Commands:
    list [--tree=X] [--device=Y] [--format=table|json]
        List checkout events with optional filtering

    show <event_id>
        Show detailed information about a single event

    stats [--format=table|json]
        Show event statistics (tree/device/priority distributions)

    group-by <field>
        Group events by: tree, device_type, requested_priority

    batch-check [--json]
        Cross-reference events with device catalog to show
        which events have candidate labs (pre-validation)

"""

import json
import sys


def load_events():
    with open("/app/checkout_events.json") as f:
        return json.load(f)


def load_catalog():
    with open("/app/device_catalog.json") as f:
        return json.load(f)


def cmd_list(events, args):
    tree_filter = None
    device_filter = None
    fmt = "table"
    for a in args:
        if a.startswith("--tree="):
            tree_filter = a.split("=", 1)[1]
        elif a.startswith("--device="):
            device_filter = a.split("=", 1)[1]
        elif a.startswith("--format="):
            fmt = a.split("=", 1)[1]

    filtered = events
    if tree_filter:
        filtered = [e for e in filtered if e["tree"] == tree_filter]
    if device_filter:
        filtered = [e for e in filtered if e["device_type"] == device_filter]

    if fmt == "json":
        print(json.dumps(filtered, indent=2))
    else:
        print(
            f"{'ID':<10} {'Tree':<20} {'Branch':<22} "
            f"{'Device':<32} {'Pri':<5} {'Commit'}"
        )
        print("-" * 105)
        for e in filtered:
            print(
                f"{e['id']:<10} {e['tree']:<20} {e['branch']:<22} "
                f"{e['device_type']:<32} {e['requested_priority']:<5} "
                f"{e['commit']}"
            )
        print(f"\n{len(filtered)} event(s)")


def cmd_show(events, event_id):
    for e in events:
        if e["id"] == event_id:
            print(f"Event: {e['id']}")
            print(f"  Tree:     {e['tree']}")
            print(f"  Branch:   {e['branch']}")
            print(f"  Commit:   {e['commit']}")
            print(f"  Device:   {e['device_type']}")
            print(f"  Priority: {e['requested_priority']}")
            return
    print(f"Error: Event '{event_id}' not found")
    sys.exit(1)


def cmd_stats(events, args):
    fmt = "table"
    for a in args:
        if a.startswith("--format="):
            fmt = a.split("=", 1)[1]

    trees = {}
    devices = {}
    priorities = []
    for e in events:
        trees[e["tree"]] = trees.get(e["tree"], 0) + 1
        devices[e["device_type"]] = devices.get(e["device_type"], 0) + 1
        priorities.append(e["requested_priority"])

    if fmt == "json":
        print(
            json.dumps(
                {
                    "total_events": len(events),
                    "unique_trees": len(trees),
                    "unique_devices": len(devices),
                    "trees": dict(sorted(trees.items())),
                    "devices": dict(sorted(devices.items())),
                    "priority_min": min(priorities),
                    "priority_max": max(priorities),
                    "priority_mean": round(
                        sum(priorities) / len(priorities), 1
                    ),
                },
                indent=2,
            )
        )
    else:
        print(f"Total events: {len(events)}")
        print(f"\nTrees ({len(trees)} unique):")
        for t in sorted(trees, key=trees.get, reverse=True):
            print(f"  {t}: {trees[t]}")
        print(f"\nDevices ({len(devices)} unique):")
        for d in sorted(devices, key=devices.get, reverse=True):
            print(f"  {d}: {devices[d]}")
        print(f"\nPriority range: [{min(priorities)}, {max(priorities)}]")
        print(
            f"Priority mean: {sum(priorities) / len(priorities):.1f}"
        )


def cmd_group_by(events, field):
    valid_fields = ("tree", "device_type", "requested_priority")
    if field not in valid_fields:
        print(
            f"Error: Cannot group by '{field}'. "
            f"Use: {', '.join(valid_fields)}"
        )
        sys.exit(1)

    groups = {}
    for e in events:
        key = str(e[field])
        groups.setdefault(key, []).append(e["id"])

    for key in sorted(groups):
        print(f"{key}:")
        for eid in groups[key]:
            print(f"  {eid}")
        print()


def cmd_batch_check(events, catalog, args):
    json_output = "--json" in args
    results = []

    for e in events:
        labs = catalog.get(e["device_type"], [])
        results.append(
            {
                "event_id": e["id"],
                "tree": e["tree"],
                "device_type": e["device_type"],
                "candidate_labs": labs,
                "candidate_count": len(labs),
            }
        )

    if json_output:
        print(json.dumps(results, indent=2))
    else:
        print(
            f"{'Event':<10} {'Tree':<20} {'Device':<32} "
            f"{'#':<4} {'Candidate Labs'}"
        )
        print("-" * 105)
        for r in results:
            labs_str = (
                ", ".join(r["candidate_labs"])
                if r["candidate_labs"]
                else "(none)"
            )
            print(
                f"{r['event_id']:<10} {r['tree']:<20} "
                f"{r['device_type']:<32} {r['candidate_count']:<4} "
                f"{labs_str}"
            )


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print(__doc__.strip())
        return

    cmd = sys.argv[1]
    events = load_events()

    if cmd == "list":
        cmd_list(events, sys.argv[2:])
    elif cmd == "show":
        if len(sys.argv) < 3:
            print("Usage: kci-events show <event_id>")
            sys.exit(1)
        cmd_show(events, sys.argv[2])
    elif cmd == "stats":
        cmd_stats(events, sys.argv[2:])
    elif cmd == "group-by":
        if len(sys.argv) < 3:
            print("Usage: kci-events group-by <field>")
            sys.exit(1)
        cmd_group_by(events, sys.argv[2])
    elif cmd == "batch-check":
        catalog = load_catalog()
        cmd_batch_check(events, catalog, sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'kci-events --help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
