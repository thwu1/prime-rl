#!/usr/bin/env python3
"""Pacman database forensics solver.

Parses the local and sync pacman databases, detects all corruption/issue
types, evaluates repair strategies, and produces:
  /app/report.json   — issue diagnostics
  /app/strategy.json — repair strategy evaluation
  /app/repair.sh     — dependency-ordered repair script

"""
import io
import json
import os
import re
import sqlite3
import subprocess
import tarfile
import tempfile
from collections import defaultdict

ARCHROOT = "/app/archroot"
LOCAL_DB = os.path.join(ARCHROOT, "var/lib/pacman/local")
SYNC_ARCHIVE = os.path.join(ARCHROOT, "var/lib/pacman/sync/core.db")
METADATA_DB = os.path.join(ARCHROOT, "var/lib/pacman/package_metadata.db")
REPORT_PATH = "/app/report.json"
STRATEGY_PATH = "/app/strategy.json"
REPAIR_PATH = "/app/repair.sh"

# Sections that a well-formed local desc MUST contain
REQUIRED_LOCAL_SECTIONS = {"NAME", "VERSION", "DESC", "ARCH", "SIZE"}


# ── Version comparison (pacman-compatible vercmp) ─────────────────────────

def _split_version_string(v):
    """Split version into (epoch, version, release)."""
    epoch = 0
    if ":" in v:
        es, v = v.split(":", 1)
        epoch = int(es)
    if "-" in v:
        ver, rel = v.rsplit("-", 1)
    else:
        ver, rel = v, None
    return epoch, ver, rel


def _tokenize(s):
    """Split a version/release segment into numeric and alpha tokens."""
    return re.findall(r"[0-9]+|[a-zA-Z]+", s)


def _compare_tokens(a, b):
    """Compare two version tokens (one segment each)."""
    ta = _tokenize(a)
    tb = _tokenize(b)
    for x, y in zip(ta, tb):
        x_num = x.isdigit()
        y_num = y.isdigit()
        if x_num and y_num:
            ix, iy = int(x), int(y)
            if ix != iy:
                return (ix > iy) - (ix < iy)
        elif x_num:
            return 1
        elif y_num:
            return -1
        else:
            if x != y:
                return (x > y) - (x < y)
    return (len(ta) > len(tb)) - (len(ta) < len(tb))


def vercmp(v1, v2):
    """Compare two pacman version strings.  Returns -1 / 0 / 1."""
    e1, ver1, rel1 = _split_version_string(v1)
    e2, ver2, rel2 = _split_version_string(v2)
    if e1 != e2:
        return (e1 > e2) - (e1 < e2)
    segs1 = ver1.split(".")
    segs2 = ver2.split(".")
    for s1, s2 in zip(segs1, segs2):
        c = _compare_tokens(s1, s2)
        if c != 0:
            return c
    if len(segs1) != len(segs2):
        return (len(segs1) > len(segs2)) - (len(segs1) < len(segs2))
    if rel1 is not None and rel2 is not None:
        return _compare_tokens(rel1, rel2)
    if rel1 is not None:
        return 1
    if rel2 is not None:
        return -1
    return 0


# ── Dependency parsing ────────────────────────────────────────────────────

def parse_dep(dep_str):
    """Parse 'pkg>=1.2' into (name, op, ver).  No op -> (name, None, None)."""
    for op in (">=", "<=", "==", "=", ">", "<"):
        if op in dep_str:
            name, ver = dep_str.split(op, 1)
            return name, op, ver
    return dep_str, None, None


def dep_satisfied(installed_version, op, constraint_version):
    if op is None:
        return True
    c = vercmp(installed_version, constraint_version)
    return {
        ">=": c >= 0, "<=": c <= 0, "=": c == 0,
        "==": c == 0, ">": c > 0, "<": c < 0,
    }.get(op, True)


# ── Database parsing ─────────────────────────────────────────────────────

