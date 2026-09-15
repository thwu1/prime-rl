#!/usr/bin/env python3
"""
Conda-forge ecosystem health audit solver.

Parses v1 recipe.yaml files with ${{ }} template syntax, builds a host
dependency graph, computes run_exports constraints, discovers version
migrations by comparing recipe versions against global pinning, computes
migration impact, and detects recipe defects.
"""

import json
import re
from collections import defaultdict, deque
from pathlib import Path

import yaml
from packaging.version import Version


BUILD_TOOLS = frozenset({
    "cmake", "ninja", "make", "pkg-config", "autoconf",
    "automake", "libtool", "nasm", "cython", "pythran", "perl",
})


# ── Recipe parsing helpers ──────────────────────────────────────────────


def extract_context(content):
    """Extract context variables from recipe content."""
    context = {}
    match = re.search(r"context:\s*\n((?:[ \t]+\S+:.*\n)*)", content)
    if match:
        for line in match.group(1).strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, val = line.split(":", 1)
                val = val.strip().strip('"').strip("'")
                context[key.strip()] = val
    return context


def preprocess_yaml(content, context):
    """Replace ${{ }} template expressions with parseable YAML values."""

    def replace_template(match):
        expr = match.group(1).strip()

        # Simple context variable reference
        if expr in context:
            return context[expr]

        # compiler('lang')
        if re.match(r"compiler\(", expr):
            lang = re.search(r"compiler\(\s*['\"](\w+)['\"]", expr)
            tag = lang.group(1) if lang else "unknown"
            return f"__COMPILER_{tag}__"

        # pin_subpackage('name', ...) — quoted string
        ps = re.match(r"pin_subpackage\(\s*['\"]([^'\"]+)['\"]", expr)
        if ps:
            return ps.group(1)

        # pin_subpackage(var, ...) — context variable
        ps_var = re.match(r"pin_subpackage\(\s*(\w+)", expr)
        if ps_var:
            return context.get(ps_var.group(1), ps_var.group(1))

        # pin_compatible('name', ...)
        pc = re.match(r"pin_compatible\(\s*['\"]([^'\"]+)['\"]", expr)
        if pc:
            return pc.group(1)

        # pin_compatible(var, ...)
        pc_var = re.match(r"pin_compatible\(\s*(\w+)", expr)
        if pc_var:
            return context.get(pc_var.group(1), pc_var.group(1))

        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", expr)
        return f"__UNKNOWN_{sanitized}__"

    return re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", replace_template, content)


def parse_dep_name(dep_str):
    """Extract package name from dependency string, filtering placeholders."""
    dep_str = dep_str.strip()
    if dep_str.startswith("__COMPILER") or dep_str.startswith("__UNKNOWN"):
        return None
    return dep_str.split()[0]


def parse_dep_constraint(dep_str):
    """Extract (name, constraint_or_None) from a dependency string."""
    dep_str = dep_str.strip()
    if dep_str.startswith("__COMPILER") or dep_str.startswith("__UNKNOWN"):
        return None, None
    parts = dep_str.split(None, 1)
    name = parts[0]
    constraint = parts[1] if len(parts) > 1 else None
    return name, constraint


def extract_package_info(section, context, feedstock_name):
    """Extract package info from a recipe section (single or multi-output)."""
    pkg = section.get("package", {})
    if not pkg:
        return None

    name = pkg.get("name", "")
    version = pkg.get("version", "")
    if not name or name.startswith("__"):
        return None

    reqs = section.get("requirements", {}) or {}
    raw_host = reqs.get("host", []) or []

    host_deps = []
    host_constraints = {}

    for item in raw_host:
        if not isinstance(item, str):
            continue
        dep_name = parse_dep_name(item)
        if dep_name and dep_name not in BUILD_TOOLS:
            host_deps.append(dep_name)
        dep_name2, constraint = parse_dep_constraint(item)
        if dep_name2 and constraint:
            host_constraints[dep_name2] = constraint

    return {
        "name": name,
        "version": version,
        "host_deps": host_deps,
        "host_constraints": host_constraints,
        "feedstock": feedstock_name,
    }


