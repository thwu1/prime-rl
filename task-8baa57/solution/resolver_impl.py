#!/usr/bin/env python3
"""
SAT-based package dependency resolver using MiniSat as the SAT backend.

Encodes dependency resolution as Boolean satisfiability, delegates solving
to MiniSat via subprocess, and implements latest-version preference through
iterative constraint tightening.
"""

import json
import sys
import re
import os
import argparse
import subprocess
import tempfile
from itertools import combinations


# -- Semantic version helpers ------------------------------------------------

def parse_version(v):
    return tuple(int(x) for x in v.strip().split("."))


def matches_constraint(version_str, constraint):
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
        # Tilde: patch-level changes only -- >=X.Y.Z <X.(Y+1).0
        upper = (base[0], base[1] + 1, 0)
        return base <= v < upper

    # Range operators: >=X.Y.Z <A.B.C  (or single bound)
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
    return [v for v in available_versions if matches_constraint(v, constraint)]


# -- SAT formula construction ------------------------------------------------

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
    """
    Build a CNF formula from the dependency problem.

    Returns (num_vars, clauses, var_map, reverse_map).
    """
    packages = registry["packages"]
    root_deps = manifest["dependencies"]
    relevant = collect_relevant(registry, root_deps)

    # Assign variable ids (sorted for determinism)
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

    # -- Root dependency clauses --
    for pkg, constraint in root_deps.items():
        if pkg not in packages:
            return num_vars, [[1], [-1]], var_map, reverse_map
        versions = sorted(packages[pkg].keys(), key=parse_version)
        matching = find_matching(constraint, versions)
        if not matching:
            return num_vars, [[1], [-1]], var_map, reverse_map
        clauses.append([var_map[(pkg, v)] for v in matching])

    # -- Dependency implication clauses --
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

    # -- Mutual exclusion (at most one version per package) --
    for pkg in relevant:
        versions = sorted(packages[pkg].keys(), key=parse_version)
        for v1, v2 in combinations(versions, 2):
            clauses.append([-var_map[(pkg, v1)], -var_map[(pkg, v2)]])

    return num_vars, clauses, var_map, reverse_map


# -- MiniSat integration ----------------------------------------------------

def _make_dimacs_str(num_vars, clauses):
    """Generate bare DIMACS CNF string (no comments)."""
    lines = [f"p cnf {num_vars} {len(clauses)}"]
    for clause in clauses:
        lines.append(" ".join(str(l) for l in clause) + " 0")
    return "\n".join(lines) + "\n"