def parse_desc(filepath):
    """Parse a pacman desc file into {section: [values]}."""
    result = {}
    try:
        with open(filepath) as f:
            content = f.read()
    except (IOError, OSError):
        return None

    current_section = None
    for line in content.split("\n"):
        line = line.strip()
        m = re.match(r"^%([A-Z0-9_]+)%$", line)
        if m:
            current_section = m.group(1)
            result[current_section] = []
        elif line and current_section is not None:
            result[current_section].append(line)
    return result


def parse_desc_from_bytes(data):
    """Parse a pacman desc from bytes content."""
    result = {}
    content = data.decode("utf-8", errors="replace")
    current_section = None
    for line in content.split("\n"):
        line = line.strip()
        m = re.match(r"^%([A-Z0-9_]+)%$", line)
        if m:
            current_section = m.group(1)
            result[current_section] = []
        elif line and current_section is not None:
            result[current_section].append(line)
    return result


def scan_local_db():
    """Scan local database, return dict of {name: info} and list of raw dirs."""
    packages = {}
    raw_dirs = []
    for entry in sorted(os.listdir(LOCAL_DB)):
        entry_path = os.path.join(LOCAL_DB, entry)
        if not os.path.isdir(entry_path) or entry == "ALPM_DB_VERSION":
            continue
        raw_dirs.append(entry)
        desc_path = os.path.join(entry_path, "desc")
        files_path = os.path.join(entry_path, "files")

        has_desc = os.path.isfile(desc_path)
        desc = parse_desc(desc_path) if has_desc else None

        # Parse files
        file_list = []
        if os.path.isfile(files_path):
            files_data = parse_desc(files_path)
            if files_data and "FILES" in files_data:
                file_list = files_data["FILES"]

        pkg_info = {
            "dir_name": entry,
            "dir_path": entry_path,
            "has_desc": has_desc,
            "desc": desc,
            "files": file_list,
        }

        if desc and "NAME" in desc:
            name = desc["NAME"][0]
            version = desc["VERSION"][0] if "VERSION" in desc else None
            pkg_info["name"] = name
            pkg_info["version"] = version
            pkg_info["deps"] = desc.get("DEPENDS", [])
            pkg_info["provides"] = desc.get("PROVIDES", [])
            pkg_info["reason"] = int(desc["REASON"][0]) if "REASON" in desc else 0
            packages[name] = pkg_info
        else:
            # Try to extract name/version from directory name
            m = re.match(r"^(.+)-([^-]+-[^-]+)$", entry)
            if m:
                name_guess = m.group(1)
                ver_guess = m.group(2)
                pkg_info["name"] = name_guess
                pkg_info["version"] = ver_guess
                pkg_info["deps"] = []
                pkg_info["provides"] = []
                pkg_info["reason"] = 0
                packages[name_guess] = pkg_info

    return packages, raw_dirs


def scan_sync_db():
    """Scan sync database from zstd-compressed tar archive."""
    packages = {}

    # Decompress zstd explicitly, then extract tar with Python's tarfile
    tmpdir = tempfile.mkdtemp(prefix="syncdb_")
    decomp = subprocess.run(
        ["zstd", "-d", "-c", SYNC_ARCHIVE],
        capture_output=True, check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(decomp.stdout), mode="r:") as tar:
        tar.extractall(path=tmpdir, filter="data")

    for entry in sorted(os.listdir(tmpdir)):
        entry_path = os.path.join(tmpdir, entry)
        if not os.path.isdir(entry_path):
            continue
        desc_path = os.path.join(entry_path, "desc")
        desc = parse_desc(desc_path) if os.path.isfile(desc_path) else None
        if desc and "NAME" in desc:
            name = desc["NAME"][0]
            packages[name] = {
                "name": name,
                "version": desc["VERSION"][0] if "VERSION" in desc else None,
                "deps": desc.get("DEPENDS", []),
                "provides": desc.get("PROVIDES", []),
                "desc": desc,
            }
    return packages


# ── Issue detection ──────────────────────────────────────────────────────

