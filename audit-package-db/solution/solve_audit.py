#!/usr/bin/env python3
"""
Audits the package database at /opt/pkgdb/ and produces /app/audit_report.json.
"""

import os
import json
import hashlib
from collections import defaultdict


BASE = "/opt/pkgdb"
LOCAL = os.path.join(BASE, "local")
SYNC = os.path.join(BASE, "sync")
CACHE = os.path.join(BASE, "cache")
REPORT_PATH = "/app/audit_report.json"


def parse_desc(path):
    """Parse a section-based desc file into {section: [values]}."""
    with open(path) as f:
        content = f.read()
    result = {}
    current_key = None
    current_values = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("%") and stripped.endswith("%") and len(stripped) > 2:
            if current_key is not None:
                result[current_key] = current_values
            current_key = stripped[1:-1]
            current_values = []
        elif stripped and current_key is not None:
            current_values.append(stripped)
    if current_key is not None:
        result[current_key] = current_values
    return result


def parse_version(v):
    """Parse version string into tuple of ints for comparison."""
    return tuple(int(x) for x in v.split("."))


def compare_versions(v1, v2):
    """Compare two version strings. Returns -1, 0, or 1."""
    p1 = parse_version(v1)
    p2 = parse_version(v2)
    if p1 < p2:
        return -1
    if p1 > p2:
        return 1
    return 0


def parse_dep(dep_str):
    """Parse dependency like 'libnet>=3.0.0' into (name, op, version)."""
    for op in [">=", "<=", ">", "<", "="]:
        idx = dep_str.find(op)
        if idx != -1:
            return dep_str[:idx], op, dep_str[idx + len(op):]
    return dep_str, None, None


def sha256_file(path):
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_local_packages():
    """Load all installed packages from local db."""
    packages = {}
    if not os.path.isdir(LOCAL):
        return packages
    for entry in os.listdir(LOCAL):
        desc_path = os.path.join(LOCAL, entry, "desc")
        if not os.path.isfile(desc_path):
            continue
        desc = parse_desc(desc_path)
        name = desc["NAME"][0]
        version = desc["VERSION"][0]
        depends = desc.get("DEPENDS", [])

        files_path = os.path.join(LOCAL, entry, "files")
        file_list = []
        if os.path.isfile(files_path):
            fdesc = parse_desc(files_path)
            file_list = fdesc.get("FILES", [])

        packages[name] = {
            "version": version,
            "depends": depends,
            "files": file_list,
        }
    return packages


def load_sync_packages():
    """Load all packages from sync repos."""
    packages = {}
    if not os.path.isdir(SYNC):
        return packages
    for repo in os.listdir(SYNC):
        repo_dir = os.path.join(SYNC, repo)
        if not os.path.isdir(repo_dir):
            continue
        for entry in os.listdir(repo_dir):
            desc_path = os.path.join(repo_dir, entry, "desc")
            if not os.path.isfile(desc_path):
                continue
            desc = parse_desc(desc_path)
            name = desc["NAME"][0]
            version = desc["VERSION"][0]
            sha256 = desc.get("SHA256SUM", [None])[0]
            packages[name] = {
                "version": version,
                "sha256": sha256,
                "repo": repo,
            }
    return packages


def check_integrity(sync_packages):
    """Check cached package files against sync database SHA256."""
    failures = []
    if not os.path.isdir(CACHE):
        return failures
    for fname in os.listdir(CACHE):
        if not fname.endswith(".pkg"):
            continue
        base = fname[:-4]  # remove .pkg
        parts = base.rsplit("-", 1)
        if len(parts) != 2:
            continue
        name, version = parts
        if name not in sync_packages:
            continue
        sp = sync_packages[name]
        if sp["version"] != version:
            continue
        expected = sp.get("sha256")
        if not expected:
            continue
        actual = sha256_file(os.path.join(CACHE, fname))
        if actual != expected:
            failures.append({
                "package": name,
                "version": version,
                "expected_sha256": expected,
                "actual_sha256": actual,
            })
    return sorted(failures, key=lambda x: x["package"])


def check_dependencies(local_packages):
    """Check for unsatisfied dependencies among installed packages."""
    unsatisfied = []
    for pkg_name, pkg_info in local_packages.items():
        for dep_str in pkg_info["depends"]:
            dep_name, op, dep_ver = parse_dep(dep_str)
            if dep_name not in local_packages:
                unsatisfied.append({
                    "package": pkg_name,
                    "version": pkg_info["version"],
                    "dependency": dep_str,
                    "installed_version": None,
                })
                continue
            if op is None:
                continue
            inst_ver = local_packages[dep_name]["version"]
            cmp = compare_versions(inst_ver, dep_ver)
            satisfied = False
            if op == ">=":
                satisfied = cmp >= 0
            elif op == "<=":
                satisfied = cmp <= 0
            elif op == ">":
                satisfied = cmp > 0
            elif op == "<":
                satisfied = cmp < 0
            elif op == "=":
                satisfied = cmp == 0
            if not satisfied:
                unsatisfied.append({
                    "package": pkg_name,
                    "version": pkg_info["version"],
                    "dependency": dep_str,
                    "installed_version": inst_ver,
                })
    return sorted(unsatisfied, key=lambda x: (x["package"], x["dependency"]))


def find_cycles(local_packages):
    """Find dependency cycles using Tarjan's SCC algorithm."""
    graph = {}
    for pkg_name, pkg_info in local_packages.items():
        neighbors = []
        for dep_str in pkg_info["depends"]:
            dep_name, _, _ = parse_dep(dep_str)
            if dep_name in local_packages and dep_name != pkg_name:
                if dep_name not in neighbors:
                    neighbors.append(dep_name)
        graph[pkg_name] = neighbors

    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = set()
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], index[w])
        if lowlinks[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for v in sorted(graph.keys()):
        if v not in index:
            strongconnect(v)

    return sccs


def find_file_conflicts(local_packages):
    """Find files owned by multiple installed packages."""
    file_owners = defaultdict(list)
    for pkg_name, pkg_info in local_packages.items():
        for fpath in pkg_info["files"]:
            file_owners[fpath].append(pkg_name)
    conflicts = []
    for fpath, owners in sorted(file_owners.items()):
        if len(owners) > 1:
            conflicts.append({
                "path": fpath,
                "owners": sorted(owners),
            })
    return conflicts


def find_orphans(local_packages, sync_packages):
    """Find installed packages not in any sync repository."""
    orphans = []
    for name in sorted(local_packages.keys()):
        if name not in sync_packages:
            orphans.append(name)
    return orphans


def main():
    local_packages = load_local_packages()
    sync_packages = load_sync_packages()

    report = {
        "integrity_failures": check_integrity(sync_packages),
        "unsatisfied_dependencies": check_dependencies(local_packages),
        "dependency_cycles": find_cycles(local_packages),
        "file_conflicts": find_file_conflicts(local_packages),
        "orphaned_packages": find_orphans(local_packages, sync_packages),
    }

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Audit report written to {REPORT_PATH}")
    print(f"  Integrity failures: {len(report['integrity_failures'])}")
    print(f"  Unsatisfied deps: {len(report['unsatisfied_dependencies'])}")
    print(f"  Dependency cycles: {len(report['dependency_cycles'])}")
    print(f"  File conflicts: {len(report['file_conflicts'])}")
    print(f"  Orphaned packages: {len(report['orphaned_packages'])}")


if __name__ == "__main__":
    main()
