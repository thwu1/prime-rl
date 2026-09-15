#!/usr/bin/env python3
"""
dn42 Registry Security Audit Tool - Solution

Parses all RPSL-like registry objects, validates cross-references,
authorization chains, peering policy references, route containment,
ROA constraints, and network analysis. Traces violations to git commits.
Outputs a structured JSON forensic report.
"""

import ipaddress
import json
import os
import re
import subprocess
import sys


REGISTRY_PATH = "/app/registry"
DATA_PATH = os.path.join(REGISTRY_PATH, "data")
REPORT_PATH = "/app/forensic_report.json"

OBJECT_TYPES = [
    "mntner", "person", "aut-num", "inetnum", "inet6num",
    "route", "route6", "dns",
]

# Global commit map cache
_COMMIT_MAP = None


def log(msg):
    print(msg, file=sys.stderr)


def parse_object(filepath):
    """Parse a single RPSL-like registry object file into a dict of attributes.

    Handles continuation lines (leading whitespace) and comments (#).
    For attributes that appear multiple times, values are stored as lists.
    """
    attrs = {}
    current_key = None
    with open(filepath) as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip() or line.strip().startswith("#"):
                continue
            if line[0] in (" ", "\t") and current_key is not None:
                val = line.strip()
                if current_key in attrs:
                    existing = attrs[current_key]
                    if isinstance(existing, list):
                        existing[-1] += " " + val
                    else:
                        attrs[current_key] = existing + " " + val
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            current_key = key
            if key in attrs:
                existing = attrs[key]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    attrs[key] = [existing, value]
            else:
                attrs[key] = value
    return attrs


def load_registry():
    """Load all objects from the registry, organized by type."""
    objects = {}
    for obj_type in OBJECT_TYPES:
        type_dir = os.path.join(DATA_PATH, obj_type)
        objects[obj_type] = {}
        if not os.path.isdir(type_dir):
            log(f"WARNING: directory not found for type '{obj_type}': {type_dir}")
            continue
        for name in sorted(os.listdir(type_dir)):
            path = os.path.join(type_dir, name)
            if os.path.isfile(path) and not name.startswith("."):
                objects[obj_type][name] = parse_object(path)
    return objects


def get_values(attrs, key):
    """Get all values for an attribute key as a flat list."""
    val = attrs.get(key)
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def get_commit_map():
    """Build a mapping from commit hash to commit message (cached)."""
    global _COMMIT_MAP
    if _COMMIT_MAP is not None:
        return _COMMIT_MAP
    result = subprocess.run(
        ["git", "-C", REGISTRY_PATH, "log", "--format=%H %s"],
        capture_output=True, text=True
    )
    _COMMIT_MAP = {}
    for line in result.stdout.strip().split("\n"):
        if " " in line:
            hash_val, msg = line.split(" ", 1)
            _COMMIT_MAP[hash_val] = msg
    log(f"Git commits found: {len(_COMMIT_MAP)}")
    for h, m in _COMMIT_MAP.items():
        log(f"  {h[:8]} {m}")
    return _COMMIT_MAP