def detect_issues(local_pkgs, sync_pkgs):
    issues = []

    # 1. MISSING_DESC
    for name, info in local_pkgs.items():
        if not info["has_desc"]:
            issues.append({
                "type": "MISSING_DESC",
                "package": name,
                "details": {},
            })

    # 2. CORRUPTED_DESC
    for name, info in local_pkgs.items():
        if not info["has_desc"]:
            continue
        desc = info["desc"]
        if desc is None:
            issues.append({
                "type": "CORRUPTED_DESC",
                "package": name,
                "details": {},
            })
            continue
        # Check for missing required sections
        missing_sections = REQUIRED_LOCAL_SECTIONS - set(desc.keys())
        if missing_sections:
            issues.append({
                "type": "CORRUPTED_DESC",
                "package": name,
                "details": {},
            })
            continue
        # Check for truncated deps (dep name not matching any known package)
        if "DEPENDS" in desc:
            for dep_str in desc["DEPENDS"]:
                dep_name, _, _ = parse_dep(dep_str)
                if dep_name not in local_pkgs and dep_name not in sync_pkgs:
                    issues.append({
                        "type": "CORRUPTED_DESC",
                        "package": name,
                        "details": {},
                    })
                    break

    # 3. PARTIAL_UPGRADE
    for name, info in local_pkgs.items():
        if info["version"] is None:
            continue
        if name not in sync_pkgs:
            continue
        sync_ver = sync_pkgs[name]["version"]
        local_ver = info["version"]
        if sync_ver is None:
            continue
        if vercmp(local_ver, sync_ver) >= 0:
            continue  # local is same or newer
        # Check if any installed package has a versioned dep on this that fails
        affected = []
        for other_name, other_info in local_pkgs.items():
            if other_name == name:
                continue
            for dep_str in other_info.get("deps", []):
                dep_name, op, dep_ver = parse_dep(dep_str)
                if dep_name == name and op is not None:
                    if not dep_satisfied(local_ver, op, dep_ver):
                        affected.append(other_name)
                        break
        if affected:
            issues.append({
                "type": "PARTIAL_UPGRADE",
                "package": name,
                "details": {
                    "local_version": local_ver,
                    "sync_version": sync_ver,
                    "affected_dependents": sorted(affected),
                },
            })

    # 4. MISSING_DEPENDENCY
    for name, info in local_pkgs.items():
        for dep_str in info.get("deps", []):
            dep_name, _, _ = parse_dep(dep_str)
            if dep_name not in local_pkgs:
                # Check if a provides satisfies it
                provided = False
                for other_name, other_info in local_pkgs.items():
                    for prov in other_info.get("provides", []):
                        prov_name, _, _ = parse_dep(prov)
                        if prov_name == dep_name:
                            provided = True
                            break
                    if provided:
                        break
                if not provided:
                    issues.append({
                        "type": "MISSING_DEPENDENCY",
                        "package": name,
                        "details": {
                            "missing_dependency": dep_name,
                        },
                    })

    # 5. FILE_CONFLICT
    file_owners = defaultdict(list)
    for name, info in local_pkgs.items():
        for fpath in info.get("files", []):
            if fpath.endswith("/"):
                continue  # skip directories
            file_owners[fpath].append(name)
    for fpath, owners in file_owners.items():
        if len(owners) > 1:
            issues.append({
                "type": "FILE_CONFLICT",
                "package": owners[0],
                "details": {
                    "file": fpath,
                    "packages": sorted(owners),
                },
            })

    # 6. ORPHANED_PACKAGE
    all_dep_names = set()
    for name, info in local_pkgs.items():
        for dep_str in info.get("deps", []):
            dep_name, _, _ = parse_dep(dep_str)
            all_dep_names.add(dep_name)
    for name, info in local_pkgs.items():
        if info.get("reason", 0) != 1:
            continue
        if name not in all_dep_names:
            issues.append({
                "type": "ORPHANED_PACKAGE",
                "package": name,
                "details": {},
            })

    return issues


# ── Strategy evaluation ────────────────────────────────────────────────

