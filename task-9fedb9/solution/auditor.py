#!/usr/bin/env python3
"""DN42 Registry Schema-Driven Validator, ROA Generator, BIRD2 Config Builder, and AS-SET Expander.

Parses RPSL schema definitions to discover validation rules, validates
all registry objects against those rules plus network allocation policy,
generates a filtered ROA table and BIRD2 configuration, and expands
AS-SET membership transitively with cycle detection.
"""

import os
import re
import json
import csv
import ipaddress
from pathlib import Path
from collections import defaultdict

REGISTRY_PATH = Path("/app/registry/data")
VIOLATIONS_PATH = Path("/app/violations.json")
ROA_PATH = Path("/app/roa_table.csv")
BIRD_CONF_PATH = Path("/app/bird.conf")
EXPANDED_SETS_PATH = Path("/app/expanded_sets.json")


# ============================================================
# RPSL Parsing
# ============================================================

def parse_rpsl(filepath):
    """Parse an RPSL-format file into a dict mapping field names to lists of values."""
    obj = defaultdict(list)
    current_key = None
    with open(filepath) as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("%"):
                continue
            if line[0] in (" ", "\t", "+"):
                if current_key is not None:
                    obj[current_key][-1] += " " + line.lstrip(" \t+")
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip()
                current_key = key
                obj[key].append(value)
    return dict(obj)


# ============================================================
# Schema Parsing
# ============================================================

def parse_schema_key_line(value):
    """Parse a schema 'key:' line value into a field rule dict."""
    parts = value.split()
    if len(parts) < 3:
        return None
    rule = {
        "name": parts[0],
        "required": parts[1] == "required",
        "multiple": parts[2] == "multiple",
        "primary": False,
        "lookup": None,
        "enum": None,
    }
    for p in parts[3:]:
        if p == "primary":
            rule["primary"] = True
        elif p.startswith("lookup="):
            rule["lookup"] = p.split("=", 1)[1]
        elif p.startswith("enum="):
            rule["enum"] = p.split("=", 1)[1].split(",")
    return rule


def load_schemas(schema_dir):
    """Load all schema definitions. Returns dict: type_name -> list of field rules."""
    schemas = {}
    if not schema_dir.is_dir():
        return schemas
    for f in sorted(os.listdir(schema_dir)):
        fp = schema_dir / f
        if not fp.is_file():
            continue
        obj = parse_rpsl(fp)
        ref = obj.get("ref", [None])[0]
        if ref and ref.startswith("dn42."):
            type_name = ref.split(".", 1)[1]
            rules = []
            for kv in obj.get("key", []):
                rule = parse_schema_key_line(kv)
                if rule:
                    rules.append(rule)
            schemas[type_name] = rules
    return schemas


# ============================================================
# Policy Parsing
# ============================================================

def load_policy(policy_dir):
    """Load allocation policy. Returns dict with ranges and community values."""
    policy = {
        "ipv4_range": None,
        "ipv6_range": None,
        "roa_community_valid": None,
        "roa_community_invalid": None,
        "roa_community_unknown": None,
    }
    policy_file = policy_dir / "dn42-policy"
    if not policy_file.exists():
        return policy
    obj = parse_rpsl(policy_file)
    if "ipv4-range" in obj:
        try:
            policy["ipv4_range"] = ipaddress.ip_network(obj["ipv4-range"][0], strict=False)
        except ValueError:
            pass
    if "ipv6-range" in obj:
        try:
            policy["ipv6_range"] = ipaddress.ip_network(obj["ipv6-range"][0], strict=False)
        except ValueError:
            pass
    if "roa-community-valid" in obj:
        policy["roa_community_valid"] = obj["roa-community-valid"][0].strip()
    if "roa-community-invalid" in obj:
        policy["roa_community_invalid"] = obj["roa-community-invalid"][0].strip()
    if "roa-community-unknown" in obj:
        policy["roa_community_unknown"] = obj["roa-community-unknown"][0].strip()
    return policy


# ============================================================
# Registry Loading
# ============================================================

