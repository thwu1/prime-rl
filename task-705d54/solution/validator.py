#!/usr/bin/env python3
"""
Type hierarchy validator for a Java-like language.
Checks all 14 hierarchy rules from the JLS specification.

"""

import json
import sys


def load_hierarchy(path):
    with open(path) as f:
        return json.load(f)["types"]


def build_type_map(types):
    return {t["canonical_name"]: t for t in types}


def method_sig(m):
    return (m["name"], tuple(m["parameter_types"]))


def get_supertypes(t):
    return t.get("extends", []) + t.get("implements", [])


# ---------------------------------------------------------------------------
# Cycle detection using DFS with 3-color marking
# ---------------------------------------------------------------------------
def detect_cycles(type_map):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in type_map}
    cyclic = set()

    def dfs(name, path):
        if name not in color:
            return
        color[name] = GRAY
        path.append(name)
        for sup in get_supertypes(type_map[name]):
            if sup not in color:
                continue
            if color[sup] == GRAY:
                idx = path.index(sup)
                for n in path[idx:]:
                    cyclic.add(n)
            elif color[sup] == WHITE:
                dfs(sup, path)
        path.pop()
        color[name] = BLACK

    for name in type_map:
        if color[name] == WHITE:
            dfs(name, [])

    return cyclic


# ---------------------------------------------------------------------------
# Effective method computation (memoized)
# ---------------------------------------------------------------------------
def compute_effective_methods(name, type_map, cyclic, cache):
    """
    Returns dict: method_sig -> method_info dict.
    method_info has keys: name, parameter_types, return_type, modifiers, declared_in.
    Declared methods replace inherited ones with the same signature.
    """
    if name in cache:
        return cache[name]

    if name not in type_map or name in cyclic:
        cache[name] = {}
        return {}

    t = type_map[name]

    # Collect methods from all supertypes
    inherited = {}
    for sup in get_supertypes(t):
        if sup not in type_map:
            continue
        sup_methods = compute_effective_methods(sup, type_map, cyclic, cache)
        for sig, m in sup_methods.items():
            if sig not in inherited:
                inherited[sig] = m

    # Declared methods replace inherited ones
    effective = dict(inherited)
    for m in t.get("methods", []):
        sig = method_sig(m)
        effective[sig] = {**m, "declared_in": name}

    cache[name] = effective
    return effective


# ---------------------------------------------------------------------------
# Collect ALL inherited method variants (for rule 9 conflict detection)
# ---------------------------------------------------------------------------
def collect_inherited_variants(name, type_map, cyclic, eff_cache):
    """
    Returns dict: method_sig -> list of method_info dicts from all supertypes.
    This preserves multiple variants of the same signature from different supertypes
    so we can detect return-type conflicts (Rule 9).
    """
    if name not in type_map or name in cyclic:
        return {}

    t = type_map[name]
    inherited = {}  # sig -> list of method_info

    for sup in get_supertypes(t):
        if sup not in type_map:
            continue
        sup_effective = compute_effective_methods(sup, type_map, cyclic, eff_cache)
        for sig, m in sup_effective.items():
            if sig not in inherited:
                inherited[sig] = []
            # Deduplicate by declaration origin
            if not any(
                e.get("declared_in") == m.get("declared_in") for e in inherited[sig]
            ):
                inherited[sig].append(m)

    return inherited


