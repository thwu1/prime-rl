#!/usr/bin/env python3
"""
dbt Pipeline Root Cause Analyzer.

Reads /data/manifest.json and /data/run_results.json, performs root cause analysis
on a failed dbt build run, and outputs /app/analysis.json with re-run strategy.

"""
import json
from collections import defaultdict, deque


def load_json(path):
    with open(path) as f:
        return json.load(f)


def build_children_map(manifest):
    """Build a children adjacency list from the manifest dependency graph."""
    children = defaultdict(list)
    for uid, node in manifest["nodes"].items():
        for dep in node.get("depends_on", {}).get("nodes", []):
            children[dep].append(uid)
    return children


def get_status_map(run_results):
    """Build unique_id -> status mapping from run results."""
    return {r["unique_id"]: r["status"] for r in run_results["results"]}


def find_root_causes(manifest, status_map):
    """
    Find nodes whose status is error/skipped but all upstream dependencies passed.
    These are the original points of failure.
    """
    failed_statuses = {"error", "skipped"}
    root_causes = []

    for uid, node in manifest["nodes"].items():
        status = status_map.get(uid, "pass")
        if status not in failed_statuses:
            continue

        upstream_deps = node.get("depends_on", {}).get("nodes", [])
        has_failed_upstream = any(
            status_map.get(dep, "pass") in failed_statuses for dep in upstream_deps
        )

        if not has_failed_upstream:
            root_causes.append(uid)

    return sorted(root_causes)


def compute_blast_radius(root_cause, children):
    """
    BFS from root_cause through the children map to find all transitive
    downstream nodes. Returns sorted list excluding the root cause itself.
    """
    visited = set()
    queue = deque()

    for child in children.get(root_cause, []):
        if child not in visited:
            visited.add(child)
            queue.append(child)

    while queue:
        node = queue.popleft()
        for child in children.get(node, []):
            if child not in visited:
                visited.add(child)
                queue.append(child)

    return sorted(visited)


def find_detached_tests(manifest):
    """
    Find all test nodes with more than one parent dependency.
    In Cosmos terminology these are 'detached' tests that run independently
    because they span multiple model boundaries.
    """
    detached = []
    for uid, node in manifest["nodes"].items():
        if node["resource_type"] == "test":
            deps = node.get("depends_on", {}).get("nodes", [])
            if len(deps) > 1:
                detached.append(uid)
    return sorted(detached)


def find_critical_path(root_causes, children, status_map, manifest):
    """
    Find the longest dependency chain starting from any root cause and
    traversing only through model nodes with status error or skipped.
    Uses DFS with backtracking.
    """
    failed_statuses = {"error", "skipped"}

    failed_models = set()
    for uid, node in manifest["nodes"].items():
        if (
            node["resource_type"] == "model"
            and status_map.get(uid, "pass") in failed_statuses
        ):
            failed_models.add(uid)

    best_path = []

    def dfs(node, path):
        nonlocal best_path
        if len(path) > len(best_path):
            best_path = list(path)

        for child in children.get(node, []):
            if child in failed_models and child not in path:
                path.append(child)
                dfs(child, path)
                path.pop()

    for rc in root_causes:
        if rc in failed_models:
            dfs(rc, [rc])

    return best_path


def generate_rerun_select(root_causes, manifest):
    """
    Generate a dbt --select expression to re-run root causes and all
    their downstream descendants using the + graph operator.
    """
    names = []
    for rc in sorted(root_causes):
        node = manifest["nodes"][rc]
        names.append(f"{node['name']}+")
    return " ".join(names)


def main():
    manifest = load_json("/data/manifest.json")
    run_results = load_json("/data/run_results.json")

    children = build_children_map(manifest)
    status_map = get_status_map(run_results)

    # 1. Identify root causes
    root_causes = find_root_causes(manifest, status_map)

    # 2. Compute blast radius for each root cause
    blast_radius = {}
    all_affected = set(root_causes)
    for rc in root_causes:
        downstream = compute_blast_radius(rc, children)
        blast_radius[rc] = downstream
        all_affected.update(downstream)

    # 3. Find detached (multi-parent) tests
    detached_tests = find_detached_tests(manifest)

    # 4. Find critical failure path
    critical_path = find_critical_path(root_causes, children, status_map, manifest)

    # 5. Generate re-run select expression
    rerun_select = generate_rerun_select(root_causes, manifest)

    analysis = {
        "root_causes": root_causes,
        "blast_radius": blast_radius,
        "total_affected": len(all_affected),
        "detached_tests": detached_tests,
        "critical_path_length": len(critical_path),
        "critical_path": critical_path,
        "rerun_select": rerun_select,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"Analysis complete. Root causes: {len(root_causes)}, "
          f"Total affected: {len(all_affected)}, "
          f"Critical path length: {len(critical_path)}")


if __name__ == "__main__":
    main()
