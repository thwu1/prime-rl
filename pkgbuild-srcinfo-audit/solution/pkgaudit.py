#!/usr/bin/env python3
"""
PKGBUILD Repository Audit Tool.
Parses PKGBUILDs, generates .SRCINFO files, builds dependency graphs,
detects issues, and computes topological installation order.
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict

REPO_DIR = "/app/repo"
RESULTS_DIR = "/app/results"
SCRIPT_DIR = "/solution"

# .SRCINFO field ordering for pkgbase section
PKGBASE_FIELD_ORDER = [
    "pkgdesc", "pkgver", "pkgrel", "epoch", "url", "install", "changelog",
    "arch", "groups", "license", "checkdepends", "makedepends", "depends",
    "optdepends", "provides", "conflicts", "replaces", "options", "backup",
    "validpgpkeys", "noextract", "source",
    "md5sums", "sha1sums", "sha224sums", "sha256sums", "sha384sums",
    "sha512sums", "b2sums",
]

# .SRCINFO field ordering for pkgname section (overridable per-package fields)
PKGNAME_FIELD_ORDER = [
    "pkgdesc", "install", "changelog", "url", "arch", "groups", "license",
    "checkdepends", "depends", "optdepends", "provides", "conflicts",
    "replaces", "options", "backup",
]

# Fields that are always scalars (single value, not arrays)
SCALAR_FIELDS = {
    "pkgdesc", "pkgver", "pkgrel", "epoch", "url", "install", "changelog",
    "pkgbase",
}


class PkgData:
    """Container for parsed PKGBUILD data."""

    def __init__(self):
        self.scalars = {}
        self.arrays = defaultdict(list)

    def has(self, key):
        return key in self.scalars or bool(self.arrays.get(key))


def parse_extractor_output(output):
    """Parse tab-separated output from the bash extractor scripts."""
    data = PkgData()
    for line in output.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        typ, key, val = parts
        if typ == "S":
            data.scalars[key] = val
        elif typ == "A":
            data.arrays[key].append(val)
    return data


def run_extract_globals(pkg_dir):
    """Run extract_globals.sh on a package directory."""
    script = os.path.join(SCRIPT_DIR, "extract_globals.sh")
    result = subprocess.run(
        ["bash", script, pkg_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Warning: extract_globals failed for {pkg_dir}: {result.stderr}",
              file=sys.stderr)
    return parse_extractor_output(result.stdout)


def run_extract_func(pkg_dir, func_name):
    """Run extract_func.sh on a package directory for a specific function."""
    script = os.path.join(SCRIPT_DIR, "extract_func.sh")
    result = subprocess.run(
        ["bash", script, pkg_dir, func_name],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Warning: extract_func failed for {func_name}: {result.stderr}",
              file=sys.stderr)
    return parse_extractor_output(result.stdout)


def generate_srcinfo(pkg_dir):
    """Generate .SRCINFO content for a package."""
    global_data = run_extract_globals(pkg_dir)

    pkgnames = global_data.arrays.get("pkgname", [])
    pkgbase = global_data.scalars.get("pkgbase", pkgnames[0] if pkgnames else "")
    is_split = len(pkgnames) > 1

    lines = [f"pkgbase = {pkgbase}"]

    # Global fields
    for field in PKGBASE_FIELD_ORDER:
        if field in SCALAR_FIELDS:
            val = global_data.scalars.get(field)
            if val:
                lines.append(f"\t{field} = {val}")
        else:
            for val in global_data.arrays.get(field, []):
                lines.append(f"\t{field} = {val}")

    # Package sections
    for pkgname in pkgnames:
        lines.append("")
        lines.append(f"pkgname = {pkgname}")

        if is_split:
            func_name = f"package_{pkgname}"
            func_data = run_extract_func(pkg_dir, func_name)

            for field in PKGNAME_FIELD_ORDER:
                if not func_data.has(field):
                    continue
                if field in SCALAR_FIELDS:
                    val = func_data.scalars.get(field)
                    if val:
                        lines.append(f"\t{field} = {val}")
                else:
                    for val in func_data.arrays.get(field, []):
                        lines.append(f"\t{field} = {val}")

    lines.append("")
    return "\n".join(lines)


def parse_version_constraint(dep):
    """Parse 'pkgname>=1.0' into (name, operator, version)."""
    for op in [">=", "<=", "=", ">", "<"]:
        if op in dep:
            idx = dep.index(op)
            return dep[:idx], op, dep[idx + len(op):]
    return dep, None, None


def vercmp(v1, v2):
    """Simple version comparison. Returns -1, 0, or 1."""
    def normalize(v):
        parts = re.split(r"[.\-]", v)
        result = []
        for p in parts:
            if p.isdigit():
                result.append(int(p))
            else:
                result.append(p)
        return result

    n1, n2 = normalize(v1), normalize(v2)
    max_len = max(len(n1), len(n2))
    n1.extend([0] * (max_len - len(n1)))
    n2.extend([0] * (max_len - len(n2)))

    for a, b in zip(n1, n2):
        if type(a) == type(b):
            if a < b:
                return -1
            if a > b:
                return 1
        else:
            a_str, b_str = str(a), str(b)
            if a_str < b_str:
                return -1
            if a_str > b_str:
                return 1
    return 0


def check_version_satisfies(provided_ver, op, required_ver):
    """Check if provided_ver satisfies the constraint 'op required_ver'."""
    cmp = vercmp(provided_ver, required_ver)
    checks = {
        ">=": cmp >= 0,
        "<=": cmp <= 0,
        "=": cmp == 0,
        ">": cmp > 0,
        "<": cmp < 0,
    }
    return checks.get(op, True)


def build_dependency_graph(packages):
    """Build the inter-package dependency graph (in-repo deps only)."""
    # Map all known package names and provides to their versions
    all_known_names = set()
    name_to_version = {}

    for pkg in packages:
        for pname in pkg["pkgnames"]:
            all_known_names.add(pname)
            name_to_version[pname] = pkg["pkgver"]
        for prov in pkg.get("all_provides", []):
            prov_name, _, prov_ver = parse_version_constraint(prov)
            all_known_names.add(prov_name)
            if prov_ver:
                name_to_version[prov_name] = prov_ver
            else:
                name_to_version[prov_name] = pkg["pkgver"]

    # Build graph edges
    graph = {}
    for pkg in packages:
        for pname in pkg["pkgnames"]:
            deps = pkg["deps_for"].get(pname, [])
            in_repo_deps = []
            for dep in deps:
                dep_name, _, _ = parse_version_constraint(dep)
                if dep_name in all_known_names and dep_name != pname:
                    in_repo_deps.append(dep_name)
            graph[pname] = sorted(set(in_repo_deps))

    return graph, name_to_version


def detect_cycles(graph):
    """Detect cycles using DFS. Returns list of cycles and set of cycle nodes."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    cycles = []
    cycle_nodes = set()

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
                for n in path[cycle_start:]:
                    cycle_nodes.add(n)
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)

        path.pop()
        color[node] = BLACK

    for node in sorted(graph.keys()):
        if color[node] == WHITE:
            dfs(node, [])

    return cycles, cycle_nodes


