#!/usr/bin/env python3

"""
Corrected isolation analyzer for seL4 Microkit system descriptions.

Fixes applied:
1. Shared memory dependencies are directional based on write permissions.
   All PDs mapping a region depend on any PD that has write access to that
   region (mapper depends on writer), rather than all mappers depending on
   all other mappers bidirectionally.
2. TCB computation uses BFS transitive closure, not just direct dependencies.
3. Impact boundary computation uses the transitive TCB, not the direct
   dependency graph.
4. FINDING-4 from the cert report is INCORRECT — sensor depends on control
   via a channel (not just memory), so the bidirectional dep is correct.
   No changes made for FINDING-4.

Additional outputs:
- Graphviz DOT file of the direct dependency graph
- SVG rendering via dot CLI
- Critical paths JSON for isolation violations
"""

import json
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict, deque


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

    X depends on Y (edge X -> Y) if:
    1. Y has write access to a memory region R that X also maps
    2. There is a channel between X and Y (bidirectional)
    3. Y is the parent of X (child depends on parent)
    """
    all_pd_names = sorted(pds.keys())
    deps = defaultdict(set)

    # Rule 1: Shared memory write exposure (DIRECTIONAL)
    # All PDs mapping a region depend on PDs that have WRITE access to it
    region_to_pds = defaultdict(list)
    for pd_name, pd_info in pds.items():
        for m in pd_info["maps"]:
            has_write = "w" in m["perms"]
            region_to_pds[m["mr"]].append((pd_name, has_write))

    for region, pd_list in region_to_pds.items():
        writers = [pd for pd, hw in pd_list if hw]
        all_mappers = [pd for pd, _ in pd_list]

        for writer in writers:
            for mapper in all_mappers:
                if mapper != writer:
                    deps[mapper].add(writer)

    # Rule 2: Channel communication (bidirectional)
    for pd_a, pd_b in channels:
        deps[pd_a].add(pd_b)
        deps[pd_b].add(pd_a)

    # Rule 3: Parent-child (child depends on parent)
    for child, parent in parent_child:
        deps[child].add(parent)

    dep_graph = {}
    for pd in all_pd_names:
        dep_graph[pd] = sorted(deps[pd] - {pd})

    return dep_graph


def compute_tcb(dep_graph):
    """Compute the TCB for each PD via BFS transitive closure."""
    tcb = {}
    for pd in dep_graph:
        visited = set()
        queue = deque(dep_graph[pd])
        for dep in dep_graph[pd]:
            visited.add(dep)

        while queue:
            current = queue.popleft()
            for next_dep in dep_graph.get(current, []):
                if next_dep != pd and next_dep not in visited:
                    visited.add(next_dep)
                    queue.append(next_dep)

        tcb[pd] = sorted(visited)
    return tcb


def compute_impact_boundary(tcb, all_pds):
    """Compute impact boundary for each PD.

    Impact boundary of X = set of all Y where X is in TCB(Y).
    """
    impact = defaultdict(set)
    for pd in all_pds:
        for other in tcb.get(pd, []):
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


def generate_dot(dep_graph, output_path):
    """Generate a Graphviz DOT file of the direct dependency graph."""
    with open(output_path, "w") as f:
        f.write("digraph dependencies {\n")
        for pd in sorted(dep_graph.keys()):
            for dep in dep_graph[pd]:
                f.write(f'    "{pd}" -> "{dep}"\n')
        f.write("}\n")


def generate_svg(dot_path, svg_path):
    """Render the DOT graph to SVG using the dot CLI tool."""
    subprocess.run(
        ["dot", "-Tsvg", dot_path, "-o", svg_path],
        check=True
    )


def find_shortest_path(dep_graph, start, end):
    """BFS shortest path in the dependency graph."""
    if start == end:
        return [start]
    visited = {start}
    queue = deque([(start, [start])])
    while queue:
        current, path = queue.popleft()
        for neighbor in dep_graph.get(current, []):
            if neighbor == end:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return None


def generate_critical_paths(dep_graph, violations, output_path):
    """Generate critical dependency chains for isolation violations."""
    entries = []
    for v in violations["isolation_violations"]:
        pair = v["pair"]  # [a, b] sorted alphabetically
        a, b = pair
        if v["first_in_tcb_of_second"]:
            # a is in TCB of b, meaning b transitively depends on a
            # Path from b to a following dependency edges
            path = find_shortest_path(dep_graph, b, a)
            if path:
                entries.append({"pair": pair, "path": path})
        if v["second_in_tcb_of_first"]:
            # b is in TCB of a, meaning a transitively depends on b
            # Path from a to b following dependency edges
            path = find_shortest_path(dep_graph, a, b)
            if path:
                entries.append({"pair": pair, "path": path})

    entries.sort(key=lambda x: x["pair"])

    result = {"isolation_violation_paths": entries}
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)


def main():
    system_xml = "/app/system.xml"
    policy_json = "/app/policy.json"
    report_json = "/app/report.json"
    dot_path = "/app/dependency_graph.dot"
    svg_path = "/app/dependency_graph.svg"
    critical_paths_path = "/app/critical_paths.json"

    memory_regions, pds, channels, parent_child = parse_system(system_xml)
    all_pd_names = sorted(pds.keys())

    dep_graph = build_dependency_graph(pds, channels, parent_child)
    tcb = compute_tcb(dep_graph)
    impact = compute_impact_boundary(tcb, all_pd_names)
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

    generate_dot(dep_graph, dot_path)
    generate_svg(dot_path, svg_path)
    generate_critical_paths(dep_graph, violations, critical_paths_path)

    print(f"Report written to {report_json}")
    print(f"DOT graph written to {dot_path}")
    print(f"SVG graph written to {svg_path}")
    print(f"Critical paths written to {critical_paths_path}")


if __name__ == "__main__":
    main()
