#!/usr/bin/env python3
"""
Mutation testing analyzer — AOR, ROR, CRP operators with subsumption analysis.
"""

import ast
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

# ======================================================================
# Configuration
# ======================================================================

SOURCE_FILE = "/app/src/algorithms.py"
TEST_DIR = "/app/tests"
REPORT_FILE = "/app/analysis_report.json"
MUTANT_TIMEOUT = 30  # seconds per test-suite run

# ======================================================================
# Operator tables
# ======================================================================

OP_SYMBOL = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
    ast.Eq: "==", ast.NotEq: "!=",
}

AOR_MAP = {
    ast.Add:      [ast.Sub],
    ast.Sub:      [ast.Add],
    ast.Mult:     [ast.FloorDiv],
    ast.FloorDiv: [ast.Mult],
    ast.Mod:      [ast.Mult],
}

ROR_MAP = {
    ast.Lt:    [ast.LtE, ast.Gt],
    ast.LtE:   [ast.Lt, ast.GtE],
    ast.Gt:    [ast.GtE, ast.Lt],
    ast.GtE:   [ast.Gt, ast.LtE],
    ast.Eq:    [ast.NotEq],
    ast.NotEq: [ast.Eq],
}


def crp_replacements(val):
    """Return list of replacement values for integer constant *val*."""
    if not isinstance(val, int) or isinstance(val, bool):
        return []
    if val == 0:
        return [1]
    if val == 1:
        return [0]
    return [val + 1]


# ======================================================================
# AST helpers
# ======================================================================

def ordered_walk(node):
    """Pre-order DFS — deterministic traversal order."""
    yield node
    for child in ast.iter_child_nodes(node):
        yield from ordered_walk(child)


def _build_func_map(tree):
    """Return dict  node-id -> enclosing-function-name."""
    result = {}

    def _visit(node, fn):
        result[id(node)] = fn
        if isinstance(node, ast.FunctionDef):
            fn = node.name
        for c in ast.iter_child_nodes(node):
            _visit(c, fn)

    _visit(tree, "<module>")
    return result


# ======================================================================
# Mutation-point collection
# ======================================================================

def _collect_points(source):
    """Return a list of mutation-point dicts from *source*."""
    tree = ast.parse(source)
    fmap = _build_func_map(tree)

    # Tag nodes with sequential IDs in ordered_walk order.
    nid_map = {}
    for idx, node in enumerate(ordered_walk(tree)):
        node._nid = idx
        nid_map[idx] = node

    points = []
    for node in ordered_walk(tree):
        # AOR
        if isinstance(node, ast.BinOp):
            ot = type(node.op)
            if ot in AOR_MAP:
                for rt in AOR_MAP[ot]:
                    points.append(dict(
                        nid=node._nid, node_cls="BinOp",
                        lineno=node.lineno, col=node.col_offset,
                        func=fmap[id(node)],
                        op="AOR", orig=OP_SYMBOL[ot], repl=OP_SYMBOL[rt],
                        _apply=("binop", rt),
                    ))

        # ROR
        if isinstance(node, ast.Compare):
            for ci, cop in enumerate(node.ops):
                ot = type(cop)
                if ot in ROR_MAP:
                    for rt in ROR_MAP[ot]:
                        points.append(dict(
                            nid=node._nid, node_cls="Compare",
                            lineno=node.lineno, col=node.col_offset,
                            func=fmap[id(node)],
                            op="ROR", orig=OP_SYMBOL[ot], repl=OP_SYMBOL[rt],
                            _apply=("compare", ci, rt),
                        ))

        # CRP
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int) and not isinstance(node.value, bool):
                for rv in crp_replacements(node.value):
                    points.append(dict(
                        nid=node._nid, node_cls="Constant",
                        lineno=node.lineno, col=node.col_offset,
                        func=fmap[id(node)],
                        op="CRP", orig=str(node.value), repl=str(rv),
                        _apply=("constant", rv),
                    ))

    return points


# ======================================================================
# Mutant source generation
# ======================================================================

def _make_mutant_source(source, point):
    """Return the mutated source string, or None on failure."""
    tree = ast.parse(source)
    # Re-tag with same IDs
    for idx, node in enumerate(ordered_walk(tree)):
        node._nid = idx

    # Locate target node by nid
    target = None
    for node in ordered_walk(tree):
        if node._nid == point["nid"]:
            target = node
            break
    if target is None:
        return None

    # Apply mutation
    ap = point["_apply"]
    if ap[0] == "binop":
        target.op = ap[1]()
    elif ap[0] == "compare":
        target.ops[ap[1]] = ap[2]()
    elif ap[0] == "constant":
        target.value = ap[1]

    ast.fix_missing_locations(tree)
    try:
        compile(tree, "<mutant>", "exec")  # verify compilable
        return ast.unparse(tree)
    except Exception:
        return None


