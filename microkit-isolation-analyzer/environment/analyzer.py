#!/usr/bin/env python3
"""
Isolation analyzer for seL4 Microkit system descriptions.
Analyzes protection domain dependencies, computes TCB and impact boundaries,
and checks security policy constraints.
"""

import json
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_system(xml_path):
    """Parse the Microkit system description XML."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    memory_regions = {}
    for mr in root.findall("memory_region"):
        memory_regions[mr.get("name")] = mr.get("size")

    pds = {}
    channels = []
    parent_child = []

    def extract_pds(element, parent_name=None):
        for pd_elem in element.findall("protection_domain"):
            name = pd_elem.get("name")
            priority = int(pd_elem.get("priority", "0"))

            maps = []
            for m in pd_elem.findall("map"):
                maps.append({
                    "mr": m.get("mr"),
                    "perms": m.get("perms", "r"),
                })

            irqs = []
            for irq in pd_elem.findall("irq"):
                irqs.append(int(irq.get("irq")))

            pds[name] = {
                "priority": priority,
                "maps": maps,
                "irqs": irqs,
                "parent": parent_name,
            }

            if parent_name is not None:
                parent_child.append((name, parent_name))

            extract_pds(pd_elem, parent_name=name)

    extract_pds(root)

    for ch in root.findall("channel"):
        ends = ch.findall("end")
        if len(ends) == 2:
            channels.append((ends[0].get("pd"), ends[1].get("pd")))

    return memory_regions, pds, channels, parent_child


def build_dependency_graph(pds, channels, parent_child):
    """Build the directed dependency graph.

    X depends on Y if they share a memory region, communicate via a channel,
    or have a parent-child relationship.
    """
    all_pd_names = sorted(pds.keys())
    deps = defaultdict(set)

    # Shared memory: if two PDs map the same region, they depend on each other
    region_to_pds = defaultdict(list)
    for pd_name, pd_info in pds.items():
        for m in pd_info["maps"]:
            region_to_pds[m["mr"]].append(pd_name)

    for region, pd_list in region_to_pds.items():
        if len(pd_list) >= 2:
            for pd_a in pd_list:
                for pd_b in pd_list:
                    if pd_a != pd_b:
                        deps[pd_a].add(pd_b)

    # Channel communication (bidirectional)
    for pd_a, pd_b in channels:
        deps[pd_a].add(pd_b)
        deps[pd_b].add(pd_a)

    # Parent-child (child depends on parent)
    for child, parent in parent_child:
        deps[child].add(parent)

    dep_graph = {}
    for pd in all_pd_names:
        dep_graph[pd] = sorted(deps[pd] - {pd})

    return dep_graph


def compute_tcb(dep_graph):
    """Compute the TCB for each PD."""
    tcb = {}
    for pd in dep_graph:
        tcb[pd] = list(dep_graph[pd])
    return tcb


def compute_impact_boundary(dep_or_tcb, all_pds):
    """Compute impact boundary for each PD.

    Impact boundary of X = set of all Y where X is in TCB(Y).
    """
    impact = defaultdict(set)
    for pd in all_pds:
        for other in dep_or_tcb.get(pd, []):
            impact[other].add(pd)

    result = {}
    for pd in all_pds:
        result[pd] = sorted(impact.get(pd, set()))
    return result


def compute_shared_resources(pds):
    """Classify shared memory regions into writers and readers."""
    region_to_pds = defaultdict(lambda: {"writers": set(), "readers": set()})

    for pd_name, pd_info in pds.items():
        for m in pd_info["maps"]:
            if "w" in m["perms"]:
                region_to_pds[m["mr"]]["writers"].add(pd_name)
            else:
                region_to_pds[m["mr"]]["readers"].add(pd_name)

    shared = {}
    for region, info in region_to_pds.items():
        all_mappers = info["writers"] | info["readers"]
        if len(all_mappers) >= 2:
            shared[region] = {
                "writers": sorted(info["writers"]),
                "readers": sorted(info["readers"]),
            }

    return shared


def check_policy(policy_path, tcb, impact):
    """Check security policy constraints."""
    with open(policy_path) as f:
        policy = json.load(f)

    violations = {
        "isolation_violations": [],
        "tcb_size_violations": [],
        "impact_size_violations": [],
    }

    for pair in policy.get("isolated_pairs", []):
        a, b = sorted(pair)
        a_in_tcb_b = a in tcb.get(b, [])
        b_in_tcb_a = b in tcb.get(a, [])
        if a_in_tcb_b or b_in_tcb_a:
            violations["isolation_violations"].append({
                "pair": [a, b],
                "first_in_tcb_of_second": a_in_tcb_b,
                "second_in_tcb_of_first": b_in_tcb_a,
            })

    violations["isolation_violations"].sort(key=lambda x: x["pair"])

    for pd, max_size in sorted(policy.get("max_tcb_size", {}).items()):
        actual = len(tcb.get(pd, []))
        if actual > max_size:
            violations["tcb_size_violations"].append({
                "pd": pd,
                "actual_size": actual,
                "max_allowed": max_size,
            })

    for pd, max_size in sorted(policy.get("max_impact_size", {}).items()):
        actual = len(impact.get(pd, []))
        if actual > max_size:
            violations["impact_size_violations"].append({
                "pd": pd,
                "actual_size": actual,
                "max_allowed": max_size,
            })

    return violations


def main():
    system_xml = "/app/system.xml"
    policy_json = "/app/policy.json"
    report_json = "/app/report.json"

    memory_regions, pds, channels, parent_child = parse_system(system_xml)
    all_pd_names = sorted(pds.keys())

    dep_graph = build_dependency_graph(pds, channels, parent_child)
    tcb = compute_tcb(dep_graph)
    impact = compute_impact_boundary(dep_graph, all_pd_names)
    shared = compute_shared_resources(pds)
    violations = check_policy(policy_json, tcb, impact)

    report = {
        "protection_domains": all_pd_names,
        "dependency_graph": dep_graph,
        "tcb": tcb,
        "impact_boundary": impact,
        "shared_resources": dict(sorted(shared.items())),
        "policy_violations": violations,
    }

    with open(report_json, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {report_json}")


if __name__ == "__main__":
    main()