# ── Run-exports extraction from raw content ─────────────────────────────


def extract_run_exports_info(content, context):
    """Extract run_exports info from raw recipe content.

    Returns dict: {package_name: {"valid": bool, "max_pin": str,
                                   "diagnostic": dict_or_none}}
    """
    result = {}
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if stripped.startswith("run_exports:"):
            re_indent = len(lines[i]) - len(lines[i].lstrip())

            # Find associated package name by looking backwards
            pkg_name = None
            for j in range(i - 1, -1, -1):
                name_match = re.match(r"\s*name:\s*(.+)", lines[j])
                if name_match:
                    name_val = name_match.group(1).strip()
                    tmpl = re.search(r"\$\{\{\s*(\w+)\s*\}\}", name_val)
                    if tmpl:
                        name_val = context.get(tmpl.group(1), name_val)
                    pkg_name = name_val
                    break

            # Scan template expressions within the run_exports block
            j = i + 1
            while j < len(lines):
                line_stripped = lines[j].strip()
                if line_stripped == "" or line_stripped.startswith("#"):
                    j += 1
                    continue
                line_indent = len(lines[j]) - len(lines[j].lstrip())
                if line_indent <= re_indent and line_stripped:
                    break

                tmpl = re.search(r"\$\{\{\s*([^}]+)\s*\}\}", lines[j])
                if tmpl and pkg_name:
                    expr = tmpl.group(1).strip()
                    info = _parse_pin_expression(expr, context)
                    result[pkg_name] = info

                j += 1

        i += 1

    return result


def _parse_pin_expression(expr, context):
    """Parse a pin_subpackage/pin_compatible expression from run_exports."""
    func_match = re.match(r"(pin_subpackage|pin_compatible)\(", expr)
    if not func_match:
        return {"valid": False, "max_pin": None, "diagnostic": None}

    # Extract first argument (package reference)
    arg_match = re.match(r"\w+\(\s*([^,)]+)", expr)
    if not arg_match:
        return {"valid": False, "max_pin": None, "diagnostic": None}

    ref_raw = arg_match.group(1).strip()
    is_quoted = ref_raw.startswith("'") or ref_raw.startswith('"')

    if is_quoted:
        is_valid = True
    else:
        # Bare variable — check if defined in context
        is_valid = ref_raw in context

    # Extract max_pin parameter
    pin_match = re.search(r"max_pin\s*=\s*['\"]([^'\"]+)['\"]", expr)
    max_pin = pin_match.group(1) if pin_match else "x"

    if not is_valid:
        return {
            "valid": False,
            "max_pin": max_pin,
            "diagnostic": {
                "issue": "undefined_context_variable",
                "detail": (
                    f"run_exports references undefined context "
                    f"variable '{ref_raw}'"
                ),
            },
        }

    return {"valid": True, "max_pin": max_pin, "diagnostic": None}


# ── Constraint computation ──────────────────────────────────────────────


def compute_constraint(version, max_pin):
    """Compute conda pin constraint string from version and max_pin pattern.

    E.g., version="1.14.4", max_pin="x.x" → ">=1.14.4,<1.15.0a0"
    """
    parts = version.split(".")
    pin_depth = max_pin.count("x")

    if pin_depth > len(parts):
        pin_depth = len(parts)

    components = list(parts[:pin_depth])
    components[-1] = str(int(components[-1]) + 1)
    upper = ".".join(components) + ".0a0"

    return f">={version},<{upper}"


# ── Graph algorithms ────────────────────────────────────────────────────


