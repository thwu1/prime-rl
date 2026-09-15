#!/usr/bin/env python3
"""Package dependency resolver.

Reads a package registry and a manifest file, resolves dependencies, and outputs
a lockfile mapping package names to resolved versions.
"""

import json
import sys
import re
import argparse


def parse_version(v):
    return tuple(int(x) for x in v.strip().split("."))


def matches_constraint(version_str, constraint):
    """Check if a version string satisfies a version constraint."""
    v = parse_version(version_str) if isinstance(version_str, str) else version_str
    constraint = constraint.strip()

    if constraint.startswith("^"):
        base = parse_version(constraint[1:])
        if base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        return base <= v < upper

    if constraint.startswith("~"):
        base = parse_version(constraint[1:])
        if base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        return base <= v < upper

    parts = re.findall(r"(>=|<=|>|<)\s*(\d+\.\d+\.\d+)", constraint)
    if not parts:
        return v == parse_version(constraint)
    for op, ver_str in parts:
        target = parse_version(ver_str)
        if op == ">=" and not (v >= target):
            return False
        if op == "<" and not (v < target):
            return False
        if op == "<=" and not (v <= target):
            return False
        if op == ">" and not (v > target):
            return False
    return True


def find_matching(constraint, available_versions):
    """Return versions that satisfy the constraint."""
    return [v for v in available_versions if matches_constraint(v, constraint)]


def collect_relevant(registry, root_deps):
    """BFS from root deps to find all transitively relevant packages."""
    packages = registry["packages"]
    relevant = set()
    queue = list(root_deps.keys())
    while queue:
        pkg = queue.pop(0)
        if pkg in relevant:
            continue
        if pkg not in packages:
            continue
        relevant.add(pkg)
        for ver_data in packages[pkg].values():
            for dep in ver_data.get("dependencies", {}):
                if dep not in relevant:
                    queue.append(dep)
    return relevant


def build_formula(registry, manifest):
    """Build a CNF formula encoding the dependency resolution problem.

    Returns (num_vars, clauses, var_map, reverse_map) where:
      var_map:     (pkg, ver_str) -> positive int
      reverse_map: positive int   -> (pkg, ver_str)
      clauses:     list of lists of signed ints
    """
    packages = registry["packages"]
    root_deps = manifest["dependencies"]
    relevant = collect_relevant(registry, root_deps)

    var_map = {}
    reverse_map = {}
    var_id = 1
    for pkg in sorted(relevant):
        for ver in sorted(packages[pkg].keys(), key=parse_version):
            var_map[(pkg, ver)] = var_id
            reverse_map[var_id] = (pkg, ver)
            var_id += 1
    num_vars = var_id - 1

    clauses = []

    # At least one matching version of each root dependency must be selected
    for pkg, constraint in root_deps.items():
        if pkg not in packages:
            return num_vars, [[1], [-1]], var_map, reverse_map
        versions = sorted(packages[pkg].keys(), key=parse_version)
        matching = find_matching(constraint, versions)
        if not matching:
            return num_vars, [[1], [-1]], var_map, reverse_map
        clauses.append([var_map[(pkg, v)] for v in matching])

    # If a version is selected, its dependencies must be satisfied
    for pkg in relevant:
        for ver, data in packages[pkg].items():
            src = var_map[(pkg, ver)]
            for dep_pkg, dep_constraint in data.get("dependencies", {}).items():
                if dep_pkg not in packages:
                    clauses.append([-src])
                    continue
                dep_versions = sorted(
                    packages[dep_pkg].keys(), key=parse_version
                )
                matching = find_matching(dep_constraint, dep_versions)
                if not matching:
                    clauses.append([-src])
                else:
                    clauses.append(
                        [-src] + [var_map[(dep_pkg, v)] for v in matching]
                    )

    return num_vars, clauses, var_map, reverse_map


def brute_force_solve(num_vars, clauses):
    """SAT solver: exhaustively enumerates all 2^N variable assignments.

    Returns a dict mapping variable IDs to True/False, or None if UNSAT.
    """
    for i in range(2 ** num_vars):
        assignment = {}
        for v in range(1, num_vars + 1):
            assignment[v] = bool((i >> (v - 1)) & 1)

        all_satisfied = True
        for clause in clauses:
            clause_satisfied = False
            for lit in clause:
                var = abs(lit)
                if (lit > 0) == assignment.get(var, False):
                    clause_satisfied = True
                    break
            if not clause_satisfied:
                all_satisfied = False
                break

        if all_satisfied:
            return assignment
    return None


def to_dimacs(num_vars, clauses, reverse_map):
    """Return a DIMACS CNF string."""
    lines = []
    for vid in sorted(reverse_map):
        pkg, ver = reverse_map[vid]
        lines.append(f"c var {vid} {pkg}@{ver}")

    lines.append(f"p cnf {num_vars} {len(clauses)}")
    for clause in clauses:
        lines.append(" ".join(str(l) for l in clause) + " 0")

    return "\n".join(lines) + "\n"


def resolve(registry, manifest):
    """Resolve dependencies and return a lockfile dict, or None."""
    num_vars, clauses, var_map, reverse_map = build_formula(
        registry, manifest
    )
    assignment = brute_force_solve(num_vars, clauses)
    if assignment is None:
        return None

    lockfile = {}
    for (pkg, ver), vid in var_map.items():
        if assignment.get(vid, False):
            lockfile[pkg] = ver
    return lockfile


def main():
    parser = argparse.ArgumentParser(
        description="Package dependency resolver"
    )
    parser.add_argument("manifest", help="Path to manifest JSON file")
    parser.add_argument(
        "--dimacs",
        action="store_true",
        help="Output DIMACS CNF instead of resolving",
    )
    parser.add_argument(
        "--registry",
        default="/app/registry.json",
        help="Path to package registry JSON",
    )
    args = parser.parse_args()

    with open(args.registry) as f:
        registry = json.load(f)
    with open(args.manifest) as f:
        manifest = json.load(f)

    if args.dimacs:
        num_vars, clauses, var_map, reverse_map = build_formula(
            registry, manifest
        )
        sys.stdout.write(to_dimacs(num_vars, clauses, reverse_map))
        sys.exit(0)

    lockfile = resolve(registry, manifest)
    if lockfile is None:
        print(
            "CONFLICT: Unable to resolve dependencies — no satisfying "
            "assignment exists",
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps(lockfile, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