# ---------------------------------------------------------------------------
# Rule checking
# ---------------------------------------------------------------------------
def check_all_rules(types):
    type_map = build_type_map(types)
    violations = set()

    # --- Rule 6: Cycle detection ---
    cyclic = detect_cycles(type_map)
    for name in cyclic:
        violations.add((name, 6))

    eff_cache = {}

    for t in types:
        name = t["canonical_name"]

        # --- Rule 1: class must not extend interface ---
        if t["kind"] == "class":
            for ext in t.get("extends", []):
                if ext in type_map and type_map[ext]["kind"] == "interface":
                    violations.add((name, 1))

        # --- Rule 2: class must not implement class ---
        if t["kind"] == "class":
            for impl in t.get("implements", []):
                if impl in type_map and type_map[impl]["kind"] == "class":
                    violations.add((name, 2))

        # --- Rule 3: no duplicate interfaces ---
        if t["kind"] == "class":
            impls = t.get("implements", [])
            if len(impls) != len(set(impls)):
                violations.add((name, 3))
        if t["kind"] == "interface":
            exts = t.get("extends", [])
            if len(exts) != len(set(exts)):
                violations.add((name, 3))

        # --- Rule 4: must not extend final class ---
        if t["kind"] == "class":
            for ext in t.get("extends", []):
                if ext in type_map and "final" in type_map[ext].get("modifiers", []):
                    violations.add((name, 4))

        # --- Rule 5: interface must not extend class ---
        if t["kind"] == "interface":
            for ext in t.get("extends", []):
                if ext in type_map and type_map[ext]["kind"] == "class":
                    violations.add((name, 5))

        # --- Rule 7: no duplicate method signatures ---
        sigs = [method_sig(m) for m in t.get("methods", [])]
        if len(sigs) != len(set(sigs)):
            violations.add((name, 7))

        # --- Rule 8: no duplicate constructor parameter types ---
        ctors = t.get("constructors", [])
        ctor_sigs = [tuple(c["parameter_types"]) for c in ctors]
        if len(ctor_sigs) != len(set(ctor_sigs)):
            violations.add((name, 8))

    # --- Rules 9-14: inheritance-dependent checks ---
    # Skip types with structurally invalid extends (R1: class extends interface)
    # since their inheritance chain is semantically broken.
    structurally_invalid = set()
    for t in types:
        name = t["canonical_name"]
        if t["kind"] == "class":
            for ext in t.get("extends", []):
                if ext in type_map and type_map[ext]["kind"] == "interface":
                    structurally_invalid.add(name)

    for t in types:
        name = t["canonical_name"]
        if name in cyclic or name in structurally_invalid:
            continue

        inherited = collect_inherited_variants(name, type_map, cyclic, eff_cache)

        declared = {}
        for m in t.get("methods", []):
            sig = method_sig(m)
            declared[sig] = {**m, "declared_in": name}

        # --- Rule 9: conflicting inherited methods (same sig, different return) ---
        for sig, methods in inherited.items():
            if sig in declared:
                continue  # declared method resolves the conflict
            return_types = {m["return_type"] for m in methods}
            if len(return_types) > 1:
                violations.add((name, 9))

        # --- Rules 11-14: check declared methods against inherited ---
        for sig, m in declared.items():
            if sig not in inherited:
                continue
            for sup_m in inherited[sig]:
                # Rule 11: non-static must not replace static
                if "static" not in m.get("modifiers", []) and "static" in sup_m.get(
                    "modifiers", []
                ):
                    violations.add((name, 11))

                # Rule 12: different return type
                if m["return_type"] != sup_m["return_type"]:
                    violations.add((name, 12))

                # Rule 13: protected must not replace public
                if "protected" in m.get("modifiers", []) and "public" in sup_m.get(
                    "modifiers", []
                ):
                    violations.add((name, 13))

                # Rule 14: must not replace final method
                if "final" in sup_m.get("modifiers", []):
                    violations.add((name, 14))

        # --- Rule 10: concrete class must not contain abstract methods ---
        if t["kind"] == "class" and "abstract" not in t.get("modifiers", []):
            has_abstract = False

            # Check own declared abstract methods
            for m in t.get("methods", []):
                if "abstract" in m.get("modifiers", []):
                    has_abstract = True
                    break

            # Check inherited abstract methods not replaced by declared
            if not has_abstract:
                for sig, methods in inherited.items():
                    if sig in declared:
                        continue  # replaced by declared method
                    for m in methods:
                        if "abstract" in m.get("modifiers", []):
                            has_abstract = True
                            break
                    if has_abstract:
                        break

            if has_abstract:
                violations.add((name, 10))

    return violations


def main():
    types = load_hierarchy("/data/hierarchy.json")
    violations = check_all_rules(types)

    result = []
    for name, rule in sorted(violations):
        result.append({"type": name, "rule": rule})

    with open("/app/violations.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Found {len(result)} violations across {len({r for _, r in violations})} rules")


if __name__ == "__main__":
    main()