def topological_sort(graph, exclude):
    """Kahn's algorithm for topological sort, excluding specified nodes."""
    filtered = {
        k: [v for v in vs if v not in exclude]
        for k, vs in graph.items()
        if k not in exclude
    }

    # in-degree = number of in-repo dependencies that must be installed first
    in_degree = {node: 0 for node in filtered}
    for node, deps in filtered.items():
        for dep in deps:
            if dep in filtered:
                pass  # dep has a dependent (node)

    # Recompute: for each node, count how many of its deps are in filtered
    in_degree = {node: 0 for node in filtered}
    for node, deps in filtered.items():
        in_degree[node] = sum(1 for d in deps if d in filtered)

    queue = sorted(n for n, d in in_degree.items() if d == 0)
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        # Find nodes that depend on this node and decrement their in-degree
        for other, deps in filtered.items():
            if node in deps:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    # Insert sorted for determinism
                    import bisect
                    bisect.insort(queue, other)

    return result


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Find package directories
    pkg_dirs = sorted([
        d for d in os.listdir(REPO_DIR)
        if os.path.isfile(os.path.join(REPO_DIR, d, "PKGBUILD"))
    ])

    packages = []
    issues = []

    for pkg_dir in pkg_dirs:
        pkg_path = os.path.join(REPO_DIR, pkg_dir)
        print(f"Processing {pkg_dir}...")

        # Generate .SRCINFO
        srcinfo = generate_srcinfo(pkg_path)
        srcinfo_path = os.path.join(pkg_path, ".SRCINFO")
        with open(srcinfo_path, "w") as f:
            f.write(srcinfo)

        # Extract data for analysis
        global_data = run_extract_globals(pkg_path)
        pkgnames = global_data.arrays.get("pkgname", [])
        pkgver = global_data.scalars.get("pkgver", "")
        epoch = global_data.scalars.get("epoch", "")

        # Collect per-package deps and provides
        all_provides = []
        deps_for = {}

        if len(pkgnames) > 1:
            # Split package
            for pname in pkgnames:
                func_data = run_extract_func(pkg_path, f"package_{pname}")
                deps_for[pname] = func_data.arrays.get("depends", [])
                all_provides.extend(func_data.arrays.get("provides", []))
        else:
            # Single package
            if pkgnames:
                deps_for[pkgnames[0]] = global_data.arrays.get("depends", [])
                all_provides = global_data.arrays.get("provides", [])

        # Check source/checksum count mismatch
        sources = global_data.arrays.get("source", [])
        for sum_type in ["md5sums", "sha1sums", "sha224sums", "sha256sums",
                         "sha384sums", "sha512sums", "b2sums"]:
            sums = global_data.arrays.get(sum_type, [])
            if sums and len(sums) != len(sources):
                issues.append({
                    "package": pkg_dir,
                    "type": "checksum_mismatch",
                    "description": (
                        f"{len(sources)} source entries but "
                        f"{len(sums)} {sum_type} entries"
                    ),
                })

        packages.append({
            "dir": pkg_dir,
            "pkgnames": pkgnames,
            "pkgver": pkgver,
            "epoch": epoch,
            "deps_for": deps_for,
            "all_provides": all_provides,
        })

    # Build dependency graph
    graph, name_to_version = build_dependency_graph(packages)

    # Detect cycles
    cycles, cycle_nodes = detect_cycles(graph)
    for cycle in cycles:
        cycle_str = " -> ".join(cycle)
        issues.append({
            "package": cycle[0],
            "type": "circular_dependency",
            "description": f"Circular dependency: {cycle_str}",
        })

    # Check version constraints
    name_to_pkg = {}
    for pkg in packages:
        for pname in pkg["pkgnames"]:
            name_to_pkg[pname] = pkg

    for pkg in packages:
        for pname in pkg["pkgnames"]:
            for dep in pkg["deps_for"].get(pname, []):
                dep_name, op, req_ver = parse_version_constraint(dep)
                if op and dep_name in name_to_pkg:
                    dep_pkg = name_to_pkg[dep_name]
                    provided_ver = dep_pkg["pkgver"]
                    if not check_version_satisfies(provided_ver, op, req_ver):
                        issues.append({
                            "package": pname,
                            "type": "version_conflict",
                            "description": (
                                f"Depends on {dep} but repository provides "
                                f"{dep_name}={provided_ver}"
                            ),
                        })

    # Topological sort
    install_order = topological_sort(graph, cycle_nodes)

    # Write results
    with open(os.path.join(RESULTS_DIR, "dependency_graph.json"), "w") as f:
        json.dump(graph, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "issues.json"), "w") as f:
        json.dump(issues, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "install_order.json"), "w") as f:
        json.dump(install_order, f, indent=2)

    print(f"\nAudit complete.")
    print(f"Generated .SRCINFO for {len(pkg_dirs)} packages.")
    print(f"Found {len(issues)} issues.")
    print(f"Install order ({len(install_order)} packages): {install_order}")


if __name__ == "__main__":
    main()
