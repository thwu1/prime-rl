#!/usr/bin/env python3
"""Audit solver: independently verifies all SAT competition benchmark results.

Discovers the environment, uses available tools, implements correct DRAT
proof verification (including clause deletion handling), and produces
the audit report.
"""

import json
import os
import subprocess
import sys


def run_tool(args):
    """Run a tool and capture output."""
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=120
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def solve_benchmark(cnf_path):
    """Use solve.py to determine SAT/UNSAT."""
    code, stdout, stderr = run_tool(["python3", "/app/tools/solve.py", cnf_path])
    if code != 0:
        print(f"  solve.py failed: {stderr[:200]}", file=sys.stderr)
        return None
    first_line = stdout.split("\n")[0].strip()
    return first_line  # "SAT" or "UNSAT"


def verify_assignment(cnf_path, assignment_path):
    """Use check_assignment.py to verify an assignment."""
    code, stdout, stderr = run_tool(
        ["python3", "/app/tools/check_assignment.py", cnf_path, assignment_path]
    )
    return stdout.strip() == "VALID"


# ---------- Correct DRAT proof checker ----------

def parse_cnf(filename):
    clauses = []
    current = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("%"):
                continue
            if line.startswith("p"):
                continue
            for token in line.split():
                val = int(token)
                if val == 0:
                    if current:
                        clauses.append(current)
                    current = []
                else:
                    current.append(val)
    if current:
        clauses.append(current)
    return clauses


def parse_proof_with_deletions(filename):
    """Parse DRAT proof, correctly handling deletion lines."""
    steps = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("d"):
                lits = []
                for token in line[1:].strip().split():
                    val = int(token)
                    if val == 0:
                        break
                    lits.append(val)
                steps.append(("d", lits))
            else:
                lits = []
                for token in line.split():
                    val = int(token)
                    if val == 0:
                        break
                    lits.append(val)
                steps.append(("a", lits))
    return steps


def unit_propagate_check(clauses, assignment):
    """Unit propagation. Returns True if conflict found."""
    assignment = dict(assignment)
    changed = True
    while changed:
        changed = False
        for clause in clauses:
            unassigned = []
            satisfied = False
            for lit in clause:
                var = abs(lit)
                if var in assignment:
                    if (lit > 0) == assignment[var]:
                        satisfied = True
                        break
                else:
                    unassigned.append(lit)
            if satisfied:
                continue
            if len(unassigned) == 0:
                return True
            if len(unassigned) == 1:
                var = abs(unassigned[0])
                assignment[var] = unassigned[0] > 0
                changed = True
    return False


def check_rup(clauses, candidate):
    assignment = {}
    for lit in candidate:
        assignment[abs(lit)] = lit < 0
    return unit_propagate_check(clauses, assignment)


def check_rat(clauses, candidate):
    if not candidate:
        return False
    for pivot in candidate:
        neg_pivot = -pivot
        all_ok = True
        for clause in clauses:
            if neg_pivot not in clause:
                continue
            resolvent = set()
            for lit in candidate:
                if lit != pivot:
                    resolvent.add(lit)
            for lit in clause:
                if lit != neg_pivot:
                    resolvent.add(lit)
            if any(-lit in resolvent for lit in resolvent):
                continue
            if not check_rup(clauses, list(resolvent)):
                all_ok = False
                break
        if all_ok:
            return True
    return False


def verify_proof_correct(cnf_path, proof_path):
    """Correct DRAT verification with proper deletion handling."""
    clauses = parse_cnf(cnf_path)
    steps = parse_proof_with_deletions(proof_path)

    clause_db = [list(c) for c in clauses]

    for step_type, lits in steps:
        if step_type == "d":
            target = sorted(lits)
            for j, c in enumerate(clause_db):
                if sorted(c) == target:
                    clause_db.pop(j)
                    break
        else:
            if check_rup(clause_db, lits):
                clause_db.append(list(lits))
            elif check_rat(clause_db, lits):
                clause_db.append(list(lits))
            else:
                return False
    return True


def main():
    base = "/app"

    # Load claimed results
    with open(os.path.join(base, "claimed", "results.json")) as f:
        claimed = json.load(f)

    audit = {}

    for name, info in sorted(claimed.items()):
        cnf_path = os.path.join(base, "benchmarks", f"{name}.cnf")
        cert_path = os.path.join(base, "claimed", info["certificate"])
        claimed_verdict = info["verdict"]

        print(f"Auditing {name}...", file=sys.stderr)

        # Determine correct verdict
        actual_verdict = solve_benchmark(cnf_path)
        original_correct = (actual_verdict == claimed_verdict)

        # Verify certificate
        if claimed_verdict == "SAT":
            certificate_valid = verify_assignment(cnf_path, cert_path)
        else:
            # Use correct DRAT checker (not the buggy one in tools/)
            certificate_valid = verify_proof_correct(cnf_path, cert_path)

        audit[name] = {
            "verdict": actual_verdict,
            "original_correct": original_correct,
            "certificate_valid": certificate_valid,
        }

        status = "OK" if original_correct and certificate_valid else "ISSUE"
        print(f"  verdict={actual_verdict}, claimed={claimed_verdict}, "
              f"cert_valid={certificate_valid} [{status}]", file=sys.stderr)

    # Write audit report
    output_path = os.path.join(base, "audit.json")
    with open(output_path, "w") as f:
        json.dump(audit, f, indent=2)

    print(f"\nAudit written to {output_path}", file=sys.stderr)

    # Summary
    issues = [n for n, a in audit.items()
              if not a["original_correct"] or not a["certificate_valid"]]
    print(f"Found {len(issues)} issues: {issues}", file=sys.stderr)


if __name__ == "__main__":
    main()