def load_registry(base_path, type_names):
    """Load all registry objects for the given type names."""
    registry = {}
    for tn in type_names:
        type_dir = base_path / tn
        registry[tn] = {}
        if not type_dir.is_dir():
            continue
        for fname in sorted(os.listdir(type_dir)):
            fpath = type_dir / fname
            if fpath.is_file():
                registry[tn][fname] = parse_rpsl(fpath)
    return registry


# ============================================================
# Schema Validation
# ============================================================

def validate_schema(registry, schemas):
    """Validate all objects against their schemas. Returns list of violations."""
    violations = []
    for type_name, rules in schemas.items():
        objects = registry.get(type_name, {})
        for obj_name, obj in objects.items():
            for rule in rules:
                field = rule["name"]
                values = obj.get(field, [])

                # Check required fields
                if rule["required"] and not values:
                    violations.append({
                        "object_type": type_name,
                        "object_name": obj_name,
                        "field": field,
                        "rule": "missing_required",
                        "message": f"Required field '{field}' is missing",
                    })
                    continue

                if not values:
                    continue

                # Check enum constraints
                if rule["enum"]:
                    for val in values:
                        if val not in rule["enum"]:
                            violations.append({
                                "object_type": type_name,
                                "object_name": obj_name,
                                "field": field,
                                "rule": "invalid_enum",
                                "message": f"Value '{val}' not in allowed values {rule['enum']}",
                            })

                # Check lookup references
                if rule["lookup"]:
                    lookup_type = rule["lookup"].split(".", 1)[1] if "." in rule["lookup"] else rule["lookup"]
                    lookup_objects = registry.get(lookup_type, {})
                    for val in values:
                        if val not in lookup_objects:
                            violations.append({
                                "object_type": type_name,
                                "object_name": obj_name,
                                "field": field,
                                "rule": "broken_lookup",
                                "message": f"Reference '{val}' not found in {lookup_type}/",
                            })

    return violations


# ============================================================
# Policy Validation
# ============================================================

def validate_ip_ranges(registry, policy):
    """Check inetnum/inet6num allocations are within valid dn42 ranges."""
    violations = []

    if policy["ipv4_range"]:
        for obj_name, obj in registry.get("inetnum", {}).items():
            cidr_vals = obj.get("cidr", [])
            if cidr_vals:
                try:
                    net = ipaddress.ip_network(cidr_vals[0], strict=False)
                    if not net.subnet_of(policy["ipv4_range"]):
                        violations.append({
                            "object_type": "inetnum",
                            "object_name": obj_name,
                            "field": "cidr",
                            "rule": "out_of_range",
                            "message": f"{net} is outside valid range {policy['ipv4_range']}",
                        })
                except ValueError:
                    pass

    if policy["ipv6_range"]:
        for obj_name, obj in registry.get("inet6num", {}).items():
            cidr_vals = obj.get("cidr", [])
            if cidr_vals:
                try:
                    net = ipaddress.ip_network(cidr_vals[0], strict=False)
                    if not net.subnet_of(policy["ipv6_range"]):
                        violations.append({
                            "object_type": "inet6num",
                            "object_name": obj_name,
                            "field": "cidr",
                            "rule": "out_of_range",
                            "message": f"{net} is outside valid range {policy['ipv6_range']}",
                        })
                except ValueError:
                    pass

    return violations


def validate_overlaps(registry):
    """Detect overlapping inetnum and inet6num allocations."""
    violations = []

    for obj_type, cidr_field in [("inetnum", "cidr"), ("inet6num", "cidr")]:
        nets = []
        for obj_name, obj in registry.get(obj_type, {}).items():
            cidr_vals = obj.get(cidr_field, [])
            if cidr_vals:
                try:
                    net = ipaddress.ip_network(cidr_vals[0], strict=False)
                    nets.append((obj_name, str(net), net))
                except ValueError:
                    pass

        for i in range(len(nets)):
            for j in range(i + 1, len(nets)):
                name_a, cidr_a, net_a = nets[i]
                name_b, cidr_b, net_b = nets[j]
                if net_a.overlaps(net_b):
                    violations.append({
                        "object_type": obj_type,
                        "object_name": f"{name_a},{name_b}",
                        "field": None,
                        "rule": "overlap",
                        "message": f"Overlapping allocations: {cidr_a} and {cidr_b}",
                    })

    return violations