def topological_sort(graph):
    """Kahn's algorithm. Returns list in valid topological order."""
    in_degree = defaultdict(int)
    adj = defaultdict(list)
    all_nodes = set(graph.keys())

    for node in all_nodes:
        if node not in in_degree:
            in_degree[node] = 0

    for node, deps in graph.items():
        for dep in deps:
            if dep in all_nodes:
                adj[dep].append(node)
                in_degree[node] += 1

    queue = deque(sorted(n for n in all_nodes if in_degree[n] == 0))
    order = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in sorted(adj[node]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(all_nodes):
        raise ValueError("Cycle detected in dependency graph")

    return order


# ── Version checking ────────────────────────────────────────────────────


def check_version_satisfies(constraint_str, version_str):
    """Check if version_str satisfies conda-style version constraint."""
    try:
        ver = Version(version_str)
    except Exception:
        return True

    for part in constraint_str.split(","):
        part = part.strip()
        m = re.match(r"([><=!]+)\s*([\w.]+)", part)
        if not m:
            continue
        op, bound_str = m.groups()
        try:
            bound = Version(bound_str)
        except Exception:
            continue

        if op == ">=" and ver < bound:
            return False
        if op == ">" and ver <= bound:
            return False
        if op == "<=" and ver > bound:
            return False
        if op == "<" and ver >= bound:
            return False
        if op == "==" and ver != bound:
            return False
        if op == "!=" and ver == bound:
            return False

    return True


def version_matches_pin(recipe_version, pin_version):
    """Check if a recipe version matches its global pin.

    A version matches when its leading dot-separated components equal the
    pin's components.  E.g. "1.3.1" matches pin "1.3", but "1.14.4" does
    not match pin "1.14.3".
    """
    recipe_parts = recipe_version.split(".")
    pin_parts = pin_version.split(".")

    for i, pin_comp in enumerate(pin_parts):
        if i >= len(recipe_parts):
            return False
        if recipe_parts[i] != pin_comp:
            return False

    return True


# ── Main analysis ───────────────────────────────────────────────────────


def main():
    feedstock_dir = Path("/app/feedstock")
    output_dir = Path("/app/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # ─── 1. Parse all recipes ───────────────────────────────────────────

    all_packages = {}  # name → info dict
    feedstock_outputs = defaultdict(list)  # feedstock_name → [pkg_names]
    run_exports_raw = {}  # pkg_name → raw run_exports info
    recipe_diagnostics = []

    for recipe_dir in sorted(feedstock_dir.iterdir()):
        if not recipe_dir.is_dir():
            continue
        recipe_file = recipe_dir / "recipe.yaml"
        if not recipe_file.exists():
            continue

        feedstock_name = recipe_dir.name
        with open(recipe_file) as f:
            content = f.read()

        context = extract_context(content)

        # Extract run_exports info from raw content (before preprocessing)
        re_info = extract_run_exports_info(content, context)

        # Preprocess templates and parse YAML
        processed = preprocess_yaml(content, context)
        try:
            data = yaml.safe_load(processed)
        except yaml.YAMLError:
            continue

        if data is None:
            continue

        # Extract package definitions
        if "outputs" in data:
            for output in data["outputs"]:
                pkg = extract_package_info(output, context, feedstock_name)
                if pkg:
                    all_packages[pkg["name"]] = pkg
                    feedstock_outputs[feedstock_name].append(pkg["name"])
        else:
            pkg = extract_package_info(data, context, feedstock_name)
            if pkg:
                all_packages[pkg["name"]] = pkg
                feedstock_outputs[feedstock_name].append(pkg["name"])

        # Process run_exports info
        for pkg_name, info in re_info.items():
            if pkg_name in all_packages:
                if info["valid"]:
                    run_exports_raw[pkg_name] = info
                else:
                    diag = info["diagnostic"].copy()
                    diag["feedstock"] = feedstock_name
                    recipe_diagnostics.append(diag)

    pkg_names = set(all_packages.keys())

    # ─── 2. Build host dependency graph ─────────────────────────────────

    dep_graph = {}
    for name, info in all_packages.items():
        deps = sorted(
            set(d for d in info["host_deps"]
                if d in pkg_names and d not in BUILD_TOOLS)
        )
        dep_graph[name] = deps

    # ─── 3. Compute run_exports analysis ────────────────────────────────

    run_exports_analysis = {}
    for pkg_name, info in sorted(run_exports_raw.items()):
        if pkg_name in all_packages:
            version = all_packages[pkg_name]["version"]
            max_pin = info["max_pin"]
            constraint = compute_constraint(version, max_pin)
            run_exports_analysis[pkg_name] = {
                "max_pin": max_pin,
                "constraint": constraint,
            }

    # ─── 4. Build order (topological sort) ──────────────────────────────

    build_order = topological_sort(dep_graph)

    # ─── 5. Read global pinning config ──────────────────────────────────

    config_path = Path("/app/conda_build_config.yaml")
    with open(config_path) as f:
        global_pins = yaml.safe_load(f)

    # Normalize pin keys: underscores → hyphens
    normalized_pins = {}
    for key, values in global_pins.items():
        if isinstance(key, str) and key.startswith("#"):
            continue
        normalized_key = key.replace("_", "-")
        if isinstance(values, list) and values:
            normalized_pins[normalized_key] = str(values[0])

    # ─── 6. Detect migration ───────────────────────────────────────────

    migration = None
    for pkg_name in sorted(all_packages.keys()):
        info = all_packages[pkg_name]
        if pkg_name in normalized_pins:
            pin_version = normalized_pins[pkg_name]
            recipe_version = info["version"]
            if not version_matches_pin(recipe_version, pin_version):
                feedstock = info["feedstock"]
                all_outputs = sorted(feedstock_outputs[feedstock])
                migration = {
                    "primary_package": pkg_name,
                    "recipe_version": recipe_version,
                    "pinned_version": pin_version,
                    "all_migrated_outputs": all_outputs,
                }
                break  # Report first migration found

    # ─── 7. Impact analysis ─────────────────────────────────────────────

    migrated_outputs = set(
        migration["all_migrated_outputs"]
    ) if migration else set()
    new_version = migration["recipe_version"] if migration else None

    # Directly affected: non-migrated packages with a migrated host dep
    directly_affected = set()
    for name, deps in dep_graph.items():
        if name in migrated_outputs:
            continue
        if any(d in migrated_outputs for d in deps):
            directly_affected.add(name)

    # Transitively affected: reachable through host dep chains
    all_affected = set(directly_affected)
    changed = True
    while changed:
        changed = False
        for name, deps in dep_graph.items():
            if name in migrated_outputs or name in all_affected:
                continue
            if any(d in all_affected for d in deps):
                all_affected.add(name)
                changed = True

    transitively_affected = all_affected - directly_affected

    # ─── 8. Rebuild order ───────────────────────────────────────────────

    affected_subgraph = {}
    for name in all_affected:
        affected_deps = [d for d in dep_graph[name] if d in all_affected]
        affected_subgraph[name] = affected_deps

    rebuild_order = topological_sort(affected_subgraph)

    # ─── 9. Pin conflicts ──────────────────────────────────────────────

    conflicts = []
    for name in sorted(all_affected):
        info = all_packages[name]
        for dep_name, constraint in sorted(info["host_constraints"].items()):
            if dep_name in migrated_outputs and new_version:
                satisfiable = check_version_satisfies(constraint, new_version)
                conflicts.append({
                    "package": name,
                    "dependency": dep_name,
                    "constraint": constraint,
                    "new_version": new_version,
                    "satisfiable": satisfiable,
                })

    # ─── 10. Assemble output ───────────────────────────────────────────

    audit = {
        "packages": sorted(pkg_names),
        "dependency_graph": dict(sorted(dep_graph.items())),
        "run_exports_analysis": dict(sorted(run_exports_analysis.items())),
        "build_order": build_order,
        "migration_detected": migration,
        "directly_affected": sorted(directly_affected),
        "transitively_affected": sorted(transitively_affected),
        "rebuild_order": rebuild_order,
        "pin_conflicts": conflicts,
        "recipe_diagnostics": recipe_diagnostics,
    }

    with open(output_dir / "audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    print(
        f"Audit complete — {len(pkg_names)} packages, "
        f"migration: {migration['primary_package'] if migration else 'none'}, "
        f"{len(all_affected)} affected, "
        f"{len(conflicts)} pin conflicts, "
        f"{len(recipe_diagnostics)} diagnostics"
    )


if __name__ == "__main__":
    main()