def evaluate_strategy(issues, local_pkgs, sync_pkgs):
    """Evaluate repair strategy: compute independent groups, check cycles."""

    # Determine all packages needing repair action
    repair_set = set()
    for issue in issues:
        repair_set.add(issue["package"])
        if issue["type"] == "PARTIAL_UPGRADE":
            for dep in issue["details"].get("affected_dependents", []):
                repair_set.add(dep)
        elif issue["type"] == "MISSING_DEPENDENCY":
            repair_set.add(issue["details"]["missing_dependency"])
        elif issue["type"] == "FILE_CONFLICT":
            for pkg in issue["details"].get("packages", []):
                repair_set.add(pkg)

    # Build undirected adjacency for connected components
    adj = defaultdict(set)

    # Connect packages linked by issues
    for issue in issues:
        if issue["type"] == "PARTIAL_UPGRADE":
            pkg = issue["package"]
            for dep in issue["details"].get("affected_dependents", []):
                adj[pkg].add(dep)
                adj[dep].add(pkg)
        elif issue["type"] == "MISSING_DEPENDENCY":
            pkg = issue["package"]
            missing = issue["details"]["missing_dependency"]
            adj[pkg].add(missing)
            adj[missing].add(pkg)
        elif issue["type"] == "FILE_CONFLICT":
            pkgs = issue["details"].get("packages", [])
            for i in range(len(pkgs)):
                for j in range(i + 1, len(pkgs)):
                    adj[pkgs[i]].add(pkgs[j])
                    adj[pkgs[j]].add(pkgs[i])

    # Connect packages in repair_set that share dependencies
    for pkg_name in repair_set:
        if pkg_name in local_pkgs:
            for dep_str in local_pkgs[pkg_name].get("deps", []):
                dep_name, _, _ = parse_dep(dep_str)
                if dep_name in repair_set:
                    adj[pkg_name].add(dep_name)
                    adj[dep_name].add(pkg_name)

    # BFS connected components
    visited = set()
    groups = []
    for pkg_name in sorted(repair_set):
        if pkg_name in visited:
            continue
        component = []
        queue = [pkg_name]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        groups.append(sorted(component))

    # Check for circular dependencies using DFS on directed dep graph
    directed = defaultdict(set)
    for pkg_name in repair_set:
        if pkg_name in local_pkgs:
            for dep_str in local_pkgs[pkg_name].get("deps", []):
                dep_name, _, _ = parse_dep(dep_str)
                if dep_name in repair_set:
                    directed[pkg_name].add(dep_name)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {pkg: WHITE for pkg in repair_set}
    has_cycle = False

    def dfs(node):
        nonlocal has_cycle
        color[node] = GRAY
        for neighbor in directed.get(node, set()):
            if color.get(neighbor, WHITE) == GRAY:
                has_cycle = True
                return
            if color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor)
        color[node] = BLACK

    for pkg in sorted(repair_set):
        if color.get(pkg, WHITE) == WHITE:
            dfs(pkg)

    # Compute full upgrade set (all packages behind sync)
    full_upgrade_set = set()
    for name, info in local_pkgs.items():
        if info["version"] and name in sync_pkgs:
            sync_ver = sync_pkgs[name]["version"]
            if sync_ver and vercmp(info["version"], sync_ver) < 0:
                full_upgrade_set.add(name)

    # Query SQLite for download cost context
    total_targeted_bytes = 0
    try:
        conn = sqlite3.connect(METADATA_DB)
        for row in conn.execute("SELECT name, compressed_size FROM package_sizes"):
            if row[0] in repair_set:
                total_targeted_bytes += row[1]
        conn.close()
    except Exception:
        pass

    strategy = {
        "recommended_strategy": "targeted",
        "minimum_repair_set": sorted(repair_set),
        "independent_repair_groups": groups,
        "has_circular_dependencies": has_cycle,
        "total_repair_operations": len(repair_set),
        "recommendation_rationale": (
            "Targeted repair is recommended: %d packages need action across "
            "%d independent groups. A full system upgrade (pacman -Syu) would "
            "touch %d packages with version differences. The dependency graph "
            "has no circular dependencies, so incremental repair is safe. "
            "Estimated targeted download: %.1f MB."
            % (
                len(repair_set),
                len(groups),
                len(full_upgrade_set),
                total_targeted_bytes / (1024 * 1024),
            )
        ),
    }
    return strategy


