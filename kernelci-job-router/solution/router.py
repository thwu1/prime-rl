#!/usr/bin/env python3
"""KernelCI Capacity-Aware Pipeline Job Router — Reference Implementation.

"""

import json
import os
import sqlite3
from fnmatch import fnmatch

import yaml


# ── I/O ───────────────────────────────────────────────────────────────────


def load_inputs():
    with open("/app/pipeline_config.yaml") as f:
        config = yaml.safe_load(f)
    with open("/app/checkout_events.json") as f:
        events = json.load(f)
    with open("/app/device_catalog.json") as f:
        catalog = json.load(f)

    conn = sqlite3.connect("/app/reliability.db")
    rows = conn.execute(
        "SELECT lab_name, device_type, score FROM lab_reliability"
    ).fetchall()
    reliability = {}
    for lab, device, score in rows:
        reliability.setdefault(lab, {})[device] = score
    conn.close()

    return config, events, catalog, reliability


# ── Step 1: Validate Labs ────────────────────────────────────────────────


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


# ── Tree Rule Matching ───────────────────────────────────────────────────


def matches_tree_rules(tree, rules):
    inclusion = [r for r in rules if not r.startswith("!")]
    exclusion = [r[1:] for r in rules if r.startswith("!")]

    for pattern in exclusion:
        if fnmatch(tree, pattern):
            return False

    for pattern in inclusion:
        if fnmatch(tree, pattern):
            return True

    return False


# ── Scoring ──────────────────────────────────────────────────────────────


def compute_score(lab_name, device_type, requested_priority, remaining_cap,
                  config, reliability):
    rt = config["runtimes"][lab_name]
    pmin, pmax = rt["priority_min"], rt["priority_max"]
    max_cap = rt["capacity"]

    r = reliability.get(lab_name, {}).get(device_type, 0.50)
    f = 1.0 if pmin <= requested_priority <= pmax else 0.0
    h = remaining_cap / max_cap
    c = rt.get("cost_factor", 0.50)

    return 0.4 * r + 0.3 * f + 0.2 * h + 0.1 * (1.0 - c)


def select_lab(eligible_labs, device_type, requested_priority,
               remaining_capacity, config, reliability):
    best_lab = None
    best_score = -1.0

    for lab in sorted(eligible_labs):
        score = compute_score(lab, device_type, requested_priority,
                              remaining_capacity[lab], config, reliability)
        if score > best_score:
            best_score = score
            best_lab = lab

    return best_lab


# ── Boot Method ──────────────────────────────────────────────────────────


def get_boot_method(device_type):
    if device_type.startswith("qemu"):
        return "qemu"
    if device_type.startswith("x86"):
        return "grub"
    if device_type == "db410c":
        return "fastboot"
    return "u-boot"


# ── LAVA Job Generation ─────────────────────────────────────────────────