def git_blame_line(filepath, search_key):
    """Use git blame to find which commit last modified the line containing search_key."""
    rel_path = os.path.relpath(filepath, REGISTRY_PATH)
    result = subprocess.run(
        ["git", "-C", REGISTRY_PATH, "blame", "--porcelain", rel_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log(f"WARNING: git blame failed for {rel_path}: {result.stderr}")
        return None
    commit_map = get_commit_map()
    lines = result.stdout.split("\n")
    current_hash = None
    for line in lines:
        if re.match(r"^[0-9a-f]{40} ", line):
            current_hash = line.split()[0]
        elif line.startswith("\t"):
            content = line[1:]
            if ":" in content:
                k = content.split(":")[0].strip()
                if k == search_key and current_hash in commit_map:
                    return commit_map[current_hash]
    return None


def git_blame_line_content(filepath, content_substr):
    """Use git blame to find which commit last modified a line containing content_substr."""
    rel_path = os.path.relpath(filepath, REGISTRY_PATH)
    result = subprocess.run(
        ["git", "-C", REGISTRY_PATH, "blame", "--porcelain", rel_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log(f"WARNING: git blame failed for {rel_path}: {result.stderr}")
        return None
    commit_map = get_commit_map()
    lines = result.stdout.split("\n")
    current_hash = None
    for line in lines:
        if re.match(r"^[0-9a-f]{40} ", line):
            current_hash = line.split()[0]
        elif line.startswith("\t"):
            content = line[1:]
            if content_substr in content and current_hash in commit_map:
                return commit_map[current_hash]
    return None


def git_file_creation_commit(filepath):
    """Find the commit that first added this file."""
    rel_path = os.path.relpath(filepath, REGISTRY_PATH)
    result = subprocess.run(
        ["git", "-C", REGISTRY_PATH, "log", "--diff-filter=A", "--format=%H", "--", rel_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log(f"WARNING: git log failed for {rel_path}: {result.stderr}")
        return None
    commit_map = get_commit_map()
    hash_val = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    if hash_val and hash_val in commit_map:
        return commit_map[hash_val]
    return "unknown"


def find_violation_commit(filepath, attr_key=None, content_substr=None):
    """Determine which commit introduced a violation."""
    if content_substr:
        msg = git_blame_line_content(filepath, content_substr)
        if msg:
            return msg
    if attr_key:
        msg = git_blame_line(filepath, attr_key)
        if msg:
            return msg
    msg = git_file_creation_commit(filepath)
    return msg if msg else "unknown"


def check_references(objects):
    """Check all cross-references across object types."""
    mntner_names = set(objects["mntner"].keys())
    person_names = set(objects["person"].keys())
    autnum_names = set(objects["aut-num"].keys())

    log(f"Reference index: {len(mntner_names)} mntners, {len(person_names)} persons, {len(autnum_names)} aut-nums")

    findings = []

    for obj_type in OBJECT_TYPES:
        for obj_name, attrs in objects[obj_type].items():
            rel_path = f"data/{obj_type}/{obj_name}"
            filepath = os.path.join(DATA_PATH, obj_type, obj_name)

            for ref in get_values(attrs, "mnt-by"):
                if ref and ref not in mntner_names:
                    findings.append({
                        "category": "dangling_mntner",
                        "object": rel_path,
                        "detail": f"mnt-by references non-existent mntner: {ref}",
                        "introduced_in": find_violation_commit(filepath, "mnt-by"),
                    })

            for ref in get_values(attrs, "admin-c"):
                if ref and ref not in person_names:
                    findings.append({
                        "category": "dangling_admin_c",
                        "object": rel_path,
                        "detail": f"admin-c references non-existent person: {ref}",
                        "introduced_in": find_violation_commit(filepath, "admin-c"),
                    })

            for ref in get_values(attrs, "tech-c"):
                if ref and ref not in person_names:
                    findings.append({
                        "category": "dangling_tech_c",
                        "object": rel_path,
                        "detail": f"tech-c references non-existent person: {ref}",
                        "introduced_in": find_violation_commit(filepath, "tech-c"),
                    })

    for route_type in ("route", "route6"):
        for obj_name, attrs in objects[route_type].items():
            rel_path = f"data/{route_type}/{obj_name}"
            filepath = os.path.join(DATA_PATH, route_type, obj_name)
            for ref in get_values(attrs, "origin"):
                if ref and ref not in autnum_names:
                    findings.append({
                        "category": "dangling_origin",
                        "object": rel_path,
                        "detail": f"origin references non-existent aut-num: {ref}",
                        "introduced_in": find_violation_commit(filepath, "origin"),
                    })

    log(f"check_references found {len(findings)} violations")
    for f in findings:
        log(f"  {f['category']}: {f['object']} - {f['detail']}")
    return findings


def check_policy_references(objects):
    """Check that import/export policy lines in aut-num objects reference existing ASes."""
    autnum_names = set(objects["aut-num"].keys())
    findings = []

    for obj_name, attrs in objects["aut-num"].items():
        rel_path = f"data/aut-num/{obj_name}"
        filepath = os.path.join(DATA_PATH, "aut-num", obj_name)

        import_vals = get_values(attrs, "import")
        export_vals = get_values(attrs, "export")
        log(f"  {obj_name}: {len(import_vals)} imports, {len(export_vals)} exports")

        for policy_line in import_vals:
            m = re.search(r"from\s+(AS\d+)", policy_line)
            if m:
                ref_as = m.group(1)
                if ref_as not in autnum_names:
                    commit = find_violation_commit(filepath, content_substr=ref_as)
                    findings.append({
                        "category": "dangling_policy_reference",
                        "object": rel_path,
                        "detail": f"import policy references non-existent aut-num: {ref_as}",
                        "introduced_in": commit,
                    })

        for policy_line in export_vals:
            m = re.search(r"to\s+(AS\d+)", policy_line)
            if m:
                ref_as = m.group(1)
                if ref_as not in autnum_names:
                    commit = find_violation_commit(filepath, content_substr=ref_as)
                    findings.append({
                        "category": "dangling_policy_reference",
                        "object": rel_path,
                        "detail": f"export policy references non-existent aut-num: {ref_as}",
                        "introduced_in": commit,
                    })

    log(f"check_policy_references found {len(findings)} violations")
    for f in findings:
        log(f"  {f['category']}: {f['object']} - {f['detail']}")
    return findings


def parse_inetnum_cidrs(objects):
    """Extract IPv4 networks from inetnum objects with their metadata."""
    nets = []
    for name, attrs in objects["inetnum"].items():
        cidr = attrs.get("cidr", "")
        if isinstance(cidr, list):
            cidr = cidr[0]
        if not cidr:
            continue
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            mnt_by_list = get_values(attrs, "mnt-by")
            mnt_lower_list = get_values(attrs, "mnt-lower")
            nets.append({
                "network": net,
                "cidr": cidr,
                "mnt_by": set(mnt_by_list),
                "mnt_lower": set(mnt_lower_list),
                "name": name,
            })
        except (ValueError, TypeError) as e:
            log(f"WARNING: failed to parse inetnum {name} cidr={cidr}: {e}")
    return nets


def parse_inet6num_cidrs(objects):
    """Extract IPv6 networks from inet6num objects with their metadata."""
    nets = []
    for name, attrs in objects["inet6num"].items():
        cidr = attrs.get("cidr", "")
        if isinstance(cidr, list):
            cidr = cidr[0]
        if not cidr:
            continue
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            mnt_by_list = get_values(attrs, "mnt-by")
            mnt_lower_list = get_values(attrs, "mnt-lower")
            nets.append({
                "network": net,
                "cidr": cidr,
                "mnt_by": set(mnt_by_list),
                "mnt_lower": set(mnt_lower_list),
                "name": name,
            })
        except (ValueError, TypeError) as e:
            log(f"WARNING: failed to parse inet6num {name} cidr={cidr}: {e}")
    return nets


def find_covering_allocation(route_net, allocations):
    """Find the smallest covering allocation for a route network."""
    covering = None
    for alloc in allocations:
        if route_net.subnet_of(alloc["network"]):
            if covering is None or alloc["network"].prefixlen > covering["network"].prefixlen:
                covering = alloc
    return covering


def is_route_authorized(route_mnt_by, covering):
    """Check if a route's maintainer is authorized by the covering allocation."""
    if not covering:
        return False
    authorized_mntners = covering["mnt_by"] | covering["mnt_lower"]
    return route_mnt_by in authorized_mntners


def check_route_allocations(objects):
    """Check that route prefixes are contained in allocated address space."""
    findings = []
    inetnum_allocs = parse_inetnum_cidrs(objects)
    inet6num_allocs = parse_inet6num_cidrs(objects)

    log(f"IPv4 allocations: {len(inetnum_allocs)}, IPv6 allocations: {len(inet6num_allocs)}")

    for obj_name, attrs in objects["route"].items():
        rel_path = f"data/route/{obj_name}"
        filepath = os.path.join(DATA_PATH, "route", obj_name)
        prefix_str = attrs.get("route", "")
        if isinstance(prefix_str, list):
            prefix_str = prefix_str[0]
        try:
            route_net = ipaddress.ip_network(prefix_str, strict=False)
        except (ValueError, TypeError):
            continue
        covering = find_covering_allocation(route_net, inetnum_allocs)
        if not covering:
            findings.append({
                "category": "unallocated_route",
                "object": rel_path,
                "detail": f"route {prefix_str} not contained in any inetnum allocation",
                "introduced_in": find_violation_commit(filepath),
            })

    for obj_name, attrs in objects["route6"].items():
        rel_path = f"data/route6/{obj_name}"
        filepath = os.path.join(DATA_PATH, "route6", obj_name)
        prefix_str = attrs.get("route6", "")
        if isinstance(prefix_str, list):
            prefix_str = prefix_str[0]
        try:
            route_net = ipaddress.ip_network(prefix_str, strict=False)
        except (ValueError, TypeError):
            continue
        covering = find_covering_allocation(route_net, inet6num_allocs)
        if not covering:
            findings.append({
                "category": "unallocated_route6",
                "object": rel_path,
                "detail": f"route6 {prefix_str} not contained in any inet6num allocation",
                "introduced_in": find_violation_commit(filepath),
            })

    log(f"check_route_allocations found {len(findings)} violations")
    for f in findings:
        log(f"  {f['category']}: {f['object']} - {f['detail']}")
    return findings


def check_route_authorization(objects):
    """Check that route maintainers are authorized by covering allocations.

    A route's mnt-by must match the covering allocation's mnt-by or be listed
    in the allocation's mnt-lower. Skip routes with no covering allocation
    (those are caught by check_route_allocations).
    """
    findings = []
    inetnum_allocs = parse_inetnum_cidrs(objects)
    inet6num_allocs = parse_inet6num_cidrs(objects)

    for obj_name, attrs in objects["route"].items():
        rel_path = f"data/route/{obj_name}"
        filepath = os.path.join(DATA_PATH, "route", obj_name)
        prefix_str = attrs.get("route", "")
        if isinstance(prefix_str, list):
            prefix_str = prefix_str[0]
        try:
            route_net = ipaddress.ip_network(prefix_str, strict=False)
        except (ValueError, TypeError):
            continue
        covering = find_covering_allocation(route_net, inetnum_allocs)
        if not covering:
            continue  # Caught by unallocated route check

        route_mnt_by_list = get_values(attrs, "mnt-by")
        for route_mnt in route_mnt_by_list:
            authorized_mntners = covering["mnt_by"] | covering["mnt_lower"]
            if route_mnt not in authorized_mntners:
                alloc_mnt = ", ".join(sorted(covering["mnt_by"]))
                log(f"  Unauthorized: {rel_path} mnt-by={route_mnt}, "
                    f"covering={covering['cidr']} authorized={authorized_mntners}")
                findings.append({
                    "category": "unauthorized_route",
                    "object": rel_path,
                    "detail": (
                        f"route maintainer {route_mnt} not authorized by "
                        f"covering allocation {covering['cidr']} "
                        f"(mnt-by: {alloc_mnt})"
                    ),
                    "introduced_in": find_violation_commit(filepath, "mnt-by"),
                })

    for obj_name, attrs in objects["route6"].items():
        rel_path = f"data/route6/{obj_name}"
        filepath = os.path.join(DATA_PATH, "route6", obj_name)
        prefix_str = attrs.get("route6", "")
        if isinstance(prefix_str, list):
            prefix_str = prefix_str[0]
        try:
            route_net = ipaddress.ip_network(prefix_str, strict=False)
        except (ValueError, TypeError):
            continue
        covering = find_covering_allocation(route_net, inet6num_allocs)
        if not covering:
            continue

        route_mnt_by_list = get_values(attrs, "mnt-by")
        for route_mnt in route_mnt_by_list:
            authorized_mntners = covering["mnt_by"] | covering["mnt_lower"]
            if route_mnt not in authorized_mntners:
                alloc_mnt = ", ".join(sorted(covering["mnt_by"]))
                findings.append({
                    "category": "unauthorized_route6",
                    "object": rel_path,
                    "detail": (
                        f"route6 maintainer {route_mnt} not authorized by "
                        f"covering allocation {covering['cidr']} "
                        f"(mnt-by: {alloc_mnt})"
                    ),
                    "introduced_in": find_violation_commit(filepath, "mnt-by"),
                })

    log(f"check_route_authorization found {len(findings)} violations")
    for f in findings:
        log(f"  {f['category']}: {f['object']} - {f['detail']}")
    return findings


def check_max_length(objects):
    """Check that route prefix lengths do not exceed max-length."""
    findings = []

    for route_type in ("route", "route6"):
        attr_key = route_type
        for obj_name, attrs in objects[route_type].items():
            rel_path = f"data/{route_type}/{obj_name}"
            filepath = os.path.join(DATA_PATH, route_type, obj_name)
            prefix_str = attrs.get(attr_key, "")
            max_len_str = attrs.get("max-length", "")

            if isinstance(prefix_str, list):
                prefix_str = prefix_str[0]
            if isinstance(max_len_str, list):
                max_len_str = max_len_str[0]

            if not prefix_str or not max_len_str:
                continue

            try:
                route_net = ipaddress.ip_network(prefix_str, strict=False)
                max_len = int(max_len_str)
            except (ValueError, TypeError):
                continue

            if route_net.prefixlen > max_len:
                findings.append({
                    "category": "max_length_violation",
                    "object": rel_path,
                    "detail": f"prefix length {route_net.prefixlen} exceeds max-length {max_len}",
                    "introduced_in": find_violation_commit(filepath, "max-length"),
                })

    log(f"check_max_length found {len(findings)} violations")
    for f in findings:
        log(f"  {f['category']}: {f['object']} - {f['detail']}")
    return findings


def compute_usable_hosts(cidr_str):
    """Compute usable hosts for an IPv4 CIDR using sipcalc with Python fallback."""
    try:
        result = subprocess.run(
            ["sipcalc", cidr_str],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if "Addresses in network" in line:
                parts = line.split("-")
                if len(parts) >= 2:
                    total = int(parts[-1].strip())
                    return total - 2
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    # Fallback: compute from prefix length
    net = ipaddress.ip_network(cidr_str, strict=False)
    return net.num_addresses - 2


def build_network_analysis(objects):
    """Build the network analysis section using sipcalc."""
    ipv4_allocs = []
    for name, attrs in sorted(objects["inetnum"].items()):
        cidr = attrs.get("cidr", "")
        if isinstance(cidr, list):
            cidr = cidr[0]
        if not cidr:
            continue
        usable = compute_usable_hosts(cidr)
        ipv4_allocs.append({"cidr": cidr, "usable_hosts": usable})

    total_usable = sum(a["usable_hosts"] for a in ipv4_allocs)

    ipv6_allocs = []
    for name, attrs in sorted(objects["inet6num"].items()):
        cidr = attrs.get("cidr", "")
        if isinstance(cidr, list):
            cidr = cidr[0]
        if not cidr:
            continue
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            ipv6_allocs.append({"cidr": cidr, "prefix_length": net.prefixlen})
        except (ValueError, TypeError):
            pass

    return {
        "ipv4_allocations": ipv4_allocs,
        "total_ipv4_usable_hosts": total_usable,
        "ipv6_allocations": ipv6_allocs,
    }


def build_routing_security(objects):
    """Build the ROA table with authorization status for each route."""
    autnum_names = set(objects["aut-num"].keys())
    inetnum_allocs = parse_inetnum_cidrs(objects)
    inet6num_allocs = parse_inet6num_cidrs(objects)

    roa_entries = []

    for obj_name, attrs in sorted(objects["route"].items()):
        prefix_str = attrs.get("route", "")
        if isinstance(prefix_str, list):
            prefix_str = prefix_str[0]
        origin = attrs.get("origin", "")
        if isinstance(origin, list):
            origin = origin[0]
        max_len_str = attrs.get("max-length", "")
        if isinstance(max_len_str, list):
            max_len_str = max_len_str[0]
        try:
            route_net = ipaddress.ip_network(prefix_str, strict=False)
            max_len = int(max_len_str) if max_len_str else route_net.prefixlen
        except (ValueError, TypeError):
            continue

        covering = find_covering_allocation(route_net, inetnum_allocs)
        route_mnt_list = get_values(attrs, "mnt-by")
        route_mnt = route_mnt_list[0] if route_mnt_list else ""

        authorized = (
            covering is not None
            and is_route_authorized(route_mnt, covering)
            and origin in autnum_names
        )

        roa_entries.append({
            "prefix": prefix_str,
            "origin": origin,
            "max_length": max_len,
            "authorized": authorized,
        })

    for obj_name, attrs in sorted(objects["route6"].items()):
        prefix_str = attrs.get("route6", "")
        if isinstance(prefix_str, list):
            prefix_str = prefix_str[0]
        origin = attrs.get("origin", "")
        if isinstance(origin, list):
            origin = origin[0]
        max_len_str = attrs.get("max-length", "")
        if isinstance(max_len_str, list):
            max_len_str = max_len_str[0]
        try:
            route_net = ipaddress.ip_network(prefix_str, strict=False)
            max_len = int(max_len_str) if max_len_str else route_net.prefixlen
        except (ValueError, TypeError):
            continue

        covering = find_covering_allocation(route_net, inet6num_allocs)
        route_mnt_list = get_values(attrs, "mnt-by")
        route_mnt = route_mnt_list[0] if route_mnt_list else ""

        authorized = (
            covering is not None
            and is_route_authorized(route_mnt, covering)
            and origin in autnum_names
        )

        roa_entries.append({
            "prefix": prefix_str,
            "origin": origin,
            "max_length": max_len,
            "authorized": authorized,
        })

    authorized_count = sum(1 for e in roa_entries if e["authorized"])
    unauthorized_count = sum(1 for e in roa_entries if not e["authorized"])

    return {
        "roa_entries": roa_entries,
        "authorized_count": authorized_count,
        "unauthorized_count": unauthorized_count,
    }


def main():
    log("Starting dn42 registry security audit")
    log(f"Registry path: {REGISTRY_PATH}")
    log(f"Data path: {DATA_PATH}")

    # Verify registry exists
    if not os.path.isdir(DATA_PATH):
        log(f"ERROR: Data directory not found: {DATA_PATH}")
        return 1

    objects = load_registry()

    # Object counts
    object_counts = {}
    for obj_type in OBJECT_TYPES:
        count = len(objects[obj_type])
        object_counts[obj_type] = count
        log(f"  {obj_type}: {count} objects")
        for name in sorted(objects[obj_type].keys()):
            log(f"    - {name}")

    total_objects = sum(object_counts.values())
    log(f"Total objects: {total_objects}")

    # Find violations
    violations = []

    log("\n--- Checking cross-references ---")
    violations.extend(check_references(objects))

    log("\n--- Checking policy references ---")
    violations.extend(check_policy_references(objects))

    log("\n--- Checking route allocations ---")
    violations.extend(check_route_allocations(objects))

    log("\n--- Checking route authorization ---")
    violations.extend(check_route_authorization(objects))

    log("\n--- Checking max-length constraints ---")
    violations.extend(check_max_length(objects))

    # Sort deterministically
    violations.sort(key=lambda v: (v["category"], v["object"]))

    log(f"\nTotal violations found: {len(violations)}")
    for i, v in enumerate(violations):
        log(f"  [{i+1}] {v['category']}: {v['object']} "
            f"(introduced: {v['introduced_in']})")

    # Network analysis
    network_analysis = build_network_analysis(objects)

    # Routing security / ROA table
    routing_security = build_routing_security(objects)

    report = {
        "registry_summary": {
            "object_counts": object_counts,
            "total_objects": total_objects,
        },
        "violations": violations,
        "network_analysis": network_analysis,
        "routing_security": routing_security,
        "total_violations": len(violations),
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Forensic audit complete: {len(violations)} violations written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
