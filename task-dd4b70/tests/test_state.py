
import json
import os

import pytest


# Ground truth for the audit
EXPECTED = {
    "simple_unsat": {
        "verdict": "UNSAT",
        "original_correct": True,
        "certificate_valid": True,
    },
    "random_sat": {
        "verdict": "SAT",
        "original_correct": True,
        "certificate_valid": True,
    },
    "pigeon_hole": {
        "verdict": "UNSAT",
        "original_correct": True,
        "certificate_valid": True,
    },
    "graph_color": {
        "verdict": "SAT",
        "original_correct": False,
        "certificate_valid": False,
    },
    "parity_chain": {
        "verdict": "UNSAT",
        "original_correct": False,
        "certificate_valid": False,
    },
    "planning": {
        "verdict": "SAT",
        "original_correct": True,
        "certificate_valid": False,
    },
    "mutex": {
        "verdict": "UNSAT",
        "original_correct": True,
        "certificate_valid": False,
    },
    "horn": {
        "verdict": "SAT",
        "original_correct": True,
        "certificate_valid": True,
    },
}


def load_audit():
    with open("/app/audit.json") as f:
        return json.load(f)


def test_audit_json_exists():
    """audit.json must exist at /app/audit.json."""
    assert os.path.isfile("/app/audit.json"), "Missing /app/audit.json"


def test_audit_all_instances_present():
    """audit.json must have entries for all 8 benchmarks."""
    audit = load_audit()
    for name in EXPECTED:
        assert name in audit, f"Missing benchmark '{name}' in audit.json"


@pytest.mark.parametrize("instance", list(EXPECTED.keys()))
def test_verdict(instance):
    """Each benchmark must have the correct SAT/UNSAT verdict."""
    audit = load_audit()
    expected_v = EXPECTED[instance]["verdict"]
    actual_v = audit[instance]["verdict"]
    assert actual_v == expected_v, (
        f"{instance}: expected verdict={expected_v}, got {actual_v}"
    )


@pytest.mark.parametrize("instance", list(EXPECTED.keys()))
def test_original_correct(instance):
    """Each benchmark must correctly identify whether the claimed result was right."""
    audit = load_audit()
    expected_oc = EXPECTED[instance]["original_correct"]
    actual_oc = audit[instance]["original_correct"]
    assert actual_oc == expected_oc, (
        f"{instance}: expected original_correct={expected_oc}, got {actual_oc}"
    )


@pytest.mark.parametrize("instance", list(EXPECTED.keys()))
def test_certificate_valid(instance):
    """Each benchmark must correctly assess certificate validity."""
    audit = load_audit()
    expected_cv = EXPECTED[instance]["certificate_valid"]
    actual_cv = audit[instance]["certificate_valid"]
    assert actual_cv == expected_cv, (
        f"{instance}: expected certificate_valid={expected_cv}, got {actual_cv}"
    )


# --- Independent verification tests ---

def _parse_cnf(filename):
    """Minimal CNF parser for verification tests."""
    clauses = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p") or line.startswith("%"):
                continue
            lits = []
            for tok in line.split():
                v = int(tok)
                if v == 0:
                    if lits:
                        clauses.append(lits)
                    lits = []
                else:
                    lits.append(v)
    return clauses


def _dpll_solve(clauses, assignment, num_vars):
    """Simple DPLL for independent verification."""
    changed = True
    assignment = dict(assignment)
    while changed:
        changed = False
        for cl in clauses:
            un = []
            sat = False
            for lit in cl:
                v = abs(lit)
                if v in assignment:
                    if (lit > 0) == assignment[v]:
                        sat = True
                        break
                else:
                    un.append(lit)
            if sat:
                continue
            if len(un) == 0:
                return None
            if len(un) == 1:
                assignment[abs(un[0])] = un[0] > 0
                changed = True

    all_sat = True
    for cl in clauses:
        sat = any(abs(l) in assignment and (l > 0) == assignment[abs(l)] for l in cl)
        if not sat:
            all_sat = False
            break
    if all_sat:
        return assignment

    for v in range(1, num_vars + 1):
        if v not in assignment:
            for val in (True, False):
                a2 = dict(assignment)
                a2[v] = val
                r = _dpll_solve(clauses, a2, num_vars)
                if r is not None:
                    return r
            return None
    return None


def test_graph_color_is_sat():
    """Independent verification: graph_color.cnf is satisfiable."""
    clauses = _parse_cnf("/app/benchmarks/graph_color.cnf")
    result = _dpll_solve(clauses, {}, 12)
    assert result is not None, "graph_color.cnf should be SAT"


def test_parity_chain_is_unsat():
    """Independent verification: parity_chain.cnf is unsatisfiable."""
    clauses = _parse_cnf("/app/benchmarks/parity_chain.cnf")
    result = _dpll_solve(clauses, {}, 3)
    assert result is None, "parity_chain.cnf should be UNSAT"


def test_mutex_proof_invalid_with_deletions():
    """Independent verification: mutex.drat is invalid when deletions are applied.

    The proof deletes clauses (-1 2) and (-1 -2), then tries to add (-1).
    Without the deleted clauses, unit propagation cannot derive a conflict,
    so the addition step fails RUP (and RAT). A correct DRAT checker must
    report this proof as invalid.
    """
    # Parse mutex formula
    clauses = _parse_cnf("/app/benchmarks/mutex.cnf")
    clause_db = [list(c) for c in clauses]

    # Parse proof with proper deletion handling
    proof_lines = []
    with open("/app/claimed/proofs/mutex.drat") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("d"):
                lits = [int(t) for t in line[1:].split() if int(t) != 0]
                proof_lines.append(("d", lits))
            else:
                lits = [int(t) for t in line.split() if int(t) != 0]
                proof_lines.append(("a", lits))

    # Process proof with correct deletion semantics
    found_invalid = False
    for step_type, lits in proof_lines:
        if step_type == "d":
            target = sorted(lits)
            for j, c in enumerate(clause_db):
                if sorted(c) == target:
                    clause_db.pop(j)
                    break
        else:
            # RUP check
            assignment = {}
            for lit in lits:
                assignment[abs(lit)] = lit < 0
            conflict = False
            changed = True
            while changed:
                changed = False
                for cl in clause_db:
                    un = []
                    sat = False
                    for l in cl:
                        v = abs(l)
                        if v in assignment:
                            if (l > 0) == assignment[v]:
                                sat = True
                                break
                        else:
                            un.append(l)
                    if sat:
                        continue
                    if len(un) == 0:
                        conflict = True
                        break
                    if len(un) == 1:
                        assignment[abs(un[0])] = un[0] > 0
                        changed = True
                if conflict:
                    break

            if not conflict:
                found_invalid = True
                break
            clause_db.append(list(lits))

    assert found_invalid, (
        "mutex.drat should be INVALID when clause deletions are applied. "
        "A correct DRAT checker must process deletion lines."
    )
