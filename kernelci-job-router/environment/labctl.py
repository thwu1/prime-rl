#!/usr/bin/env python3
"""labctl - KernelCI Lab Topology Inspector

Usage: labctl <command> [args]

Commands:
    list-labs                     List all configured lab runtimes
    show-lab <name>               Show detailed lab configuration
    list-devices                  List all known device types
    show-device <name>            Show which labs host a device
    check-tree <lab> <tree>       Check if a tree matches a lab's rules
    validate                      Validate all LAVA lab configurations
    reliability [options]         Query device reliability scores from DB
    topology [--json]             Show combined lab-device-tree topology
    eligible <tree> <device>      List labs eligible for a tree/device pair
    score <lab> <device> <pri> <headroom>
                                  Compute routing score for a scenario

Options for 'reliability':
    --lab LAB       Filter by lab name
    --device DEV    Filter by device type
    --json          Output as JSON array

"""

import json
import sqlite3
import sys
from fnmatch import fnmatch

import yaml


def load_config():
    with open("/app/pipeline_config.yaml") as f:
        return yaml.safe_load(f)


def load_catalog():
    with open("/app/device_catalog.json") as f:
        return json.load(f)


def open_reliability_db():
    conn = sqlite3.connect("/app/reliability.db")
    conn.row_factory = sqlite3.Row
    return conn


# ── list-labs ────────────────────────────────────────────────────────────


def cmd_list_labs(config):
    runtimes = config.get("runtimes", {})
    print(
        f"{'Lab Name':<25} {'Type':<12} {'Priority':<14} "
        f"{'Cap':<5} {'Cost':<6} {'Tree Rules'}"
    )
    print("-" * 100)
    for name in sorted(runtimes):
        rt = runtimes[name]
        lab_type = rt.get("lab_type", "unknown")
        pmin = rt.get("priority_min", "-")
        pmax = rt.get("priority_max", "-")
        prange = f"[{pmin},{pmax}]" if pmin != "-" else "N/A"
        cap = rt.get("capacity", "-")
        cost = rt.get("cost_factor", "-")
        rules = rt.get("rules", {}).get("tree", [])
        rules_str = ", ".join(rules[:4])
        if len(rules) > 4:
            rules_str += f" (+{len(rules) - 4} more)"
        print(
            f"{name:<25} {lab_type:<12} {prange:<14} "
            f"{str(cap):<5} {str(cost):<6} {rules_str}"
        )


# ── show-lab ─────────────────────────────────────────────────────────────


def cmd_show_lab(config, lab_name):
    runtimes = config.get("runtimes", {})
    if lab_name not in runtimes:
        print(f"Error: Lab '{lab_name}' not found")
        print(f"Available labs: {', '.join(sorted(runtimes.keys()))}")
        sys.exit(1)
    rt = runtimes[lab_name]
    print(f"Lab: {lab_name}")
    print(f"  Type: {rt.get('lab_type', 'unknown')}")
    print(f"  URL: {rt.get('url', 'N/A')}")
    if "priority_min" in rt:
        print(f"  Priority Range: [{rt['priority_min']}, {rt['priority_max']}]")
    if "capacity" in rt:
        print(f"  Capacity: {rt['capacity']}")
    if "cost_factor" in rt:
        print(f"  Cost Factor: {rt['cost_factor']}")
    if "notify" in rt:
        cb = rt["notify"].get("callback", {})
        token = cb.get("token", "")
        print(f"  Callback Token: {'(empty)' if not token else token}")
    # Reliability from SQLite DB
    try:
        conn = open_reliability_db()
        rows = conn.execute(
            "SELECT device_type, score FROM lab_reliability "
            "WHERE lab_name = ? ORDER BY device_type",
            (lab_name,),
        ).fetchall()
        conn.close()
        if rows:
            print(f"  Reliability Scores ({len(rows)} devices):")
            for row in rows:
                print(f"    {row['device_type']}: {row['score']}")
    except Exception:
        pass
    rules = rt.get("rules", {}).get("tree", [])
    if rules:
        inc = [r for r in rules if not r.startswith("!")]
        exc = [r for r in rules if r.startswith("!")]
        print(
            f"  Tree Rules ({len(rules)} total: "
            f"{len(inc)} include, {len(exc)} exclude):"
        )
        for r in rules:
            if r.startswith("!"):
                print(f"    EXCLUDE: {r[1:]}")
            else:
                print(f"    INCLUDE: {r}")


