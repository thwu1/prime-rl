#!/usr/bin/env python3
"""
PKGBUILD repository auditor.
Uses provided tools: /app/tools/pkgsource, /app/tools/vercmp, /app/registry.db
"""

import json
import os
import re
import sqlite3
import subprocess
from collections import defaultdict


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------

def run_pkgsource(pkgbuild_path, split_pkg=None):
    """Run pkgsource tool to parse a PKGBUILD."""
    cmd = ["/app/tools/pkgsource", pkgbuild_path]
    if split_pkg:
        cmd.append(split_pkg)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None


def run_vercmp(v1, v2):
    """Run vercmp tool to compare two versions."""
    result = subprocess.run(
        ["/app/tools/vercmp", v1, v2],
        capture_output=True, text=True,
    )
    return int(result.stdout.strip())


def load_registry(db_path="/app/registry.db"):
    """Load external packages from the SQLite registry database."""
    conn = sqlite3.connect(db_path)
    packages = {}
    for row in conn.execute("SELECT name, version, provides FROM packages"):
        packages[row[0]] = {
            "version": row[1],
            "provides": json.loads(row[2]) if row[2] else [],
        }
    conn.close()
    return packages


# ---------------------------------------------------------------------------
# Version constraint checking (uses vercmp tool)
# ---------------------------------------------------------------------------

def check_constraint(dep, actual_ver):
    """Return True if actual_ver satisfies the version constraint in dep."""
    m = re.match(r"^(.+?)(>=|<=|>|<|=)(.+)$", dep)
    if not m:
        return True
    _, op, req = m.groups()
    c = run_vercmp(actual_ver, req)
    return {
        ">=": c >= 0,
        "<=": c <= 0,
        ">": c > 0,
        "<": c < 0,
        "=": c == 0,
    }[op]


# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def find_cycles(graph):
    """Return list of cycles (each cycle = list of nodes) via DFS."""
    visited, rec_stack = set(), set()
    cycles = []

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for nb in sorted(graph.get(node, set())):
            if nb not in visited:
                dfs(nb, path)
            elif nb in rec_stack:
                idx = path.index(nb)
                cycle = list(path[idx:])
                mn = min(cycle)
                mi = cycle.index(mn)
                norm = cycle[mi:] + cycle[:mi]
                if norm not in cycles:
                    cycles.append(norm)
        path.pop()
        rec_stack.discard(node)

    for n in sorted(graph):
        if n not in visited:
            dfs(n, [])
    return cycles