def solve_with_minisat(num_vars, clauses):
    """Solve a SAT formula by invoking MiniSat.

    Returns a dict {variable_id: bool} or None if UNSAT.
    """
    dimacs = _make_dimacs_str(num_vars, clauses)

    cnf_fd, cnf_path = tempfile.mkstemp(suffix=".cnf")
    out_path = cnf_path + ".out"
    try:
        with os.fdopen(cnf_fd, "w") as f:
            f.write(dimacs)

        result = subprocess.run(
            ["/usr/bin/minisat", cnf_path, out_path],
            capture_output=True, timeout=60,
        )

        if result.returncode == 20:
            return None  # UNSAT

        if result.returncode != 10:
            return None  # error or unknown

        with open(out_path) as f:
            lines = f.readlines()

        if not lines or lines[0].strip() != "SAT":
            return None

        assignment = {}
        if len(lines) > 1:
            for tok in lines[1].strip().split():
                lit = int(tok)
                if lit == 0:
                    break
                assignment[abs(lit)] = lit > 0

        return assignment
    finally:
        if os.path.exists(cnf_path):
            os.unlink(cnf_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


# -- Resolution with latest-version preference ------------------------------

def resolve(registry, manifest):
    """Resolve dependencies, preferring latest compatible versions.

    Uses iterative MiniSat invocations: first checks satisfiability, then
    for each package greedily pins the latest compatible version by adding
    unit clauses and re-solving.
    """
    packages = registry["packages"]
    num_vars, clauses, var_map, reverse_map = build_formula(registry, manifest)

    # Check base satisfiability
    assignment = solve_with_minisat(num_vars, clauses)
    if assignment is None:
        return None

    # Iteratively pin each package to its latest compatible version
    relevant = collect_relevant(registry, manifest["dependencies"])
    pinned_clauses = list(clauses)

    for pkg in sorted(relevant):
        versions = sorted(packages[pkg].keys(), key=parse_version, reverse=True)
        for ver in versions:
            vid = var_map[(pkg, ver)]
            test_clauses = pinned_clauses + [[vid]]
            test_assignment = solve_with_minisat(num_vars, test_clauses)
            if test_assignment is not None:
                pinned_clauses.append([vid])
                assignment = test_assignment
                break

    lockfile = {}
    for (pkg, ver), vid in var_map.items():
        if assignment.get(vid, False):
            lockfile[pkg] = ver
    return lockfile


# -- DIMACS export -----------------------------------------------------------

def to_dimacs(registry, manifest):
    """Return a DIMACS CNF string with variable mapping comments."""
    num_vars, clauses, var_map, reverse_map = build_formula(registry, manifest)
    lines = []
    for vid in sorted(reverse_map):
        pkg, ver = reverse_map[vid]
        lines.append(f"c var {vid} {pkg}@{ver}")
    lines.append(f"p cnf {num_vars} {len(clauses)}")
    for clause in clauses:
        lines.append(" ".join(str(l) for l in clause) + " 0")
    return "\n".join(lines) + "\n"


# -- Conflict analysis ------------------------------------------------------

def analyze_conflicts(registry, manifest):
    """Identify irreconcilable version constraints in the dependency graph."""
    packages = registry["packages"]
    root_deps = manifest["dependencies"]
    relevant = collect_relevant(registry, root_deps)

    # Collect all constraints imposed on each package
    constraints_on = {}
    for pkg, constraint in root_deps.items():
        constraints_on.setdefault(pkg, []).append(
            (manifest.get("name", "root"), None, constraint)
        )
    for pkg in relevant:
        for ver, data in packages[pkg].items():
            for dep_pkg, dep_constraint in data.get("dependencies", {}).items():
                if dep_pkg in relevant or dep_pkg in root_deps:
                    constraints_on.setdefault(dep_pkg, []).append(
                        (pkg, ver, dep_constraint)
                    )

    # Find pairwise-incompatible constraints
    conflicts = []
    seen_pkgs = set()
    for pkg in sorted(constraints_on):
        if pkg not in packages or pkg in seen_pkgs:
            continue
        clist = constraints_on[pkg]
        all_versions = sorted(packages[pkg].keys(), key=parse_version)
        for i in range(len(clist)):
            src1, ver1, c1 = clist[i]
            m1 = set(find_matching(c1, all_versions))
            for j in range(i + 1, len(clist)):
                src2, ver2, c2 = clist[j]
                m2 = set(find_matching(c2, all_versions))
                if not (m1 & m2):
                    seen_pkgs.add(pkg)
                    conflicts.append({
                        "package": pkg,
                        "source1": src1, "version1": ver1, "constraint1": c1,
                        "matches1": sorted(m1, key=parse_version),
                        "source2": src2, "version2": ver2, "constraint2": c2,
                        "matches2": sorted(m2, key=parse_version),
                    })
                    break
            if pkg in seen_pkgs:
                break
    return conflicts


def format_conflict_diagnostic(conflicts):
    """Format conflict analysis into a structured multi-line diagnostic."""
    lines = [
        "CONFLICT: Unable to resolve dependencies -- "
        "unsatisfiable constraints detected"
    ]
    for c in conflicts:
        pkg = c["package"]
        s1 = (f"{c['source1']}@{c['version1']}"
              if c["version1"] else c["source1"])
        s2 = (f"{c['source2']}@{c['version2']}"
              if c["version2"] else c["source2"])
        m1_str = ", ".join(c["matches1"])
        m2_str = ", ".join(c["matches2"])
        lines.append(f"  {pkg} has incompatible version requirements:")
        lines.append(
            f"    {s1} requires {pkg} {c['constraint1']} "
            f"(compatible: {m1_str})"
        )
        lines.append(
            f"    {s2} requires {pkg} {c['constraint2']} "
            f"(compatible: {m2_str})"
        )
        lines.append(
            f"    No version of {pkg} satisfies both constraints"
        )
    return "\n".join(lines)


# -- CLI ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SAT-based package dependency resolver"
    )
    parser.add_argument("manifest", help="Path to manifest JSON file")
    parser.add_argument(
        "--dimacs", action="store_true",
        help="Output DIMACS CNF instead of resolving",
    )
    parser.add_argument(
        "--registry", default="/app/registry.json",
        help="Path to package registry JSON",
    )
    args = parser.parse_args()

    with open(args.registry) as f:
        registry = json.load(f)
    with open(args.manifest) as f:
        manifest = json.load(f)

    if args.dimacs:
        sys.stdout.write(to_dimacs(registry, manifest))
        sys.exit(0)

    lockfile = resolve(registry, manifest)
    if lockfile is None:
        conflicts = analyze_conflicts(registry, manifest)
        diagnostic = format_conflict_diagnostic(conflicts)
        print(diagnostic, file=sys.stderr)
        sys.exit(1)

    print(json.dumps(lockfile, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
