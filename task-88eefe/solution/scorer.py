#!/usr/bin/env python3
"""
Kernel Patch Quality Scorer — DRIVEBENCH AST-delta scoring methodology.

Usage:
    python3 scorer.py <case_dir>                  # single case → JSON on stdout
    python3 scorer.py <cases_dir> <output_file>   # batch → write JSON file
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict

import pycparser
from pycparser import c_ast

# ---------------------------------------------------------------------------
# AST node-type categories for the five sub-metrics
# ---------------------------------------------------------------------------
FUNCTION_TYPES = {"FuncDef", "FuncDecl"}
CALL_TYPES = {"FuncCall"}
CONTROL_TYPES = {
    "If", "While", "DoWhile", "For", "Switch",
    "Return", "Break", "Continue", "Goto",
}
VARIABLE_TYPES = {"Decl", "Assignment"}

COMPOSITE_WEIGHTS = {
    "ast_similarity": 0.30,
    "function_accuracy": 0.25,
    "call_accuracy": 0.20,
    "node_accuracy": 0.15,
    "variable_accuracy": 0.10,
}

# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def _manual_preprocess(code: str) -> str:
    """Expand simple ``#define NAME VALUE`` macros and strip other directives."""
    lines = code.split("\n")
    defines: dict[str, str] = {}
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#define "):
            rest = stripped[8:]
            parts = rest.split(None, 1)
            if len(parts) >= 2 and "(" not in parts[0]:
                defines[parts[0]] = parts[1]
            elif len(parts) == 1:
                defines[parts[0]] = ""
            continue
        if stripped.startswith("#"):
            continue
        for name in sorted(defines, key=len, reverse=True):
            line = re.sub(r"\b" + re.escape(name) + r"\b", defines[name], line)
        output.append(line)
    return "\n".join(output)


def _preprocess(filepath: str) -> str:
    """Return preprocessed C source for *filepath*."""
    with open(filepath) as fh:
        raw = fh.read()
    has_directives = any(
        l.strip().startswith("#") for l in raw.split("\n") if l.strip()
    )
    if not has_directives:
        return raw
    # Try the system C preprocessor first.
    try:
        proc = subprocess.run(
            ["cpp", "-P", "-nostdinc", "-undef", filepath],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return _manual_preprocess(raw)

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _count_node_types(node) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)

    def _visit(n):
        if n is None:
            return
        counts[n.__class__.__name__] += 1
        for _, child in n.children():
            _visit(child)

    _visit(node)
    return dict(counts)


def _parse_file(filepath: str):
    code = _preprocess(filepath)
    parser = pycparser.CParser()
    return parser.parse(code, filename=filepath)


def _extract_function_names(node) -> set[str]:
    names: set[str] = set()

    def _visit(n):
        if n is None:
            return
        if isinstance(n, c_ast.FuncDef):
            if n.decl and hasattr(n.decl, "name") and n.decl.name:
                names.add(n.decl.name)
        for _, child in n.children():
            _visit(child)

    _visit(node)
    return names


def _extract_type_names(node) -> set[str]:
    names: set[str] = set()

    def _visit(n):
        if n is None:
            return
        if isinstance(n, c_ast.Struct) and n.name:
            names.add(n.name)
        if isinstance(n, c_ast.Typedef) and n.name:
            names.add(n.name)
        for _, child in n.children():
            _visit(child)

    _visit(node)
    return names


def _subtree_counts(node) -> dict[str, int]:
    """Node-type counts for a subtree rooted at *node*."""
    return _count_node_types(node)


def _extract_func_bodies(node) -> dict[str, dict[str, int]]:
    """Return {func_name: subtree_counts} for every FuncDef."""
    bodies: dict[str, dict[str, int]] = {}

    def _visit(n):
        if n is None:
            return
        if isinstance(n, c_ast.FuncDef):
            name = n.decl.name if n.decl and hasattr(n.decl, "name") else None
            if name:
                bodies[name] = _subtree_counts(n)
        for _, child in n.children():
            _visit(child)

    _visit(node)
    return bodies

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _similarity(delta_ref: int, delta_gen: int):
    """Return (sim, weight) or None if both deltas are zero."""
    if delta_ref == 0 and delta_gen == 0:
        return None
    mx = max(abs(delta_ref), abs(delta_gen))
    if mx == 0:
        return None
    sim = 1.0 - abs(delta_ref - delta_gen) / mx
    return sim, mx


def _compute_metric(
    base_counts: dict[str, int],
    ref_counts: dict[str, int],
    cand_counts: dict[str, int],
    type_filter: set[str] | None = None,
) -> float:
    all_types = set(base_counts) | set(ref_counts) | set(cand_counts)
    if type_filter is not None:
        all_types &= type_filter
    weighted_sum = 0.0
    weight_sum = 0.0
    for t in all_types:
        dr = ref_counts.get(t, 0) - base_counts.get(t, 0)
        dg = cand_counts.get(t, 0) - base_counts.get(t, 0)
        result = _similarity(dr, dg)
        if result is None:
            continue
        sim, w = result
        weighted_sum += w * sim
        weight_sum += w
    return weighted_sum / weight_sum if weight_sum else 1.0


