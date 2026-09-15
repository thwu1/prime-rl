#!/usr/bin/env python3
"""Puppet Forge module dependency resolver with backtracking.

"""

import json
import re
import sys
from functools import cmp_to_key


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def parse_version(v):
    return tuple(int(p) for p in v.split("."))


def version_key_desc(v):
    """Sort key for descending version order (highest first)."""
    return tuple(-x for x in parse_version(v))


def satisfies_op(version, op, bound):
    v = parse_version(version)
    b = parse_version(bound)
    if op == ">=":
        return v >= b
    if op == ">":
        return v > b
    if op == "<=":
        return v <= b
    if op == "<":
        return v < b
    if op == "=":
        return v == b
    raise ValueError(f"Unknown operator: {op}")


# ---------------------------------------------------------------------------
# Constraint parsing
# ---------------------------------------------------------------------------

def expand_pessimistic(ver_str):
    """Expand ~> into (lower, upper) constraint strings."""
    parts = ver_str.strip().split(".")
    if len(parts) == 2:
        major, minor = int(parts[0]), int(parts[1])
        return f">= {major}.{minor}.0", f"< {major + 1}.0.0"
    elif len(parts) == 3:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        return f">= {major}.{minor}.{patch}", f"< {major}.{minor + 1}.0"
    else:
        raise ValueError(f"Invalid pessimistic version: {ver_str}")


def parse_constraints(text):
    """Parse a constraint string into a list of (op, version) tuples."""
    if not text:
        return []
    constraints = []
    remaining = text.strip()
    while remaining:
        remaining = remaining.strip()
        if not remaining:
            break
        if remaining.startswith("~>"):
            m = re.match(r"~>\s*(\S+)", remaining)
            if not m:
                raise ValueError(f"Bad pessimistic constraint: {remaining}")
            lo, hi = expand_pessimistic(m.group(1))
            constraints.extend(parse_constraints(lo))
            constraints.extend(parse_constraints(hi))
            remaining = remaining[m.end():]
            continue
        m = re.match(r"(>=|<=|>|<|=)\s*(\S+)", remaining)
        if m:
            constraints.append((m.group(1), m.group(2)))
            remaining = remaining[m.end():]
            continue
        m = re.match(r"(\d+\.\d+\.\d+)", remaining)
        if m:
            constraints.append(("=", m.group(1)))
            remaining = remaining[m.end():]
            continue
        raise ValueError(f"Cannot parse constraint: {remaining}")
    return constraints


def version_satisfies(version, constraints):
    return all(satisfies_op(version, op, bnd) for op, bnd in constraints)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def get_candidates(module, constraints, forge):
    """Return versions of *module* satisfying *constraints*, highest first."""
    if module not in forge:
        return []
    versions = [v for v in forge[module] if version_satisfies(v, constraints)]
    versions.sort(key=version_key_desc)
    return versions


# ---------------------------------------------------------------------------
# Backtracking resolver
# ---------------------------------------------------------------------------

def resolve(pending, constraints, resolved, forge):
    """Return a resolved dict {module: version} or None on failure."""
    if not pending:
        return resolved

    module = pending[0]
    rest = pending[1:]

    # Already resolved — just verify constraints
    if module in resolved:
        if version_satisfies(resolved[module], constraints.get(module, [])):
            return resolve(rest, constraints, resolved, forge)
        return None  # conflict with already-locked version

    if module not in forge:
        return None

    candidates = get_candidates(module, constraints.get(module, []), forge)

    for version in candidates:
        new_resolved = dict(resolved)
        new_resolved[module] = version
        new_constraints = {k: list(v) for k, v in constraints.items()}
        new_pending = list(rest)

        deps = forge[module][version].get("dependencies", [])
        valid = True

        for dep in deps:
            dep_name = dep["name"]
            dep_cs = parse_constraints(dep["version_requirement"])
            new_constraints.setdefault(dep_name, []).extend(dep_cs)

            if dep_name in new_resolved:
                if not version_satisfies(new_resolved[dep_name], dep_cs):
                    valid = False
                    break
            elif dep_name not in new_pending:
                new_pending.append(dep_name)

        if not valid:
            continue

        result = resolve(new_pending, new_constraints, new_resolved, forge)
        if result is not None:
            return result

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    with open("/app/forge_data/modules.json") as f:
        raw = json.load(f)
    # Flatten: {"mod": {"versions": {"1.0.0": ...}}} -> {"mod": {"1.0.0": ...}}
    forge = {name: data["versions"] for name, data in raw["modules"].items()}

    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "error_type": "usage",
                          "message": "Usage: resolver.py spec [spec ...]"}))
        sys.exit(0)

    initial_constraints = {}
    requested = []

    for arg in sys.argv[1:]:
        if ":" in arg:
            name, cstr = arg.split(":", 1)
        else:
            name, cstr = arg, ""
        name = name.strip()

        if name not in forge:
            print(json.dumps({"status": "error", "error_type": "not_found",
                              "message": f"Module '{name}' not found in forge"}))
            sys.exit(0)

        cs = parse_constraints(cstr)
        initial_constraints.setdefault(name, []).extend(cs)
        if name not in requested:
            requested.append(name)

    result = resolve(requested, initial_constraints, {}, forge)

    if result is None:
        print(json.dumps({"status": "error", "error_type": "unsatisfiable",
                          "message": "No valid version combination satisfies all constraints"}))
    else:
        modules = [{"name": n, "version": v} for n, v in sorted(result.items())]
        print(json.dumps({"status": "ok", "modules": modules}))


if __name__ == "__main__":
    main()
