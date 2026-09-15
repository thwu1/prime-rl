#!/usr/bin/env python3

"""HTB Qdisc Hierarchy Analyzer.

Parses a multi-interface HTB tc configuration, validates it for
misconfigurations, computes steady-state per-leaf-class bandwidth
allocation under full load using the HTB model spec, and checks
SLA compliance.
"""

import json


def load_json(path):
    with open(path) as f:
        return json.load(f)


def validate_config(config):
    """Detect configuration errors across all interfaces."""
    errors = []

    for iface, icfg in config["interfaces"].items():
        classes = icfg["classes"]
        by_id = {c["classid"]: c for c in classes}
        qdisc_handle = icfg["qdisc"]["handle"]

        # Build children-of mapping
        children_of = {}
        for c in classes:
            children_of.setdefault(c["parent"], []).append(c)

        # 1. Orphan classes: parent is neither qdisc handle nor existing class
        for c in classes:
            p = c["parent"]
            if p != qdisc_handle and p not in by_id:
                errors.append({
                    "type": "orphan_class",
                    "interface": iface,
                    "class": c["classid"],
                    "details": f"Parent {p} does not exist in the hierarchy",
                })

        # 2. Ceil exceeds parent ceil
        for c in classes:
            if c["parent"] in by_id:
                parent = by_id[c["parent"]]
                if c["ceil_mbps"] > parent["ceil_mbps"]:
                    errors.append({
                        "type": "ceil_exceeds_parent",
                        "interface": iface,
                        "class": c["classid"],
                        "details": (
                            f"ceil {c['ceil_mbps']} Mbps exceeds parent "
                            f"{c['parent']} ceil {parent['ceil_mbps']} Mbps"
                        ),
                    })

        # 3. Rate oversubscription: children's rate sum > parent rate
        for parent_id, child_list in children_of.items():
            if parent_id in by_id:
                parent = by_id[parent_id]
                total_child_rate = sum(c["rate_mbps"] for c in child_list)
                if total_child_rate > parent["rate_mbps"]:
                    errors.append({
                        "type": "rate_oversubscription",
                        "interface": iface,
                        "class": parent_id,
                        "details": (
                            f"Children rates sum {total_child_rate} Mbps exceeds "
                            f"parent rate {parent['rate_mbps']} Mbps"
                        ),
                    })

        # 4. Missing default class
        default_cls = icfg["qdisc"].get("default_class")
        if default_cls and default_cls not in by_id:
            errors.append({
                "type": "missing_default_class",
                "interface": iface,
                "qdisc": qdisc_handle,
                "class": default_cls,
                "details": f"Default class {default_cls} does not exist",
            })

        # 5. Invalid filter targets
        for flt in icfg.get("filters", []):
            flowid = flt["flowid"]
            if flowid not in by_id:
                errors.append({
                    "type": "invalid_filter_target",
                    "interface": iface,
                    "filter_flowid": flowid,
                    "details": f"Filter target class {flowid} does not exist",
                })

    return errors


def compute_leaf_allocations(cls, available_bw, children_map):
    """Recursively compute leaf bandwidth using the HTB model spec algorithm.

    Args:
        cls: The current class dict.
        available_bw: Bandwidth available from parent.
        children_map: Dict mapping classid -> list of child class dicts.

    Returns:
        Dict mapping leaf classid -> allocated bandwidth (float).
    """
    classid = cls["classid"]
    effective_bw = min(available_bw, cls["ceil_mbps"])

    children = children_map.get(classid, [])
    if not children:
        # Leaf class
        return {classid: effective_bw}

    # Group children by priority
    by_prio = {}
    for child in children:
        by_prio.setdefault(child["prio"], []).append(child)

    # Initialize per-child allocation
    alloc = {child["classid"]: 0.0 for child in children}
    remaining = effective_bw
    oversubscribed = False

    # Phase 1: Guaranteed rate allocation
    for prio in sorted(by_prio.keys()):
        group = by_prio[prio]
        total_rate = sum(c["rate_mbps"] for c in group)

        if total_rate <= remaining:
            # All guarantees fit
            for c in group:
                alloc[c["classid"]] = float(c["rate_mbps"])
            remaining -= total_rate
        else:
            # Oversubscription: distribute remaining by quantum
            total_quantum = sum(c["quantum"] for c in group)
            for c in group:
                alloc[c["classid"]] = remaining * c["quantum"] / total_quantum
            remaining = 0.0
            oversubscribed = True
            # All lower-priority children get nothing
            for lower_prio in sorted(by_prio.keys()):
                if lower_prio > prio:
                    for c in by_prio[lower_prio]:
                        alloc[c["classid"]] = 0.0
            break

    # Phase 2: Excess bandwidth distribution (water-filling)
    if not oversubscribed and remaining > 0.001:
        for prio in sorted(by_prio.keys()):
            if remaining <= 0.001:
                break
            group = by_prio[prio]

            for _ in range(200):  # max iterations for convergence
                if remaining <= 0.001:
                    break
                active = [
                    c for c in group
                    if alloc[c["classid"]] < c["ceil_mbps"] - 0.001
                ]
                if not active:
                    break

                total_quantum = sum(c["quantum"] for c in active)
                given = 0.0
                for c in active:
                    fair_share = remaining * c["quantum"] / total_quantum
                    room = c["ceil_mbps"] - alloc[c["classid"]]
                    actual = min(fair_share, room)
                    alloc[c["classid"]] += actual
                    given += actual
                remaining -= given
                if given < 0.001:
                    break

    # Recurse into each child
    result = {}
    for child in children:
        child_bw = min(alloc[child["classid"]], child["ceil_mbps"])
        sub_result = compute_leaf_allocations(child, child_bw, children_map)
        result.update(sub_result)

    return result


def main():
    config = load_json("/app/tc_config.json")
    sla = load_json("/app/sla_requirements.json")

    # Validate configuration
    errors = validate_config(config)

    # Compute allocations per interface
    leaf_allocations = {}

    for iface, icfg in config["interfaces"].items():
        classes = icfg["classes"]
        by_id = {c["classid"]: c for c in classes}
        qdisc_handle = icfg["qdisc"]["handle"]

        # Build children map, excluding orphan classes
        children_map = {}
        for c in classes:
            parent = c["parent"]
            if parent == qdisc_handle or parent in by_id:
                children_map.setdefault(parent, []).append(c)

        # Find root class (direct child of qdisc handle)
        root_classes = children_map.get(qdisc_handle, [])
        if not root_classes:
            continue
        root = root_classes[0]

        # Compute recursive allocation
        raw_allocs = compute_leaf_allocations(
            root, root["rate_mbps"], children_map
        )

        # Round to 2 decimal places
        leaf_allocations[iface] = {
            cid: round(bw, 2) for cid, bw in raw_allocs.items()
        }

    # Check SLA requirements
    sla_violations = []
    for req in sla["requirements"]:
        iface = req["interface"]
        class_id = req["class_id"]
        min_bw = req["min_bandwidth_mbps"]
        actual_bw = leaf_allocations.get(iface, {}).get(class_id, 0.0)

        if actual_bw < min_bw:
            sla_violations.append({
                "class": class_id,
                "interface": iface,
                "required_mbps": min_bw,
                "actual_mbps": actual_bw,
            })

    # Write report
    report = {
        "validation_errors": errors,
        "leaf_allocations": leaf_allocations,
        "sla_violations": sla_violations,
    }

    with open("/app/analysis_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(
        f"Analysis complete: {len(errors)} validation errors, "
        f"{len(sla_violations)} SLA violations detected."
    )


if __name__ == "__main__":
    main()