def validate_route_coverage(registry):
    """Check route/route6 prefixes are covered by inetnum/inet6num allocations."""
    violations = []

    ipv4_allocs = []
    for obj_name, obj in registry.get("inetnum", {}).items():
        cidr_vals = obj.get("cidr", [])
        if cidr_vals:
            try:
                ipv4_allocs.append(ipaddress.ip_network(cidr_vals[0], strict=False))
            except ValueError:
                pass

    ipv6_allocs = []
    for obj_name, obj in registry.get("inet6num", {}).items():
        cidr_vals = obj.get("cidr", [])
        if cidr_vals:
            try:
                ipv6_allocs.append(ipaddress.ip_network(cidr_vals[0], strict=False))
            except ValueError:
                pass

    for obj_name, obj in registry.get("route", {}).items():
        route_vals = obj.get("route", [])
        if route_vals:
            try:
                route_net = ipaddress.ip_network(route_vals[0], strict=False)
                if not any(route_net.subnet_of(a) for a in ipv4_allocs):
                    violations.append({
                        "object_type": "route",
                        "object_name": obj_name,
                        "field": "route",
                        "rule": "uncovered_prefix",
                        "message": f"Route {route_net} not covered by any inetnum allocation",
                    })
            except ValueError:
                pass

    for obj_name, obj in registry.get("route6", {}).items():
        route_vals = obj.get("route6", [])
        if route_vals:
            try:
                route_net = ipaddress.ip_network(route_vals[0], strict=False)
                if not any(route_net.subnet_of(a) for a in ipv6_allocs):
                    violations.append({
                        "object_type": "route6",
                        "object_name": obj_name,
                        "field": "route6",
                        "rule": "uncovered_prefix",
                        "message": f"Route {route_net} not covered by any inet6num allocation",
                    })
            except ValueError:
                pass

    return violations


def validate_max_length(registry):
    """Check route/route6 max-length >= prefix length."""
    violations = []

    for route_type, cidr_key in [("route", "route"), ("route6", "route6")]:
        for obj_name, obj in registry.get(route_type, {}).items():
            if "max-length" in obj and cidr_key in obj:
                try:
                    route_net = ipaddress.ip_network(obj[cidr_key][0], strict=False)
                    max_len = int(obj["max-length"][0])
                    if max_len < route_net.prefixlen:
                        violations.append({
                            "object_type": route_type,
                            "object_name": obj_name,
                            "field": "max-length",
                            "rule": "max_length",
                            "message": f"max-length {max_len} < prefix length {route_net.prefixlen} for {route_net}",
                        })
                except (ValueError, IndexError):
                    pass

    return violations


def validate_asset_members(registry):
    """Check AS-SET members reference existing aut-num or as-set objects."""
    violations = []
    as_set_names = set(registry.get("as-set", {}).keys())
    aut_num_names = set(registry.get("aut-num", {}).keys())

    for obj_name, obj in registry.get("as-set", {}).items():
        members = obj.get("members", [])
        for member in members:
            member = member.strip()
            if re.match(r'^AS\d+$', member):
                # ASN reference — check aut-num/
                if member not in aut_num_names:
                    violations.append({
                        "object_type": "as-set",
                        "object_name": obj_name,
                        "field": "members",
                        "rule": "broken_member_reference",
                        "message": f"Member '{member}' not found in aut-num/",
                    })
            elif member.startswith("AS-"):
                # AS-SET reference — check as-set/
                if member not in as_set_names:
                    violations.append({
                        "object_type": "as-set",
                        "object_name": obj_name,
                        "field": "members",
                        "rule": "broken_member_reference",
                        "message": f"Member '{member}' not found in as-set/",
                    })

    return violations


# ============================================================
# AS-SET Expansion
# ============================================================