# ── list-devices ─────────────────────────────────────────────────────────


def cmd_list_devices(catalog):
    print(f"{'Device Type':<40} {'Lab Count':<10} {'Labs'}")
    print("-" * 90)
    for dev in sorted(catalog):
        labs = catalog[dev]
        labs_str = ", ".join(labs) if labs else "(none)"
        print(f"{dev:<40} {len(labs):<10} {labs_str}")


# ── show-device ──────────────────────────────────────────────────────────


def cmd_show_device(catalog, device_name):
    if device_name not in catalog:
        print(f"Error: Device '{device_name}' not found in catalog")
        print(f"Available devices: {', '.join(sorted(catalog.keys()))}")
        sys.exit(1)
    labs = catalog[device_name]
    print(f"Device: {device_name}")
    if labs:
        print(f"Available at {len(labs)} lab(s):")
        for lab in sorted(labs):
            print(f"  - {lab}")
    else:
        print("Not available at any lab")


# ── check-tree ───────────────────────────────────────────────────────────


def cmd_check_tree(config, lab_name, tree):
    runtimes = config.get("runtimes", {})
    if lab_name not in runtimes:
        print(f"Error: Lab '{lab_name}' not found")
        sys.exit(1)
    rt = runtimes[lab_name]
    rules = rt.get("rules", {}).get("tree", [])
    inclusion = [r for r in rules if not r.startswith("!")]
    exclusion = [r[1:] for r in rules if r.startswith("!")]

    print(f"Checking tree '{tree}' against {lab_name} rules:")
    print()

    for pattern in exclusion:
        match = fnmatch(tree, pattern)
        status = "MATCHED" if match else "no match"
        print(f"  Exclusion '!{pattern}': {status}")
        if match:
            print(
                f"\nResult: EXCLUDED (blocked by exclusion pattern '!{pattern}')"
            )
            return

    matched_inclusion = False
    for pattern in inclusion:
        match = fnmatch(tree, pattern)
        status = "MATCHED" if match else "no match"
        print(f"  Inclusion '{pattern}': {status}")
        if match and not matched_inclusion:
            matched_inclusion = True

    print()
    if matched_inclusion:
        print("Result: ELIGIBLE")
    else:
        print("Result: NOT ELIGIBLE (no inclusion rule matched)")


# ── validate ─────────────────────────────────────────────────────────────


def cmd_validate(config):
    runtimes = config.get("runtimes", {})
    errors = []
    lava_count = 0

    for name in sorted(runtimes):
        rt = runtimes[name]
        if rt.get("lab_type") != "lava":
            continue
        lava_count += 1

        pmin = rt.get("priority_min", 0)
        pmax = rt.get("priority_max", 100)
        if pmin >= pmax:
            errors.append(
                (
                    name,
                    "invalid_priority_range",
                    f"priority_min ({pmin}) >= priority_max ({pmax})",
                )
            )
            continue

        url = rt.get("url", "")
        if url.startswith("http://"):
            errors.append((name, "insecure_url", f"URL uses HTTP: {url}"))
            continue

        token = rt.get("notify", {}).get("callback", {}).get("token", "")
        if not token:
            errors.append(
                (name, "missing_callback_token", "Callback token is empty or missing")
            )
            continue

    if errors:
        print(f"Validation errors ({len(errors)}):")
        for lab, etype, detail in errors:
            print(f"  [{lab}] {etype}: {detail}")
    else:
        print("All LAVA labs passed validation.")

    valid = lava_count - len(errors)
    print(f"\n{lava_count} LAVA labs total, {valid} valid, {len(errors)} with errors")


# ── reliability ──────────────────────────────────────────────────────────


