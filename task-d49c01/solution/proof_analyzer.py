#!/usr/bin/env python3
"""
Formal Verification Proof Structure Analyzer.
Multi-tool pipeline: tclsh -> python -> graphviz dot
"""

import json
import os
import re
import subprocess
from collections import defaultdict


# ==================== TCL State Resolution ====================


def resolve_design_states():
    """Evaluate jg_states.tcl with tclsh to produce resolved design states."""
    outpath = "/app/design_states_resolved.json"
    result = subprocess.run(
        ["tclsh", "/app/jg_states.tcl", outpath],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tclsh evaluation failed: {result.stderr}")

    with open(outpath) as f:
        return json.load(f)


# ==================== Input Loading ====================


def load_inputs():
    with open("/app/design_hierarchy.json") as f:
        hierarchy = json.load(f)
    with open("/app/properties.json") as f:
        properties = json.load(f)
    with open("/app/proof_structure.json") as f:
        proof_struct = json.load(f)
    return hierarchy, properties, proof_struct


# ==================== Assume-Guarantee Analysis ====================


def build_guarantee_to_node_map(proof_nodes):
    """Map each guarantee ID to the node that provides it."""
    g2n = {}
    for node in proof_nodes:
        if node["strategy"] == "assume_guarantee":
            for g in node.get("guarantees", []):
                g2n[g["id"]] = node["id"]
    return g2n


def build_ag_dependency_graph(proof_nodes, g2n):
    """Build node -> [dependency nodes] based on assumption->guarantee links."""
    dep_graph = {}
    for node in proof_nodes:
        if node["strategy"] != "assume_guarantee":
            continue
        deps = set()
        for a in node.get("assumptions", []):
            gid = a.get("depends_on_guarantee")
            if gid and gid in g2n:
                deps.add(g2n[gid])
        dep_graph[node["id"]] = sorted(deps)
    return dep_graph


def tarjan_scc(graph):
    """Tarjan's algorithm for strongly connected components."""
    index_counter = [0]
    stack = []
    on_stack = set()
    index = {}
    lowlink = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in graph.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            result.append(sorted(component))

    for v in sorted(graph.keys()):
        if v not in index:
            strongconnect(v)

    return result


def find_cycles(dep_graph):
    """Find SCCs representing cycles (size >= 2 or self-referential)."""
    sccs = tarjan_scc(dep_graph)
    cycles = []
    for scc in sccs:
        if len(scc) >= 2:
            cycles.append(scc)
        elif len(scc) == 1:
            node = scc[0]
            if node in dep_graph.get(node, []):
                cycles.append(scc)
    cycles.sort(key=lambda c: c[0])
    return cycles


def analyze_assume_guarantee(proof_nodes):
    g2n = build_guarantee_to_node_map(proof_nodes)
    dep_graph = build_ag_dependency_graph(proof_nodes, g2n)
    cycles = find_cycles(dep_graph)
    return {"dependency_graph": dep_graph, "cycles": cycles}


# ==================== Case Split Analysis ====================


def extract_enum_values_from_condition(condition):
    return re.findall(r'(\w+\.\w+)\s*==\s*(\w+)', condition)


def analyze_case_splits(proof_nodes, design_states):
    result = {}
    for node in proof_nodes:
        if node["strategy"] != "case_split":
            continue
        nid = node["id"]
        var_values = defaultdict(set)
        for case in node["cases"]:
            pairs = extract_enum_values_from_condition(case["condition"])
            for var, val in pairs:
                var_values[var].add(val)

        primary_var = None
        for var in var_values:
            if var in design_states:
                primary_var = var
                break

        if primary_var is None:
            result[nid] = {
                "complete": True, "state_variable": None,
                "covered_values": [], "missing_values": [],
            }
            continue

        all_values = set(design_states[primary_var])
        covered = var_values[primary_var]
        missing = all_values - covered
        result[nid] = {
            "complete": len(missing) == 0,
            "state_variable": primary_var,
            "covered_values": sorted(covered),
            "missing_values": sorted(missing),
        }
    return result


# ==================== Stopat Analysis ====================


def analyze_stopat(proof_nodes, modules):
    result = {}
    for node in proof_nodes:
        if node["strategy"] != "stopat":
            continue
        nid = node["id"]
        errors = []
        scope_module = node["module_scope"][0]
        for sm in node["stopat_modules"]:
            if sm not in modules:
                errors.append(
                    f"Module '{sm}' does not exist in design hierarchy"
                )
            else:
                children = modules.get(scope_module, {}).get("children", [])
                if sm not in children:
                    errors.append(
                        f"Module '{sm}' is not a child of '{scope_module}'"
                    )
        result[nid] = {"valid": len(errors) == 0, "errors": errors}
    return result


# ==================== Edit Node Analysis ====================


def analyze_edit_nodes(proof_nodes):
    node_ids = {n["id"] for n in proof_nodes}
    result = {}
    for node in proof_nodes:
        if node["strategy"] != "edit_node":
            continue
        nid = node["id"]
        errors = []
        base = node.get("base_node")
        if base is not None and base not in node_ids:
            errors.append(
                f"Base node '{base}' does not exist in proof structure"
            )
        result[nid] = {"valid": len(errors) == 0, "errors": errors}
    return result


# ==================== Cone of Influence ====================


def compute_coi(signals_referenced, signal_deps):
    """Compute transitive closure of signal dependencies."""
    visited = set()
    queue = list(signals_referenced)
    while queue:
        sig = queue.pop()
        if sig in visited:
            continue
        visited.add(sig)
        for dep in signal_deps.get(sig, []):
            if dep not in visited:
                queue.append(dep)
    return sorted(visited)


def analyze_coi(properties, signal_deps):
    result = {}
    for prop in properties:
        result[prop["id"]] = compute_coi(prop["signals_referenced"], signal_deps)
    return result


# ==================== Abstraction Soundness ====================


def analyze_abstraction_soundness(proof_nodes, modules, coi_results):
    """Check if stopat abstractions compromise proof by cutting COI signals."""
    result = {}
    for node in proof_nodes:
        if node["strategy"] != "stopat":
            continue
        nid = node["id"]

        # Gather COI for all target properties of this node
        target_coi = set()
        for pid in node["target_properties"]:
            if pid in coi_results:
                target_coi.update(coi_results[pid])

        # Check which stopat modules exist and which have signals in COI
        compromised = set()
        missing = []
        for sm in node["stopat_modules"]:
            if sm not in modules:
                missing.append(sm)
            else:
                prefix = sm + "."
                for sig in target_coi:
                    if sig.startswith(prefix):
                        compromised.add(sig)

        sound = len(missing) == 0 and len(compromised) == 0
        result[nid] = {
            "sound": sound,
            "compromised_signals": sorted(compromised),
            "missing_modules": sorted(missing),
        }
    return result


# ==================== Proof Coverage ====================


def analyze_proof_coverage(proof_nodes, all_properties, schedule):
    """Determine which properties have valid proof paths."""
    schedulable = set(schedule["schedulable"])
    covered = set()

    for node in proof_nodes:
        if node["id"] not in schedulable:
            continue
        # Direct target properties
        covered.update(node["target_properties"])
        # Partition sub-properties
        if node["strategy"] == "partition":
            for part in node.get("partitions", []):
                covered.update(part.get("sub_properties", []))

    all_pids = sorted(p["id"] for p in all_properties)
    uncovered = sorted(set(all_pids) - covered)
    ratio = len(covered) / len(all_pids) if all_pids else 0.0

    return {
        "covered": sorted(covered),
        "uncovered": uncovered,
        "coverage_ratio": round(ratio, 4),
    }


# ==================== Execution Schedule ====================


def analyze_execution_schedule(proof_nodes, ag_analysis, stopat_analysis,
                               edit_node_analysis):
    cycles = ag_analysis["cycles"]
    dep_graph = ag_analysis["dependency_graph"]

    cyclic_nodes = set()
    for cycle in cycles:
        cyclic_nodes.update(cycle)

    invalid_nodes = set()
    for nid, sa in stopat_analysis.items():
        if not sa["valid"]:
            invalid_nodes.add(nid)
    for nid, en in edit_node_analysis.items():
        if not en["valid"]:
            invalid_nodes.add(nid)

    blocked_nodes = set()
    for nid, deps in dep_graph.items():
        if nid in cyclic_nodes or nid in invalid_nodes:
            continue
        for dep in deps:
            if dep in cyclic_nodes or dep in invalid_nodes:
                blocked_nodes.add(nid)
                break

    all_node_ids = {n["id"] for n in proof_nodes}
    schedulable = all_node_ids - cyclic_nodes - invalid_nodes - blocked_nodes

    return {
        "schedulable": sorted(schedulable),
        "cyclic": sorted(cyclic_nodes),
        "invalid": sorted(invalid_nodes),
        "blocked": sorted(blocked_nodes),
    }


# ==================== DOT Graph Generation ====================


def generate_dot(proof_nodes, ag_analysis, schedule, g2n_map):
    """Generate Graphviz DOT digraph and render SVG."""
    dep_graph = ag_analysis["dependency_graph"]

    status_colors = {
        "schedulable": "#4CAF50",
        "cyclic": "#F44336",
        "invalid": "#FF9800",
        "blocked": "#9E9E9E",
    }
    strategy_shapes = {
        "assume_guarantee": "ellipse",
        "case_split": "box",
        "partition": "hexagon",
        "stopat": "diamond",
        "edit_node": "trapezium",
    }

    node_status = {}
    for cat in ["schedulable", "cyclic", "invalid", "blocked"]:
        for nid in schedule[cat]:
            node_status[nid] = cat

    lines = ["digraph proof_structure {"]
    lines.append('    rankdir=TB;')
    lines.append('    node [fontname="Helvetica" fontsize=10];')
    lines.append("")

    for node in sorted(proof_nodes, key=lambda n: n["id"]):
        nid = node["id"]
        strategy = node["strategy"]
        status = node_status.get(nid, "schedulable")
        shape = strategy_shapes.get(strategy, "ellipse")
        color = status_colors.get(status, "#FFFFFF")
        props = ",".join(node["target_properties"])
        label = f"{nid}\\n{strategy}\\n[{props}]"
        lines.append(
            f'    {nid} [label="{label}" shape={shape} '
            f'style=filled fillcolor="{color}"];'
        )

    lines.append("")

    for node in sorted(proof_nodes, key=lambda n: n["id"]):
        if node["strategy"] != "assume_guarantee":
            continue
        nid = node["id"]
        for assumption in node.get("assumptions", []):
            gid = assumption.get("depends_on_guarantee")
            if gid and gid in g2n_map:
                target = g2n_map[gid]
                lines.append(f'    {nid} -> {target} [label="{gid}"];')

    lines.append("}")

    dot_content = "\n".join(lines)
    with open("/app/proof_dependency.dot", "w") as f:
        f.write(dot_content)

    result = subprocess.run(
        ["dot", "-Tsvg", "/app/proof_dependency.dot",
         "-o", "/app/proof_dependency.svg"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"dot SVG rendering failed: {result.stderr}")


# ==================== Main ====================


def main():
    # Step 1: Resolve design states via tclsh
    design_states = resolve_design_states()

    # Step 2: Load remaining inputs
    hierarchy, properties_data, proof_struct = load_inputs()
    proof_nodes = proof_struct["proof_nodes"]
    modules = hierarchy["modules"]
    signal_deps = hierarchy["signal_dependencies"]
    props = properties_data["properties"]

    # Step 3: Core analyses
    ag_analysis = analyze_assume_guarantee(proof_nodes)
    cs_analysis = analyze_case_splits(proof_nodes, design_states)
    sa_analysis = analyze_stopat(proof_nodes, modules)
    en_analysis = analyze_edit_nodes(proof_nodes)
    coi = analyze_coi(props, signal_deps)
    schedule = analyze_execution_schedule(
        proof_nodes, ag_analysis, sa_analysis, en_analysis
    )

    # Step 4: Advanced analyses
    abs_soundness = analyze_abstraction_soundness(proof_nodes, modules, coi)
    proof_coverage = analyze_proof_coverage(proof_nodes, props, schedule)

    # Step 5: Generate DOT graph and SVG
    g2n = build_guarantee_to_node_map(proof_nodes)
    generate_dot(proof_nodes, ag_analysis, schedule, g2n)

    # Step 6: Write report
    report = {
        "assume_guarantee_analysis": ag_analysis,
        "case_split_analysis": cs_analysis,
        "stopat_analysis": sa_analysis,
        "edit_node_analysis": en_analysis,
        "coi": coi,
        "abstraction_soundness": abs_soundness,
        "proof_coverage": proof_coverage,
        "execution_schedule": schedule,
    }

    with open("/app/analysis_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Analysis complete. Report written to /app/analysis_report.json")
    print(f"DOT graph: /app/proof_dependency.dot")
    print(f"SVG rendering: /app/proof_dependency.svg")
    print(f"Design states: /app/design_states_resolved.json")


if __name__ == "__main__":
    main()