def expand_asset(name, as_sets, visited=None):
    """Transitively expand an AS-SET to its member AS numbers with cycle detection."""
    if visited is None:
        visited = set()
    if name in visited:
        return set()
    visited.add(name)

    result = set()
    obj = as_sets.get(name)
    if obj is None:
        return result

    members = obj.get("members", [])
    for member in members:
        member = member.strip()
        if re.match(r'^AS\d+$', member):
            result.add(member)
        elif member.startswith("AS-"):
            result.update(expand_asset(member, as_sets, visited))

    return result


def expand_all_assets(registry):
    """Expand all AS-SET objects. Returns dict: set_name -> sorted list of ASNs."""
    as_sets = registry.get("as-set", {})
    expanded = {}
    for name in sorted(as_sets.keys()):
        members = expand_asset(name, as_sets)
        expanded[name] = sorted(members)
    return expanded


# ============================================================
# ROA Generation
# ============================================================

def generate_roa(registry, violations):
    """Generate ROA entries from route/route6 objects that have no violations."""
    violated = set()
    for v in violations:
        obj_name = v["object_name"]
        obj_type = v["object_type"]
        if "," in obj_name:
            for name in obj_name.split(","):
                violated.add((obj_type, name.strip()))
        else:
            violated.add((obj_type, obj_name))

    roa_entries = []

    for route_type, cidr_key in [("route", "route"), ("route6", "route6")]:
        for obj_name, obj in registry.get(route_type, {}).items():
            if (route_type, obj_name) in violated:
                continue

            cidr_vals = obj.get(cidr_key, [])
            origin_vals = obj.get("origin", [])
            if not cidr_vals or not origin_vals:
                continue

            try:
                route_net = ipaddress.ip_network(cidr_vals[0], strict=False)
            except ValueError:
                continue

            prefix = str(route_net)
            asn = origin_vals[0]

            if "max-length" in obj:
                try:
                    max_length = int(obj["max-length"][0])
                except (ValueError, IndexError):
                    max_length = route_net.prefixlen
            else:
                max_length = route_net.prefixlen

            roa_entries.append((prefix, max_length, asn))

    roa_entries.sort(key=lambda x: x[0])
    return roa_entries


# ============================================================
# BIRD2 Configuration Generation
# ============================================================