def cmd_reliability(args):
    lab_filter = None
    device_filter = None
    json_output = False
    i = 0
    while i < len(args):
        if args[i] == "--lab" and i + 1 < len(args):
            lab_filter = args[i + 1]
            i += 2
        elif args[i] == "--device" and i + 1 < len(args):
            device_filter = args[i + 1]
            i += 2
        elif args[i] == "--json":
            json_output = True
            i += 1
        else:
            i += 1

    conn = open_reliability_db()
    c = conn.cursor()

    query = "SELECT lab_name, device_type, score FROM lab_reliability WHERE 1=1"
    params = []
    if lab_filter:
        query += " AND lab_name = ?"
        params.append(lab_filter)
    if device_filter:
        query += " AND device_type = ?"
        params.append(device_filter)
    query += " ORDER BY lab_name, device_type"

    rows = c.execute(query, params).fetchall()

    if json_output:
        result = [
            {"lab": r["lab_name"], "device": r["device_type"], "score": r["score"]}
            for r in rows
        ]
        print(json.dumps(result, indent=2))
    else:
        meta = dict(
            c.execute("SELECT key, value FROM reliability_metadata").fetchall()
        )
        print(f"Reliability Database v{meta.get('version', '?')}")
        print(f"Default score: {meta.get('default_score', '0.50')}")
        print(f"Computation window: {meta.get('computation_window', '?')}")
        print()
        print(f"{'Lab':<25} {'Device Type':<35} {'Score'}")
        print("-" * 70)
        for r in rows:
            print(f"{r['lab_name']:<25} {r['device_type']:<35} {r['score']:.2f}")
        print(f"\n{len(rows)} record(s)")

    conn.close()


# ── topology ─────────────────────────────────────────────────────────────


def cmd_topology(config, catalog, args):
    json_output = "--json" in args
    conn = open_reliability_db()
    c = conn.cursor()

    runtimes = config.get("runtimes", {})

    if json_output:
        topology = {}
        for name in sorted(runtimes):
            rt = runtimes[name]
            if rt.get("lab_type") != "lava":
                continue
            devices_at_lab = sorted(
                d for d, labs in catalog.items() if name in labs
            )
            rel_rows = c.execute(
                "SELECT device_type, score FROM lab_reliability WHERE lab_name = ?",
                (name,),
            ).fetchall()
            reliability = {r["device_type"]: r["score"] for r in rel_rows}

            topology[name] = {
                "url": rt.get("url", ""),
                "priority_range": [
                    rt.get("priority_min"),
                    rt.get("priority_max"),
                ],
                "capacity": rt.get("capacity"),
                "cost_factor": rt.get("cost_factor"),
                "devices": devices_at_lab,
                "reliability": reliability,
                "tree_rules": rt.get("rules", {}).get("tree", []),
                "notify_token": rt.get("notify", {})
                .get("callback", {})
                .get("token", ""),
            }
        print(json.dumps(topology, indent=2))
    else:
        for name in sorted(runtimes):
            rt = runtimes[name]
            if rt.get("lab_type") != "lava":
                continue
            devices = sorted(d for d, labs in catalog.items() if name in labs)
            rules = rt.get("rules", {}).get("tree", [])
            cap = rt.get("capacity", "?")
            cost = rt.get("cost_factor", "?")
            pmin = rt.get("priority_min", "?")
            pmax = rt.get("priority_max", "?")

            rel_rows = c.execute(
                "SELECT device_type, score FROM lab_reliability WHERE lab_name = ?",
                (name,),
            ).fetchall()

            print(f"{name}:")
            print(f"  URL: {rt.get('url', '?')}")
            print(f"  Priority: [{pmin}, {pmax}]  Capacity: {cap}  Cost: {cost}")
            print(f"  Devices: {', '.join(devices) if devices else '(none)'}")
            if rel_rows:
                rel_strs = [
                    f"{r['device_type']}={r['score']:.2f}" for r in rel_rows
                ]
                print(f"  Reliability: {', '.join(rel_strs)}")
            print(f"  Tree rules: {', '.join(rules)}")
            print()

    conn.close()


# ── eligible ─────────────────────────────────────────────────────────────


def cmd_eligible(config, catalog, tree, device):
    runtimes = config.get("runtimes", {})
    device_labs = set(catalog.get(device, []))

    if not device_labs:
        print(f"Device '{device}' not found in any lab's catalog.")
        return

    print(f"Checking eligibility for tree='{tree}', device='{device}'")
    print(f"Device available at: {', '.join(sorted(device_labs))}")
    print()

    eligible = []
    for name in sorted(runtimes):
        rt = runtimes[name]
        if rt.get("lab_type") != "lava":
            continue
        if name not in device_labs:
            continue

        tree_rules = rt.get("rules", {}).get("tree", [])
        inclusion = [r for r in tree_rules if not r.startswith("!")]
        exclusion = [r[1:] for r in tree_rules if r.startswith("!")]

        excluded = False
        for pattern in exclusion:
            if fnmatch(tree, pattern):
                print(f"  {name}: EXCLUDED (exclusion rule '!{pattern}')")
                excluded = True
                break

        if excluded:
            continue

        matched = False
        matched_pattern = None
        for pattern in inclusion:
            if fnmatch(tree, pattern):
                matched = True
                matched_pattern = pattern
                break

        if matched:
            eligible.append(name)
            print(f"  {name}: ELIGIBLE (matched '{matched_pattern}')")
        else:
            print(f"  {name}: NOT ELIGIBLE (no inclusion match)")

    print(f"\n{len(eligible)} eligible lab(s): {', '.join(eligible)}")


