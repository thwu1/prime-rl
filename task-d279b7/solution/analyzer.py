#!/usr/bin/env python3
"""
Dioptra Experiment Graph Analyzer

Analyzes NIST Dioptra experiment YAML workflow definitions for dependency
structure, reference validity, and graph properties. Outputs a JSON report.
"""

import heapq
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml


def is_reference(s):
    """Check if a string is a $-reference (not $$-escaped)."""
    return isinstance(s, str) and s.startswith("$") and not s.startswith("$$")


def parse_reference(ref_str):
    """Parse '$name' or '$step.output' into (name, output_or_none)."""
    name = ref_str[1:]
    if "." in name:
        parts = name.split(".", 1)
        return parts[0], parts[1]
    return name, None


def extract_references(value):
    """Recursively find all $references in a value tree."""
    refs = []
    if isinstance(value, str):
        if is_reference(value):
            refs.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            refs.extend(extract_references(v))
    elif isinstance(value, list):
        for item in value:
            refs.extend(extract_references(item))
    return refs


def get_task_short_name(step_def):
    """Extract the task short name from a step definition."""
    if "task" in step_def:
        return step_def["task"]
    for key in step_def:
        if key != "dependencies":
            return key
    return None


def get_explicit_deps(step_def):
    """Extract explicit dependencies from a step definition."""
    deps = step_def.get("dependencies", [])
    if isinstance(deps, str):
        return [deps]
    return list(deps)


def get_step_param_refs(step_def):
    """Extract all $references from the parameter values of a step."""
    refs = []
    if "task" in step_def:
        # Mixed invocation
        if "args" in step_def:
            args = step_def["args"]
            if isinstance(args, list):
                for a in args:
                    refs.extend(extract_references(a))
            elif args is not None:
                refs.extend(extract_references(args))
        if "kwargs" in step_def:
            refs.extend(extract_references(step_def["kwargs"]))
    else:
        # Positional or keyword invocation
        for key, value in step_def.items():
            if key == "dependencies":
                continue
            refs.extend(extract_references(value))
    return refs


def get_task_output_names(task_def):
    """Get list of output names defined by a task."""
    outputs = task_def.get("outputs")
    if outputs is None:
        return []
    if isinstance(outputs, dict):
        return list(outputs.keys())
    elif isinstance(outputs, list):
        names = []
        for out in outputs:
            if isinstance(out, dict):
                names.extend(out.keys())
        return names
    return []


def detect_cycle(all_steps, successors):
    """DFS-based cycle detection. Returns cycle path list or None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s: WHITE for s in all_steps}

    def dfs(u, path):
        color[u] = GRAY
        path.append(u)
        for v in sorted(successors.get(u, set())):
            if color[v] == GRAY:
                idx = path.index(v)
                return path[idx:] + [v]
            elif color[v] == WHITE:
                result = dfs(v, path)
                if result:
                    return result
        path.pop()
        color[u] = BLACK
        return None

    for s in sorted(all_steps):
        if color[s] == WHITE:
            result = dfs(s, [])
            if result:
                return result
    return None


def topological_sort_kahn(all_steps, predecessors, successors):
    """Kahn's algorithm with alphabetical tie-breaking via min-heap."""
    in_degree = {s: len(predecessors.get(s, set())) for s in all_steps}
    heap = sorted([s for s in all_steps if in_degree[s] == 0])
    heapq.heapify(heap)

    order = []
    while heap:
        u = heapq.heappop(heap)
        order.append(u)
        for v in sorted(successors.get(u, set())):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                heapq.heappush(heap, v)
    return order


def compute_depths(predecessors, topo_order):
    """Compute depth (longest path from any root) for each step."""
    depths = {}
    for s in topo_order:
        preds = predecessors.get(s, set())
        if not preds:
            depths[s] = 0
        else:
            depths[s] = max(depths[p] for p in preds) + 1
    return depths


def find_critical_path(all_steps, predecessors, topo_order, depths):
    """Find the critical path through the DAG."""
    if not depths:
        return [], 0

    max_depth = max(depths.values())
    # Pick alphabetically first endpoint at max depth
    end_nodes = sorted([s for s in all_steps if depths[s] == max_depth])
    end = end_nodes[0]

    # Trace back from end node
    path = [end]
    current = end
    while depths[current] > 0:
        target_depth = depths[current] - 1
        preds = sorted(predecessors.get(current, set()))
        best = None
        for p in preds:
            if depths[p] == target_depth:
                best = p
                break
        if best is None:
            break
        path.append(best)
        current = best

    path.reverse()
    return path, len(path)