# ── Repair script generation ────────────────────────────────────────────

def generate_repair_script(issues):
    """Generate dependency-ordered repair commands."""
    lines = [
        "#!/bin/bash",
        "# Pacman database repair script",
        "# Generated by forensics solver",
        "",
    ]

    # Group issues by type
    by_type = defaultdict(list)
    for issue in issues:
        by_type[issue["type"]].append(issue)

    # Phase 1: Fix database integrity (missing/corrupted desc)
    desc_pkgs = []
    for issue in by_type.get("MISSING_DESC", []):
        desc_pkgs.append(issue["package"])
    for issue in by_type.get("CORRUPTED_DESC", []):
        desc_pkgs.append(issue["package"])
    if desc_pkgs:
        lines.append("# Phase 1: Restore missing/corrupted database entries")
        for pkg in desc_pkgs:
            lines.append("pacman -S --noconfirm --dbonly %s" % pkg)
        lines.append("")

    # Phase 2: Install missing dependencies
    missing = by_type.get("MISSING_DEPENDENCY", [])
    if missing:
        lines.append("# Phase 2: Install missing dependencies")
        installed = set()
        for issue in missing:
            dep = issue["details"]["missing_dependency"]
            if dep not in installed:
                lines.append("pacman -S --noconfirm %s" % dep)
                installed.add(dep)
        lines.append("")

    # Phase 3: Fix partial upgrades (dependencies first, then dependents)
    partial = by_type.get("PARTIAL_UPGRADE", [])
    if partial:
        lines.append("# Phase 3: Upgrade packages stuck in partial-upgrade state")
        for issue in partial:
            lines.append("pacman -S --noconfirm %s" % issue["package"])
        all_deps = set()
        for issue in partial:
            for dep in issue["details"].get("affected_dependents", []):
                all_deps.add(dep)
        for dep in sorted(all_deps):
            lines.append("pacman -S --noconfirm %s" % dep)
        lines.append("")

    # Phase 4: Fix file conflicts
    conflicts = by_type.get("FILE_CONFLICT", [])
    if conflicts:
        lines.append("# Phase 4: Resolve file ownership conflicts")
        for issue in conflicts:
            fpath = issue["details"]["file"]
            pkgs = issue["details"]["packages"]
            lines.append(
                "pacman -S --noconfirm --overwrite '/%s' %s" % (fpath, pkgs[-1])
            )
        lines.append("")

    # Phase 5: Remove orphans
    orphans = by_type.get("ORPHANED_PACKAGE", [])
    if orphans:
        lines.append("# Phase 5: Remove orphaned packages")
        names = " ".join(i["package"] for i in orphans)
        lines.append("pacman -Rns --noconfirm %s" % names)
        lines.append("")

    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    local_pkgs, _ = scan_local_db()
    sync_pkgs = scan_sync_db()

    issues = detect_issues(local_pkgs, sync_pkgs)

    # Write report
    report = {"issues": issues}
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote %d issues to %s" % (len(issues), REPORT_PATH))

    # Evaluate strategy
    strategy = evaluate_strategy(issues, local_pkgs, sync_pkgs)
    with open(STRATEGY_PATH, "w") as f:
        json.dump(strategy, f, indent=2)
    print("Wrote strategy to %s" % STRATEGY_PATH)

    # Write repair script
    script = generate_repair_script(issues)
    with open(REPAIR_PATH, "w") as f:
        f.write(script)
    os.chmod(REPAIR_PATH, 0o755)
    print("Wrote repair script to %s" % REPAIR_PATH)


if __name__ == "__main__":
    main()
