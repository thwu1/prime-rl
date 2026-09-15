#!/usr/bin/env python3
"""
Generate bug_report.json by analyzing solver outputs using minisat for UNSAT verification.
"""

import json
import os
import subprocess
import tempfile


INSTANCES_DIR = "/app/instances"
OUTPUTS_DIR = "/app/outputs"


def parse_wcnf(filepath):
    """Parse WCNF file, auto-detecting format."""
    hard_clauses = []
    soft_clauses = []
    max_var = 0
    top = None

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                tokens = line.split()
                if len(tokens) >= 4 and tokens[1] == "wcnf":
                    top = int(tokens[3])
                break
            else:
                break

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            tokens = line.split()

            if top is not None:
                weight = int(tokens[0])
                lits = []
                for t in tokens[1:]:
                    val = int(t)
                    if val == 0:
                        break
                    lits.append(val)
                    max_var = max(max_var, abs(val))
                if weight >= top:
                    hard_clauses.append(lits)
                else:
                    soft_clauses.append((weight, lits))
            else:
                if tokens[0] == "h":
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    hard_clauses.append(lits)
                else:
                    weight = int(tokens[0])
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    soft_clauses.append((weight, lits))

    return max_var, hard_clauses, soft_clauses


def eval_clause(clause, assignment):
    if not clause:
        return False
    for lit in clause:
        var = abs(lit)
        val = assignment.get(var, 0)
        if (lit > 0 and val == 1) or (lit < 0 and val == 0):
            return True
    return False


def check_sat_minisat(clauses, num_vars):
    """Use minisat to check satisfiability of a set of clauses."""
    import tempfile as tf
    fd, in_path = tf.mkstemp(suffix='.cnf')
    out_path = in_path + ".out"
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(f"p cnf {num_vars} {len(clauses)}\n")
            for clause in clauses:
                f.write(" ".join(str(l) for l in clause) + " 0\n")
        result = subprocess.run(
            ["minisat", in_path, out_path],
            capture_output=True, timeout=30
        )
        return result.returncode == 10
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass
        try:
            os.unlink(out_path)
        except OSError:
            pass


def parse_solver_output(filepath):
    status = None
    cost = None
    v_values = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("c "):
                continue
            if line.startswith("s "):
                status = line[2:].strip()
            elif line.startswith("o "):
                cost = int(line[2:].strip())
            elif line.startswith("v "):
                v_values.extend(line[2:].strip().split())
    assignment = [int(x) for x in v_values] if v_values else None
    return status, cost, assignment


def get_instance_for_output(output_path):
    """Extract instance name from the comment line in solver output."""
    with open(output_path) as f:
        for line in f:
            if line.startswith("c Solver output for instance:"):
                return line.split(":")[-1].strip()
    return None


def classify_output(instance_file, output_file):
    bugs = []
    num_vars, hard_clauses, soft_clauses = parse_wcnf(instance_file)
    status, cost, assignment = parse_solver_output(output_file)

    if status == "UNSATISFIABLE":
        # Use minisat to verify the UNSAT claim
        dimacs_clauses = [list(c) for c in hard_clauses]
        if check_sat_minisat(dimacs_clauses, num_vars):
            bugs.append("false_unsatisfiable")
        return len(bugs) == 0, bugs

    if status in ("OPTIMUM FOUND", "SATISFIABLE"):
        if assignment is None:
            bugs.append("missing_assignment")
            return False, bugs

        asgn_dict = {i + 1: assignment[i] for i in range(len(assignment))}

        for clause in hard_clauses:
            if not eval_clause(clause, asgn_dict):
                bugs.append("hard_clause_violation")
                break

        actual_cost = 0
        for weight, clause in soft_clauses:
            if not eval_clause(clause, asgn_dict):
                actual_cost += weight
        if cost is not None and actual_cost != cost:
            bugs.append("cost_mismatch")

        return len(bugs) == 0, bugs

    bugs.append("invalid_status")
    return False, bugs


def main():
    report = {}

    for fname in sorted(os.listdir(OUTPUTS_DIR)):
        output_path = os.path.join(OUTPUTS_DIR, fname)
        if not os.path.isfile(output_path):
            continue
        inst_name = get_instance_for_output(output_path)
        if inst_name is None:
            continue
        instance_path = os.path.join(INSTANCES_DIR, inst_name)
        if not os.path.isfile(instance_path):
            continue

        valid, bugs = classify_output(instance_path, output_path)
        report[fname] = {"valid": valid, "bugs": bugs}

    with open("/app/bug_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Bug report written to /app/bug_report.json")
    for name, entry in report.items():
        status = "VALID" if entry["valid"] else f"INVALID: {entry['bugs']}"
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