def analyze(yaml_path):
    """Perform full analysis of a Dioptra experiment YAML file."""
    with open(yaml_path) as f:
        experiment = yaml.safe_load(f)

    tasks = experiment.get("tasks", {})
    graph = experiment.get("graph", {})
    parameters = experiment.get("parameters", {})
    all_steps = set(graph.keys())

    # Build DAG: successors[u] = set of v where u→v (v depends on u)
    successors = defaultdict(set)
    predecessors = defaultdict(set)

    issues = []
    global_params_used = set()

    for step_name, step_def in graph.items():
        # Check explicit dependencies
        for dep in get_explicit_deps(step_def):
            if dep in all_steps:
                successors[dep].add(step_name)
                predecessors[step_name].add(dep)

        # Check task exists
        task_name = get_task_short_name(step_def)
        if task_name and task_name not in tasks:
            issues.append({
                "type": "undefined_task",
                "step": step_name,
                "task": task_name,
                "severity": "error",
                "message": (
                    f"Step '{step_name}' references undefined task "
                    f"'{task_name}'"
                ),
            })

        # Extract and classify references
        refs = get_step_param_refs(step_def)
        for ref_str in refs:
            ref_name, output_name = parse_reference(ref_str)

            if ref_name in parameters:
                global_params_used.add(ref_name)
            elif ref_name in all_steps:
                # Implicit dependency
                successors[ref_name].add(step_name)
                predecessors[step_name].add(ref_name)

                # Validate output name if dotted reference
                if output_name:
                    ref_step_def = graph[ref_name]
                    ref_task_name = get_task_short_name(ref_step_def)
                    if ref_task_name and ref_task_name in tasks:
                        task_outputs = get_task_output_names(
                            tasks[ref_task_name]
                        )
                        if task_outputs and output_name not in task_outputs:
                            issues.append({
                                "type": "invalid_output_reference",
                                "step": step_name,
                                "reference": ref_str,
                                "referenced_step": ref_name,
                                "task": ref_task_name,
                                "available_outputs": task_outputs,
                                "severity": "error",
                                "message": (
                                    f"Step '{step_name}' references output "
                                    f"'{output_name}' of step '{ref_name}' "
                                    f"(task '{ref_task_name}'), but available "
                                    f"outputs are: {task_outputs}"
                                ),
                            })
            else:
                issues.append({
                    "type": "unresolvable_reference",
                    "step": step_name,
                    "reference": ref_str,
                    "severity": "error",
                    "message": (
                        f"Step '{step_name}' has unresolvable reference "
                        f"'{ref_str}'"
                    ),
                })

    # Unused parameters
    unused_params = sorted(set(parameters.keys()) - global_params_used)
    for p in unused_params:
        issues.append({
            "type": "unused_parameter",
            "parameter": p,
            "severity": "warning",
            "message": f"Parameter '{p}' is defined but never referenced",
        })

    # Count unique edges
    edges = set()
    for u in successors:
        for v in successors[u]:
            edges.add((u, v))
    num_edges = len(edges)

    # Cycle detection
    cycle_path = detect_cycle(all_steps, successors)
    has_cycle = cycle_path is not None

    if has_cycle:
        issues.insert(0, {
            "type": "cycle",
            "cycle_path": cycle_path,
            "severity": "error",
            "message": f"Cycle detected: {' -> '.join(cycle_path)}",
        })

    # Graph metrics (only for acyclic graphs)
    topo_order = None
    critical_path_list = None
    critical_path_cost = None
    max_par = None
    step_depths = None

    if not has_cycle:
        topo_order = topological_sort_kahn(
            all_steps, predecessors, successors
        )
        step_depths = compute_depths(predecessors, topo_order)
        critical_path_list, critical_path_cost = find_critical_path(
            all_steps, predecessors, topo_order, step_depths
        )
        depth_counts = Counter(step_depths.values())
        max_par = max(depth_counts.values()) if depth_counts else 0

    return {
        "file": str(yaml_path),
        "num_steps": len(all_steps),
        "num_edges": num_edges,
        "has_cycle": has_cycle,
        "cycle_path": cycle_path,
        "topological_order": topo_order,
        "critical_path": critical_path_list,
        "critical_path_cost": critical_path_cost,
        "max_parallelism": max_par,
        "step_depths": step_depths,
        "global_params_used": sorted(global_params_used),
        "unused_params": unused_params,
        "issues": issues,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <experiment.yaml>", file=sys.stderr)
        sys.exit(1)

    result = analyze(sys.argv[1])
    print(json.dumps(result, indent=2))