def generate_lava_job(event, lab_name, assigned_priority, config):
    runtime = config["runtimes"][lab_name]
    return {
        "device_type": event["device_type"],
        "job_name": (
            f"kernelci-{event['tree']}-{event['branch']}"
            f"-{event['device_type']}-{event['commit']}"
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


# ── Unconstrained Routing (for capacity impact) ─────────────────────────


def get_eligible_unconstrained(event, config, catalog, excluded):
    tree = event["tree"]
    device = event["device_type"]
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

    return sorted(eligible)


def select_lab_unconstrained(eligible_labs, device_type, requested_priority,
                             config, reliability):
    best_lab = None
    best_score = -1.0

    for lab in sorted(eligible_labs):
        rt = config["runtimes"][lab]
        pmin, pmax = rt["priority_min"], rt["priority_max"]
        r = reliability.get(lab, {}).get(device_type, 0.50)
        f = 1.0 if pmin <= requested_priority <= pmax else 0.0
        h = 1.0  # unlimited capacity
        c = rt.get("cost_factor", 0.50)
        score = 0.4 * r + 0.3 * f + 0.2 * h + 0.1 * (1.0 - c)

        if score > best_score:
            best_score = score
            best_lab = lab

    return best_lab


# ── Main Routing ─────────────────────────────────────────────────────────


def route_events(config, events, catalog, reliability):
    validation_errors, excluded = validate_labs(config)

    # Initialize capacity tracking
    remaining_capacity = {}
    for name, runtime in config.get("runtimes", {}).items():
        if runtime.get("lab_type") == "lava" and name not in excluded:
            remaining_capacity[name] = runtime.get("capacity", 1)

    routing_decisions = []
    labs_used = {}
    routed = 0
    unroutable_spec = 0
    unroutable_cap = 0

    # Track actual routing per event for capacity impact
    actual_routing = {}

    for event in events:
        tree = event["tree"]
        device = event["device_type"]
        priority = event["requested_priority"]

        device_labs = set(catalog.get(device, []))

        # Filter eligible labs (including capacity check)
        eligible = []
        eligible_no_cap = []  # eligible ignoring capacity

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
            eligible_no_cap.append(lab_name)
            if remaining_capacity.get(lab_name, 0) > 0:
                eligible.append(lab_name)

        eligible.sort()
        eligible_no_cap.sort()

        if not eligible:
            if not eligible_no_cap:
                unroutable_spec += 1
            else:
                unroutable_cap += 1

            routing_decisions.append({
                "event_id": event["id"],
                "eligible_labs": [],
                "selected_lab": None,
                "assigned_priority": None,
                "priority_clamped": False,
                "lava_job": None,
            })
            actual_routing[event["id"]] = {
                "selected": None,
                "eligible_no_cap": eligible_no_cap,
            }
        else:
            selected = select_lab(eligible, device, priority,
                                  remaining_capacity, config, reliability)
            rt = config["runtimes"][selected]
            clamped = max(rt["priority_min"],
                         min(priority, rt["priority_max"]))
            was_clamped = clamped != priority

            job = generate_lava_job(event, selected, clamped, config)

            remaining_capacity[selected] -= 1
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
            actual_routing[event["id"]] = {
                "selected": selected,
                "eligible_no_cap": eligible_no_cap,
            }

    # ── Capacity Impact Analysis ─────────────────────────────────────

    rerouted_events = []
    blocked_events = []

    for event in events:
        eid = event["id"]
        actual = actual_routing[eid]

        # Get unconstrained eligible labs
        uc_eligible = get_eligible_unconstrained(event, config, catalog,
                                                 excluded)
        if not uc_eligible:
            continue  # spec-unroutable, no capacity impact

        uc_winner = select_lab_unconstrained(
            uc_eligible, event["device_type"],
            event["requested_priority"], config, reliability)

        if actual["selected"] is None:
            # Blocked by capacity
            blocked_events.append({
                "event_id": eid,
                "unconstrained_lab": uc_winner,
                "exhausted_labs": sorted(actual["eligible_no_cap"]),
            })
        elif actual["selected"] != uc_winner:
            # Rerouted due to capacity
            rerouted_events.append({
                "event_id": eid,
                "actual_lab": actual["selected"],
                "unconstrained_lab": uc_winner,
            })

    rerouted_events.sort(key=lambda x: x["event_id"])
    blocked_events.sort(key=lambda x: x["event_id"])

    return {
        "routing_decisions": routing_decisions,
        "validation_errors": validation_errors,
        "summary": {
            "total_events": len(events),
            "routed": routed,
            "unroutable": unroutable_spec + unroutable_cap,
            "unroutable_by_spec": unroutable_spec,
            "unroutable_by_capacity": unroutable_cap,
            "labs_used": dict(sorted(labs_used.items())),
            "validation_error_count": len(validation_errors),
        },
        "capacity_impact": {
            "rerouted_events": rerouted_events,
            "blocked_events": blocked_events,
            "total_rerouted": len(rerouted_events),
            "total_blocked": len(blocked_events),
        },
    }


def main():
    config, events, catalog, reliability = load_inputs()
    report = route_events(config, events, catalog, reliability)
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/routing_report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