# ======================================================================
# Test discovery & execution
# ======================================================================

def _discover_tests():
    """Return sorted list of test IDs (pytest format)."""
    r = subprocess.run(
        ["python3", "-m", "pytest", TEST_DIR, "--collect-only", "-q"],
        capture_output=True, text=True, cwd="/app",
    )
    tests = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if "::" in line and "test_" in line:
            if line.startswith("tests/") or line.startswith("test_"):
                tests.append(line)
    return sorted(tests)


def _run_tests(mutant_src, test_ids):
    """Write *mutant_src* to SOURCE_FILE, run pytest, return {tid: killed}."""
    xml_path = "/tmp/_mut_results.xml"
    if os.path.exists(xml_path):
        os.remove(xml_path)

    with open(SOURCE_FILE, "w") as f:
        f.write(mutant_src)

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    try:
        subprocess.run(
            ["python3", "-m", "pytest", TEST_DIR,
             f"--junitxml={xml_path}", "--tb=no", "-q"],
            capture_output=True, text=True,
            timeout=MUTANT_TIMEOUT, cwd="/app", env=env,
        )
    except subprocess.TimeoutExpired:
        return {t: True for t in test_ids}

    if not os.path.exists(xml_path):
        return {t: True for t in test_ids}

    results = {}
    try:
        xtree = ET.parse(xml_path)
        for tc in xtree.iter("testcase"):
            name = tc.get("name", "")
            failed = (len(tc.findall("failure")) > 0
                      or len(tc.findall("error")) > 0)
            for tid in test_ids:
                if tid.endswith("::" + name):
                    results[tid] = failed
                    break
    except ET.ParseError:
        return {t: True for t in test_ids}

    # Tests not found in XML → assume killed
    for tid in test_ids:
        if tid not in results:
            results[tid] = True

    return results


# ======================================================================
# Analysis functions
# ======================================================================

def _kill_sets(km):
    """Return {mid: frozenset of killing test IDs}."""
    return {mid: frozenset(t for t, v in row.items() if v == 1)
            for mid, row in km.items()}


def _compute_subsumption(ks):
    """Return (relations, minimal_set)."""
    killable = {m for m, s in ks.items() if s}
    relations = []
    subsumed = set()
    for m1 in sorted(killable):
        for m2 in sorted(killable):
            if m1 != m2 and ks[m1] < ks[m2]:
                relations.append([m1, m2])
                subsumed.add(m2)
    minimal = sorted(killable - subsumed)
    return relations, minimal


def _compute_reduced_relations(ks):
    """Compute Hasse diagram (transitive reduction) of the subsumption order."""
    killable = {m for m, s in ks.items() if s}
    # Collect all subsumption pairs
    all_pairs = []
    for m1 in sorted(killable):
        for m2 in sorted(killable):
            if m1 != m2 and ks[m1] < ks[m2]:
                all_pairs.append((m1, m2))

    # Keep only immediate edges (no intermediate mutant)
    reduced = []
    for m1, m2 in all_pairs:
        has_intermediate = False
        for m3 in killable:
            if m3 != m1 and m3 != m2 and ks[m1] < ks[m3] < ks[m2]:
                has_intermediate = True
                break
        if not has_intermediate:
            reduced.append([m1, m2])
    return reduced


def _dynamic_equivalences(km):
    """Return list of [m1, m2] pairs with identical non-empty kill vectors."""
    test_ids = sorted(next(iter(km.values())).keys()) if km else []
    groups = defaultdict(list)
    for mid, row in km.items():
        vec = tuple(row[t] for t in test_ids)
        if any(v == 1 for v in vec):
            groups[vec].append(mid)
    pairs = []
    for mids in groups.values():
        mids_s = sorted(mids)
        for i in range(len(mids_s)):
            for j in range(i + 1, len(mids_s)):
                pairs.append([mids_s[i], mids_s[j]])
    return pairs