def generate_bird_conf(roa_entries, policy):
    """Generate a BIRD2 configuration with ROA tables, static entries, and import filters."""
    # Parse community values from policy
    comm_valid = policy.get("roa_community_valid", "64511,1")
    comm_invalid = policy.get("roa_community_invalid", "64511,2")
    comm_unknown = policy.get("roa_community_unknown", "64511,3")

    # Separate ROA entries by address family
    roa4 = []
    roa6 = []
    for prefix, max_len, asn in roa_entries:
        asn_num = asn.replace("AS", "")
        try:
            net = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        if net.version == 4:
            roa4.append((prefix, max_len, asn_num))
        else:
            roa6.append((prefix, max_len, asn_num))

    lines = []
    lines.append("log stderr all;")
    lines.append("router id 172.20.10.1;")
    lines.append("")
    lines.append("roa4 table dn42_roa4;")
    lines.append("roa6 table dn42_roa6;")
    lines.append("")
    lines.append("protocol device {")
    lines.append("}")
    lines.append("")

    # ROA4 static protocol
    lines.append("protocol static roa4_load {")
    lines.append("    roa4 { table dn42_roa4; };")
    for prefix, max_len, asn_num in roa4:
        lines.append(f"    route {prefix} max {max_len} as {asn_num};")
    lines.append("}")
    lines.append("")

    # ROA6 static protocol
    lines.append("protocol static roa6_load {")
    lines.append("    roa6 { table dn42_roa6; };")
    for prefix, max_len, asn_num in roa6:
        lines.append(f"    route {prefix} max {max_len} as {asn_num};")
    lines.append("}")
    lines.append("")

    # IPv4 import filter
    lines.append("filter dn42_import_v4 {")
    lines.append(f"    if (roa_check(dn42_roa4, net, bgp_path.last) = ROA_VALID) then {{")
    lines.append(f"        bgp_community.add(({comm_valid}));")
    lines.append(f"        accept;")
    lines.append(f"    }}")
    lines.append(f"    if (roa_check(dn42_roa4, net, bgp_path.last) = ROA_INVALID) then {{")
    lines.append(f"        bgp_community.add(({comm_invalid}));")
    lines.append(f"        reject;")
    lines.append(f"    }}")
    lines.append(f"    bgp_community.add(({comm_unknown}));")
    lines.append(f"    accept;")
    lines.append("}")
    lines.append("")

    # IPv6 import filter
    lines.append("filter dn42_import_v6 {")
    lines.append(f"    if (roa_check(dn42_roa6, net, bgp_path.last) = ROA_VALID) then {{")
    lines.append(f"        bgp_community.add(({comm_valid}));")
    lines.append(f"        accept;")
    lines.append(f"    }}")
    lines.append(f"    if (roa_check(dn42_roa6, net, bgp_path.last) = ROA_INVALID) then {{")
    lines.append(f"        bgp_community.add(({comm_invalid}));")
    lines.append(f"        reject;")
    lines.append(f"    }}")
    lines.append(f"    bgp_community.add(({comm_unknown}));")
    lines.append(f"    accept;")
    lines.append("}")
    lines.append("")

    # BGP template
    lines.append("template bgp dn42_peer {")
    lines.append("    local as 4242420001;")
    lines.append("    ipv4 {")
    lines.append("        import filter dn42_import_v4;")
    lines.append("        export none;")
    lines.append("    };")
    lines.append("    ipv6 {")
    lines.append("        import filter dn42_import_v6;")
    lines.append("        export none;")
    lines.append("    };")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def main():
    # Load schemas
    schemas = load_schemas(REGISTRY_PATH / "schema")
    print(f"Loaded {len(schemas)} schema definitions")

    # Load policy
    policy = load_policy(REGISTRY_PATH / "policy")
    print(f"Policy IPv4 range: {policy['ipv4_range']}")
    print(f"Policy IPv6 range: {policy['ipv6_range']}")
    print(f"Policy ROA communities: valid={policy['roa_community_valid']}, "
          f"invalid={policy['roa_community_invalid']}, "
          f"unknown={policy['roa_community_unknown']}")

    # Load registry objects
    type_names = list(schemas.keys())
    registry = load_registry(REGISTRY_PATH, type_names)
    total_objects = sum(len(v) for v in registry.values())
    print(f"Loaded {total_objects} objects across {len(type_names)} types")

    # Validate
    violations = []
    violations.extend(validate_schema(registry, schemas))
    violations.extend(validate_ip_ranges(registry, policy))
    violations.extend(validate_overlaps(registry))
    violations.extend(validate_route_coverage(registry))
    violations.extend(validate_max_length(registry))
    violations.extend(validate_asset_members(registry))

    # Write violations
    with open(VIOLATIONS_PATH, "w") as f:
        json.dump(violations, f, indent=2)
    print(f"\n{len(violations)} violations written to {VIOLATIONS_PATH}")

    # Generate and write ROA table
    roa_entries = generate_roa(registry, violations)
    with open(ROA_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["prefix", "max_length", "asn"])
        for prefix, max_length, asn in roa_entries:
            writer.writerow([prefix, max_length, asn])
    print(f"{len(roa_entries)} ROA entries written to {ROA_PATH}")

    # Generate and write BIRD2 config
    bird_conf = generate_bird_conf(roa_entries, policy)
    with open(BIRD_CONF_PATH, "w") as f:
        f.write(bird_conf)
    print(f"BIRD2 configuration written to {BIRD_CONF_PATH}")

    # Validate BIRD2 config with bird -p
    import subprocess
    import shutil
    bird_path = shutil.which("bird") or "/usr/sbin/bird"
    result = subprocess.run(
        [bird_path, "-p", "-c", str(BIRD_CONF_PATH)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("BIRD2 config passed syntax validation")
    else:
        print(f"WARNING: BIRD2 config failed validation:\n{result.stderr}")

    # Expand AS-SETs and write
    expanded = expand_all_assets(registry)
    with open(EXPANDED_SETS_PATH, "w") as f:
        json.dump(expanded, f, indent=2)
    print(f"{len(expanded)} AS-SET expansions written to {EXPANDED_SETS_PATH}")


if __name__ == "__main__":
    main()