def topo_sort(graph, nodes):
    """Kahn's algorithm with deterministic (sorted) tie-breaking."""
    in_deg = {n: 0 for n in nodes}
    dependents = defaultdict(set)
    for n in nodes:
        for dep in graph.get(n, set()):
            if dep in nodes:
                in_deg[n] += 1
                dependents[dep].add(n)

    queue = sorted(n for n in nodes if in_deg[n] == 0)
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for dep in sorted(dependents.get(node, set())):
            in_deg[dep] -= 1
            if in_deg[dep] == 0:
                queue.append(dep)
        queue.sort()
    return result


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def main():
    repo_dir = "/app/repo"
    registry = load_registry()
    available = set(registry.keys())

    # Parse all PKGBUILDs using pkgsource
    all_pkgs = {}
    pkgbases = defaultdict(list)

    for entry in sorted(os.listdir(repo_dir)):
        pb = os.path.join(repo_dir, entry, "PKGBUILD")
        if not os.path.isfile(pb):
            continue

        # Get global metadata (includes pkgname list and package functions)
        global_meta = run_pkgsource(pb)
        if not global_meta:
            continue

        pkgbase = global_meta["pkgbase"]
        pkg_names = global_meta["pkgname"]
        if isinstance(pkg_names, str):
            pkg_names = [pkg_names]

        pkgver = global_meta["pkgver"]
        pkgrel = global_meta["pkgrel"]
        epoch = global_meta.get("epoch", "0")

        version = f"{pkgver}-{pkgrel}"
        if epoch and str(epoch) != "0":
            version = f"{epoch}:{version}"

        # For each package, get per-function metadata via pkgsource
        for pkg_name in pkg_names:
            pkg_meta = run_pkgsource(pb, pkg_name)
            if pkg_meta:
                all_pkgs[pkg_name] = {
                    "pkgbase": pkgbase,
                    "version": version,
                    "depends": pkg_meta.get("depends", []),
                    "makedepends": pkg_meta.get("makedepends",
                                                global_meta.get("makedepends", [])),
                    "provides": pkg_meta.get("provides", []),
                    "conflicts": pkg_meta.get("conflicts", []),
                }
            else:
                all_pkgs[pkg_name] = {
                    "pkgbase": pkgbase,
                    "version": version,
                    "depends": global_meta.get("depends", []),
                    "makedepends": global_meta.get("makedepends", []),
                    "provides": global_meta.get("provides", []),
                    "conflicts": global_meta.get("conflicts", []),
                }
            pkgbases[pkgbase].append(pkg_name)

    # Build provides map: provided_name -> [(provider_pkg, version)]
    provides_map = {}
    for name, meta in all_pkgs.items():
        provides_map.setdefault(name, []).append((name, meta["version"]))
        for p in meta.get("provides", []):
            m = re.match(r"^([^><=]+)(?:=(.+))?$", p)
            pname = m.group(1)
            pver = m.group(2) or meta["version"]
            provides_map.setdefault(pname, []).append((name, pver))

    issues = []

    # 1. Missing dependencies
    for name, meta in sorted(all_pkgs.items()):
        for dep in meta.get("depends", []) + meta.get("makedepends", []):
            dep_name = re.split(r"[><=]", dep)[0]
            if dep_name not in provides_map and dep_name not in available:
                issues.append({
                    "type": "missing_dependency",
                    "package": name,
                    "missing": dep_name,
                })

    # 2. Version constraint violations (internal + external)
    for name, meta in sorted(all_pkgs.items()):
        for dep in meta.get("depends", []) + meta.get("makedepends", []):
            m = re.match(r"^(.+?)(>=|<=|>|<|=)(.+)$", dep)
            if not m:
                continue
            dep_name = m.group(1)
            # Check against internal packages
            if dep_name in provides_map:
                satisfied = any(
                    check_constraint(dep, pver)
                    for _, pver in provides_map[dep_name]
                )
                if not satisfied:
                    actual = provides_map[dep_name][0][1]
                    issues.append({
                        "type": "version_constraint_violation",
                        "package": name,
                        "dependency": dep,
                        "actual_version": actual,
                    })
            # Check against external registry
            elif dep_name in registry:
                reg_ver = registry[dep_name]["version"]
                if not check_constraint(dep, reg_ver):
                    issues.append({
                        "type": "version_constraint_violation",
                        "package": name,
                        "dependency": dep,
                        "actual_version": reg_ver,
                    })

    # 3. Conflicting provides (same name from different pkgbases)
    seen_conflicts = set()
    for prov_name, providers in provides_map.items():
        provider_pkgs = [p for p, _ in providers if p in all_pkgs]
        bases = set(all_pkgs[p]["pkgbase"] for p in provider_pkgs)
        if len(bases) > 1 and prov_name not in seen_conflicts:
            seen_conflicts.add(prov_name)
            issues.append({
                "type": "conflicting_provides",
                "packages": sorted(provider_pkgs),
                "provides": prov_name,
            })

    # 4. Build pkgbase-level dependency graph
    base_deps = defaultdict(set)
    for base, pkg_names in pkgbases.items():
        for pn in pkg_names:
            meta = all_pkgs[pn]
            for dep in meta.get("depends", []) + meta.get("makedepends", []):
                dep_name = re.split(r"[><=]", dep)[0]
                if dep_name in provides_map:
                    for provider, _ in provides_map[dep_name]:
                        if provider in all_pkgs:
                            dep_base = all_pkgs[provider]["pkgbase"]
                            if dep_base != base:
                                base_deps[base].add(dep_base)

    # 5. Cycle detection
    cycles = find_cycles(base_deps)
    for cycle in cycles:
        issues.append({"type": "circular_dependency", "cycle": cycle})

    # 6. Build order (exclude circular pkgbases)
    circular = set()
    for c in cycles:
        circular.update(c)
    acyclic = set(pkgbases.keys()) - circular
    build_order = topo_sort(base_deps, acyclic)

    # Write report
    report = {
        "packages": all_pkgs,
        "issues": issues,
        "build_order": build_order,
    }
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {len(all_pkgs)} packages, {len(issues)} issues, "
          f"build order: {' -> '.join(build_order)}")


if __name__ == "__main__":
    main()
