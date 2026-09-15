#!/usr/bin/env python3
"""KernelCI Pipeline Job Router - v2.3.1

Routes kernel checkout events to LAVA labs based on pipeline configuration.

"""

import json
import os
import sys
from fnmatch import fnmatch

import yaml


def load_inputs():
    with open("/app/pipeline_config.yaml") as f:
        config = yaml.safe_load(f)
    with open("/app/checkout_events.json") as f:
        events = json.load(f)
    with open("/app/device_catalog.json") as f:
        catalog = json.load(f)
    return config, events, catalog


def validate_labs(config):
    errors = []
    excluded = set()

    for name, runtime in config.get("runtimes", {}).items():
        if runtime.get("lab_type") != "lava":
            continue

        pmin = runtime.get("priority_min", 0)
        pmax = runtime.get("priority_max", 100)
        if pmin >= pmax:
            errors.append({
                "lab": name,
                "error_type": "invalid_priority_range",
                "detail": f"priority_min ({pmin}) >= priority_max ({pmax})",
            })
            excluded.add(name)
            continue

        url = runtime.get("url", "")
        if url.startswith("http://"):
            errors.append({
                "lab": name,
                "error_type": "insecure_url",
                "detail": f"URL uses HTTP instead of HTTPS: {url}",
            })
            excluded.add(name)
            continue

        token = runtime.get("notify", {}).get("callback", {}).get("token", "")
        if not token:
            errors.append({
                "lab": name,
                "error_type": "missing_callback_token",
                "detail": "callback token is empty or missing",
            })
            excluded.add(name)
            continue

    errors.sort(key=lambda e: e["lab"])
    return errors, excluded


def matches_tree_rules(tree, rules):
    inclusion = [r for r in rules if not r.startswith("!")]
    exclusion = [r[1:] for r in rules if r.startswith("!")]

    for pattern in exclusion:
        if tree == pattern:
            return False

    for pattern in inclusion:
        if fnmatch(tree, pattern):
            return True

    return False


def count_inclusion_patterns(rules):
    return len([r for r in rules if not r.startswith("!")])


def get_boot_method(device_type):
    if device_type.startswith("qemu"):
        return "qemu"
    if device_type.startswith("x86"):
        return "grub"
    if device_type == "db410c":
        return "fastboot"
    return "u-boot"


def priority_fits(priority, pmin, pmax):
    return pmin <= priority <= pmax


def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return lo
    return value


def select_lab(eligible_labs, requested_priority, config):
    def sort_key(lab_name):
        rt = config["runtimes"][lab_name]
        pmin, pmax = rt["priority_min"], rt["priority_max"]
        fits = 0 if priority_fits(requested_priority, pmin, pmax) else 1
        prange = pmax - pmin
        tree_count = count_inclusion_patterns(rt.get("rules", {}).get("tree", []))
        return (fits, prange, tree_count, lab_name)

    return sorted(eligible_labs, key=sort_key)[0]


def generate_lava_job(event, lab_name, assigned_priority, config):
    runtime = config["runtimes"][lab_name]
    return {
        "device_type": event["device_type"],
        "job_name": (
            f"kernelci-{event['tree']}-{event['branch']}"
            f"-{event['device_type']}-{event['commit'][:8]}"
        ),
        "priority": assigned_priority,
        "timeouts": {
            "job": {"minutes": 30},
            "action": {"minutes": 10},
            "connection": {"minutes": 5},
        },
        "boot_method": get_boot_method(event["device_type"]),
        "notify": {
            "callback_url": f"https://callback.kernelci.org/lava/{lab_name}",
            "token": runtime["notify"]["callback"]["token"],
        },
    }


def route_events(config, events, catalog):
    validation_errors, excluded = validate_labs(config)

    routing_decisions = []
    labs_used = {}
    routed = 0
    unroutable = 0

    for event in events:
        tree = event["tree"]
        device = event["device_type"]
        priority = event["requested_priority"]

        device_labs = set(catalog.get(device, []))

        eligible = []
        for lab_name, runtime in config.get("runtimes", {}).items():
            if runtime.get("lab_type") != "lava":
                continue
            if lab_name in excluded:
                continue
            if lab_name not in device_labs:
                continue
            tree_rules = runtime.get("rules", {}).get("tree", [])
            if not matches_tree_rules(tree, tree_rules):
                continue
            eligible.append(lab_name)

        eligible.sort()

        if not eligible:
            unroutable += 1
            routing_decisions.append({
                "event_id": event["id"],
                "eligible_labs": [],
                "selected_lab": None,
                "assigned_priority": None,
                "priority_clamped": False,
                "lava_job": None,
            })
        else:
            selected = select_lab(eligible, priority, config)
            rt = config["runtimes"][selected]
            clamped = clamp(priority, rt["priority_min"], rt["priority_max"])
            was_clamped = clamped != priority

            job = generate_lava_job(event, selected, clamped, config)

            routed += 1
            labs_used[selected] = labs_used.get(selected, 0) + 1

            routing_decisions.append({
                "event_id": event["id"],
                "eligible_labs": eligible,
                "selected_lab": selected,
                "assigned_priority": clamped,
                "priority_clamped": was_clamped,
                "lava_job": job,
            })

    return {
        "routing_decisions": routing_decisions,
        "validation_errors": validation_errors,
        "summary": {
            "total_events": len(events),
            "routed": routed,
            "unroutable": unroutable,
            "labs_used": dict(sorted(labs_used.items())),
            "validation_error_count": len(validation_errors),
        },
    }


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("Usage: kci-router [--output PATH]")
        print()
        print("Routes kernel checkout events to LAVA labs based on pipeline config.")
        print()
        print("Options:")
        print("  --output PATH  Output file (default: /app/output/routing_report.json)")
        print()
        print("Input files (must exist in /app/):")
        print("  pipeline_config.yaml  Pipeline configuration")
        print("  checkout_events.json  Checkout events to route")
        print("  device_catalog.json   Device-to-lab mapping")
        return

    output_path = "/app/output/routing_report.json"
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    config, events, catalog = load_inputs()
    report = route_events(config, events, catalog)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Routing report written to {output_path}")
    print(f"  Total events: {report['summary']['total_events']}")
    print(f"  Routed: {report['summary']['routed']}")
    print(f"  Unroutable: {report['summary']['unroutable']}")
    print(f"  Validation errors: {report['summary']['validation_error_count']}")


if __name__ == "__main__":
    main()