def _minimal_test_set(km):
    """Greedy set cover; ties broken alphabetically."""
    killable = {m for m, row in km.items() if any(v == 1 for v in row.values())}
    if not killable:
        return []
    test_ids = sorted(next(iter(km.values())).keys())
    uncovered = set(killable)
    remaining = set(test_ids)
    selected = []
    while uncovered and remaining:
        best_t, best_n = None, -1
        for t in sorted(remaining):
            n = sum(1 for m in uncovered if km[m][t] == 1)
            if n > best_n:
                best_n = n
                best_t = t
        if best_n == 0:
            break
        selected.append(best_t)
        remaining.remove(best_t)
        uncovered -= {m for m in uncovered if km[m][best_t] == 1}
    return selected


def _operator_stats(mutants):
    stats = defaultdict(lambda: dict(count=0, killed=0, survived=0))
    for m in mutants:
        stats[m["operator"]]["count"] += 1
        stats[m["operator"]][m["status"]] += 1
    for s in stats.values():
        s["score"] = round(s["killed"] / s["count"], 4) if s["count"] else 0.0
    return dict(stats)


# ======================================================================
# Main
# ======================================================================

def main():
    # ---- housekeeping ------------------------------------------------
    for root, dirs, _ in os.walk("/app"):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    with open(SOURCE_FILE) as f:
        original_source = f.read()

    backup = SOURCE_FILE + ".orig_backup"
    shutil.copy2(SOURCE_FILE, backup)

    # ---- collect mutation points -------------------------------------
    points = _collect_points(original_source)
    print(f"[*] Collected {len(points)} mutation points")

    # ---- generate mutant sources -------------------------------------
    mutant_data = []  # list of dicts ready for the report
    mutant_sources = []
    for pt in points:
        ms = _make_mutant_source(original_source, pt)
        if ms is None:
            continue
        mid = f"M{len(mutant_data)+1:03d}"
        mutant_data.append(dict(
            id=mid, operator=pt["op"], function=pt["func"],
            line=pt["lineno"], original=pt["orig"],
            replacement=pt["repl"], status=None, killed_by=[],
        ))
        mutant_sources.append(ms)

    print(f"[*] Generated {len(mutant_data)} compilable mutants")

    # ---- discover tests ----------------------------------------------
    test_ids = _discover_tests()
    print(f"[*] Discovered {len(test_ids)} tests")

    # ---- execute tests against each mutant ---------------------------
    kill_matrix = {}
    try:
        for i, (md, ms) in enumerate(zip(mutant_data, mutant_sources)):
            print(f"  {md['id']}  ({i+1}/{len(mutant_data)}) "
                  f"{md['operator']} {md['original']}->{md['replacement']} "
                  f"in {md['function']}",
                  flush=True)
            results = _run_tests(ms, test_ids)
            killed_by = sorted(t for t, k in results.items() if k)
            md["killed_by"] = killed_by
            md["status"] = "killed" if killed_by else "survived"
            kill_matrix[md["id"]] = {t: (1 if results[t] else 0)
                                     for t in test_ids}
    finally:
        # Always restore original source
        shutil.copy2(backup, SOURCE_FILE)
        if os.path.exists(backup):
            os.remove(backup)

    # ---- analysis ----------------------------------------------------
    killed_n = sum(1 for m in mutant_data if m["status"] == "killed")
    survived_n = len(mutant_data) - killed_n

    ks = _kill_sets(kill_matrix)
    relations, minimal = _compute_subsumption(ks)
    reduced = _compute_reduced_relations(ks)
    dyn_eq = _dynamic_equivalences(kill_matrix)
    min_tests = _minimal_test_set(kill_matrix)
    op_stats = _operator_stats(mutant_data)

    report = dict(
        summary=dict(
            total_mutants=len(mutant_data),
            killed=killed_n,
            survived=survived_n,
            mutation_score=round(killed_n / len(mutant_data), 4),
        ),
        kill_matrix=kill_matrix,
        subsumption=dict(
            relations=relations,
            reduced_relations=reduced,
            minimal_subsuming_set=minimal,
            subsuming_mutation_score=round(
                len(minimal) / len(mutant_data), 4),
        ),
        dynamic_equivalences=dyn_eq,
        minimal_test_set=min_tests,
        operator_stats=op_stats,
        mutants=mutant_data,
    )

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[*] Report written to {REPORT_FILE}")
    print(f"    {killed_n}/{len(mutant_data)} killed  "
          f"(score {report['summary']['mutation_score']})")
    print(f"    Subsuming set size: {len(minimal)}")
    print(f"    Reduced relations: {len(reduced)} / {len(relations)}")
    print(f"    Dynamic-equiv pairs: {len(dyn_eq)}")
    print(f"    Minimal test set size: {len(min_tests)}")


if __name__ == "__main__":
    main()