def _node_type_details(
    base_counts: dict[str, int],
    ref_counts: dict[str, int],
    cand_counts: dict[str, int],
) -> dict:
    all_types = set(base_counts) | set(ref_counts) | set(cand_counts)
    details: dict = {}
    for t in sorted(all_types):
        dr = ref_counts.get(t, 0) - base_counts.get(t, 0)
        dg = cand_counts.get(t, 0) - base_counts.get(t, 0)
        if dr == 0 and dg == 0:
            continue
        mx = max(abs(dr), abs(dg))
        sim = 1.0 - abs(dr - dg) / mx if mx else 1.0
        details[t] = {
            "delta_ref": dr,
            "delta_gen": dg,
            "similarity": round(sim, 6),
        }
    return details

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify_migration(
    base_counts: dict[str, int],
    ref_counts: dict[str, int],
    base_funcs: set[str],
    ref_funcs: set[str],
) -> str:
    added = ref_funcs - base_funcs
    removed = base_funcs - ref_funcs

    func_delta = abs(ref_counts.get("FuncDef", 0) - base_counts.get("FuncDef", 0))
    param_delta = abs(ref_counts.get("Decl", 0) - base_counts.get("Decl", 0))
    control_delta = sum(
        abs(ref_counts.get(t, 0) - base_counts.get(t, 0))
        for t in CONTROL_TYPES
    )
    total_delta = sum(
        abs(ref_counts.get(t, 0) - base_counts.get(t, 0))
        for t in set(base_counts) | set(ref_counts)
    )

    if total_delta == 0:
        return "rename"

    if added and removed:
        if param_delta > 0:
            return "api_migration"
        return "deprecation"

    if func_delta > 0 and control_delta > func_delta:
        return "structural"

    if param_delta > 0:
        return "api_migration"

    if control_delta > func_delta:
        return "structural"

    return "refactor"

# ---------------------------------------------------------------------------
# Score one case
# ---------------------------------------------------------------------------

def score_case(case_dir: str) -> dict:
    base_ast = _parse_file(os.path.join(case_dir, "base.c"))
    ref_ast = _parse_file(os.path.join(case_dir, "reference.c"))
    cand_ast = _parse_file(os.path.join(case_dir, "candidate.c"))

    bc = _count_node_types(base_ast)
    rc = _count_node_types(ref_ast)
    cc = _count_node_types(cand_ast)

    ast_sim = _compute_metric(bc, rc, cc, None)
    func_acc = _compute_metric(bc, rc, cc, FUNCTION_TYPES)
    call_acc = _compute_metric(bc, rc, cc, CALL_TYPES)
    node_acc = _compute_metric(bc, rc, cc, CONTROL_TYPES)
    var_acc = _compute_metric(bc, rc, cc, VARIABLE_TYPES)

    composite = (
        COMPOSITE_WEIGHTS["ast_similarity"] * ast_sim
        + COMPOSITE_WEIGHTS["function_accuracy"] * func_acc
        + COMPOSITE_WEIGHTS["call_accuracy"] * call_acc
        + COMPOSITE_WEIGHTS["node_accuracy"] * node_acc
        + COMPOSITE_WEIGHTS["variable_accuracy"] * var_acc
    )

    # Symbol analysis
    base_funcs = _extract_function_names(base_ast)
    ref_funcs = _extract_function_names(ref_ast)
    base_types = _extract_type_names(base_ast)
    ref_types = _extract_type_names(ref_ast)
    all_base = base_funcs | base_types
    all_ref = ref_funcs | ref_types

    added = sorted(all_ref - all_base)
    removed = sorted(all_base - all_ref)

    base_bodies = _extract_func_bodies(base_ast)
    ref_bodies = _extract_func_bodies(ref_ast)
    modified = sorted(
        name
        for name in base_funcs & ref_funcs
        if base_bodies.get(name) != ref_bodies.get(name)
    )

    migration_type = _classify_migration(bc, rc, base_funcs, ref_funcs)
    details = _node_type_details(bc, rc, cc)

    return {
        "ast_similarity": round(ast_sim, 6),
        "function_accuracy": round(func_acc, 6),
        "call_accuracy": round(call_acc, 6),
        "node_accuracy": round(node_acc, 6),
        "variable_accuracy": round(var_acc, 6),
        "composite_score": round(composite, 6),
        "migration_type": migration_type,
        "changed_symbols": {
            "added": added,
            "removed": removed,
            "modified": modified,
        },
        "node_type_details": details,
    }

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  scorer.py <case_dir>                  # single case → stdout\n"
            "  scorer.py <cases_dir> <output_file>   # batch → file",
            file=sys.stderr,
        )
        sys.exit(1)

    path = sys.argv[1]

    # Single-case mode: directory contains base.c
    if os.path.isfile(os.path.join(path, "base.c")):
        result = score_case(path)
        print(json.dumps(result, indent=2))
        return

    # Batch mode: process every subdirectory that looks like a case
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    results: dict = {"cases": {}}
    for name in sorted(os.listdir(path)):
        case_dir = os.path.join(path, name)
        if os.path.isdir(case_dir) and os.path.isfile(
            os.path.join(case_dir, "base.c")
        ):
            try:
                results["cases"][name] = score_case(case_dir)
            except Exception as exc:
                print(f"Warning: failed to score {name}: {exc}", file=sys.stderr)

    payload = json.dumps(results, indent=2)
    if output_file:
        with open(output_file, "w") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()