# ── score ────────────────────────────────────────────────────────────────


def cmd_score(config, lab, device, priority, headroom):
    runtimes = config.get("runtimes", {})
    if lab not in runtimes:
        print(f"Error: Lab '{lab}' not found")
        sys.exit(1)

    rt = runtimes[lab]
    pmin = rt.get("priority_min", 0)
    pmax = rt.get("priority_max", 100)
    cost = rt.get("cost_factor", 0.50)

    conn = open_reliability_db()
    row = conn.execute(
        "SELECT score FROM lab_reliability WHERE lab_name = ? AND device_type = ?",
        (lab, device),
    ).fetchone()
    r_score = row[0] if row else 0.50
    conn.close()

    f_score = 1.0 if pmin <= priority <= pmax else 0.0
    h_score = headroom
    c_score = cost

    total = 0.4 * r_score + 0.3 * f_score + 0.2 * h_score + 0.1 * (1.0 - c_score)

    print(f"Score computation for {lab} / {device}:")
    print(f"  R (reliability):     {r_score:.4f}  (w=0.4) -> {0.4 * r_score:.4f}")
    print(f"  F (priority fit):    {f_score:.4f}  (w=0.3) -> {0.3 * f_score:.4f}")
    print(
        f"    requested={priority}, range=[{pmin},{pmax}], "
        f"{'in range' if f_score == 1.0 else 'out of range'}"
    )
    print(f"  H (headroom):        {h_score:.4f}  (w=0.2) -> {0.2 * h_score:.4f}")
    print(
        f"  C (cost):            {c_score:.4f}  (w=0.1) -> "
        f"{0.1 * (1.0 - c_score):.4f}"
    )
    print(f"  {'─' * 42}")
    print(f"  Total score:         {total:.4f}")


# ── main ─────────────────────────────────────────────────────────────────


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print(__doc__.strip())
        return

    cmd = sys.argv[1]
    config = load_config()

    if cmd == "list-labs":
        cmd_list_labs(config)
    elif cmd == "show-lab":
        if len(sys.argv) < 3:
            print("Usage: labctl show-lab <name>")
            sys.exit(1)
        cmd_show_lab(config, sys.argv[2])
    elif cmd == "list-devices":
        catalog = load_catalog()
        cmd_list_devices(catalog)
    elif cmd == "show-device":
        if len(sys.argv) < 3:
            print("Usage: labctl show-device <name>")
            sys.exit(1)
        catalog = load_catalog()
        cmd_show_device(catalog, sys.argv[2])
    elif cmd == "check-tree":
        if len(sys.argv) < 4:
            print("Usage: labctl check-tree <lab> <tree>")
            sys.exit(1)
        cmd_check_tree(config, sys.argv[2], sys.argv[3])
    elif cmd == "validate":
        cmd_validate(config)
    elif cmd == "reliability":
        cmd_reliability(sys.argv[2:])
    elif cmd == "topology":
        catalog = load_catalog()
        cmd_topology(config, catalog, sys.argv[2:])
    elif cmd == "eligible":
        if len(sys.argv) < 4:
            print("Usage: labctl eligible <tree> <device>")
            sys.exit(1)
        catalog = load_catalog()
        cmd_eligible(config, catalog, sys.argv[2], sys.argv[3])
    elif cmd == "score":
        if len(sys.argv) < 6:
            print("Usage: labctl score <lab> <device> <priority> <headroom>")
            print("  priority: integer")
            print("  headroom: float [0.0, 1.0]")
            sys.exit(1)
        cmd_score(
            config,
            sys.argv[2],
            sys.argv[3],
            int(sys.argv[4]),
            float(sys.argv[5]),
        )
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'labctl --help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
