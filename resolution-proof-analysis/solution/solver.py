
"""
Resolution Proof Audit with Craig Interpolation

Handles three instance types:
  1. Resolution proof instances (formula.cnf + proof.res)
  2. Resolution proof instances with A/B partition (+ partition.json)
  3. Bare formula instances (formula.cnf only)
"""

import json
import os
import subprocess
import tempfile


def parse_cnf(filepath):
    """Parse DIMACS CNF into a set of frozensets (clauses) and number of variables."""
    clauses = set()
    num_vars = 0
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                num_vars = int(parts[2])
                continue
            lits = list(map(int, line.split()))
            if lits and lits[-1] == 0:
                lits = lits[:-1]
            clauses.add(frozenset(lits))
    return clauses, num_vars


def parse_proof(filepath):
    """Parse resolution proof file into ordered list of (step_id, clause, antecedents)."""
    steps = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            tokens = list(map(int, line.split()))
            step_id = tokens[0]
            first_zero = tokens.index(0, 1)
            clause_lits = tokens[1:first_zero]
            ant_tokens = tokens[first_zero + 1:]
            if ant_tokens and ant_tokens[-1] == 0:
                ant_tokens = ant_tokens[:-1]
            steps.append((step_id, frozenset(clause_lits), tuple(ant_tokens)))
    return steps


def run_minisat(cnf_path):
    """Run minisat on a CNF file. Returns (is_sat, assignment_or_none)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["minisat", cnf_path, tmp_path],
            capture_output=True, text=True, timeout=120
        )
        with open(tmp_path) as f:
            lines = f.read().strip().split("\n")
        if lines[0] == "SAT":
            assignment = []
            for line in lines[1:]:
                for tok in line.split():
                    val = int(tok)
                    if val != 0:
                        assignment.append(val)
            return True, assignment
        else:
            return False, None
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def validate_proof(steps, formula_clauses):
    """Validate resolution proof. Returns (True, None) or (False, error_dict)."""
    defined = {}
    for step_id, clause, antecedents in steps:
        if not antecedents:
            if clause not in formula_clauses:
                return False, {"first_error_step": step_id, "error_type": "phantom_clause"}
            defined[step_id] = clause
        else:
            if len(antecedents) != 2:
                return False, {"first_error_step": step_id, "error_type": "invalid_resolvent"}
            ant1, ant2 = antecedents
            if ant1 not in defined or ant2 not in defined:
                return False, {"first_error_step": step_id, "error_type": "invalid_reference"}
            c1, c2 = defined[ant1], defined[ant2]
            valid = False
            for lit in c1:
                if -lit in c2:
                    resolvent = (c1 - {lit}) | (c2 - {-lit})
                    if resolvent == clause:
                        valid = True
                        break
            if not valid:
                return False, {"first_error_step": step_id, "error_type": "invalid_resolvent"}
            defined[step_id] = clause
    return True, None


def compute_depths(steps):
    """Compute depth of each step in the proof DAG."""
    depths = {}
    for step_id, clause, antecedents in steps:
        if not antecedents:
            depths[step_id] = 0
        else:
            depths[step_id] = 1 + max(depths[a] for a in antecedents)
    return depths


def compute_width(steps):
    """Compute maximum clause size across all steps."""
    return max(len(clause) for _, clause, _ in steps)


def check_tree_like(steps):
    """Check if every derived step is used as antecedent at most once."""
    use_count = {}
    for _, _, antecedents in steps:
        for a in antecedents:
            use_count[a] = use_count.get(a, 0) + 1
    return all(c <= 1 for c in use_count.values())


def find_pivots(steps):
    """Determine pivot variable and literal for each derived step."""
    defined = {}
    pivots = {}  # step_id -> (pivot_var, literal_in_ant1)
    for step_id, clause, antecedents in steps:
        if not antecedents:
            defined[step_id] = clause
        else:
            c1 = defined[antecedents[0]]
            c2 = defined[antecedents[1]]
            for lit in c1:
                if -lit in c2:
                    resolvent = (c1 - {lit}) | (c2 - {-lit})
                    if resolvent == clause:
                        pivots[step_id] = (abs(lit), lit)
                        break
            defined[step_id] = clause
    return pivots


def trim_proof(steps, empty_clause_step_id):
    """Find minimal sub-derivation to derive the empty clause."""
    step_dict = {sid: (clause, ants) for sid, clause, ants in steps}
    needed = set()
    queue = [empty_clause_step_id]
    while queue:
        sid = queue.pop()
        if sid in needed:
            continue
        needed.add(sid)
        _, ants = step_dict[sid]
        for ant in ants:
            queue.append(ant)
    return sorted(needed)


def check_regularity(steps, empty_clause_id, pivots):
    """Check if the trimmed proof is regular."""
    step_dict = {sid: ants for sid, _, ants in steps}

    def dfs(sid, pivot_set):
        ants = step_dict.get(sid, ())
        if not ants:
            return True
        pivot_info = pivots.get(sid)
        if pivot_info is None:
            return True
        pivot_var = pivot_info[0]
        if pivot_var in pivot_set:
            return False
        new_set = pivot_set | {pivot_var}
        return all(dfs(ant, new_set) for ant in ants)

    return dfs(empty_clause_id, set())


def all_assignments(variables):
    """Generate all truth assignments over a sorted set of variables."""
    variables = sorted(variables)
    n = len(variables)
    for bits in range(2 ** n):
        asgn = tuple(
            v if (bits >> i) & 1 else -v
            for i, v in enumerate(variables)
        )
        yield asgn


def compute_interpolant(steps, partition, a_vars, b_vars):
    """Compute Craig interpolant using Pudlak-style labeling.

    Returns (shared_vars_sorted, models_list).
    """
    shared = a_vars & b_vars
    shared_sorted = sorted(shared)
    a_local = a_vars - shared
    b_local = b_vars - shared

    a_step_set = set(partition["A"])
    all_shared_models = set(all_assignments(shared))

    # Each partial interpolant is a set of frozensets (truth assignments that satisfy it)
    partial = {}
    defined = {}

    for step_id, clause, antecedents in steps:
        if not antecedents:
            # Input clause
            shared_lits = frozenset(l for l in clause if abs(l) in shared)
            if step_id in a_step_set:
                # A-leaf: I = disjunction of shared-variable literals
                if not shared_lits:
                    partial[step_id] = set()  # FALSE
                else:
                    models = set()
                    for sigma in all_shared_models:
                        sigma_set = set(sigma)
                        if any(l in sigma_set for l in shared_lits):
                            models.add(sigma)
                    partial[step_id] = models
            else:
                # B-leaf: I = conjunction of negated shared-variable literals
                if not shared_lits:
                    partial[step_id] = set(all_shared_models)  # TRUE
                else:
                    models = set()
                    for sigma in all_shared_models:
                        sigma_set = set(sigma)
                        if all(-l in sigma_set for l in shared_lits):
                            models.add(sigma)
                    partial[step_id] = models
            defined[step_id] = clause
        else:
            ant1, ant2 = antecedents
            c1 = defined[ant1]
            c2 = defined[ant2]

            # Find pivot
            pivot_lit = None
            for l in c1:
                if -l in c2:
                    resolvent = (c1 - {l}) | (c2 - {-l})
                    if resolvent == clause:
                        pivot_lit = l
                        break

            pivot_var = abs(pivot_lit)

            if pivot_var in a_local:
                # A-local: I(res) = I(ant1) OR I(ant2)
                partial[step_id] = partial[ant1] | partial[ant2]
            elif pivot_var in b_local:
                # B-local: I(res) = I(ant1) AND I(ant2)
                partial[step_id] = partial[ant1] & partial[ant2]
            else:
                # Shared: I(res) = (l OR I(ant1)) AND (NOT l OR I(ant2))
                # where ant1 has pivot_lit, ant2 has -pivot_lit
                models = set()
                for sigma in all_shared_models:
                    sigma_set = set(sigma)
                    l_satisfied = pivot_lit in sigma_set
                    neg_l_satisfied = -pivot_lit in sigma_set
                    in_i1 = sigma in partial[ant1]
                    in_i2 = sigma in partial[ant2]
                    if (l_satisfied or in_i1) and (neg_l_satisfied or in_i2):
                        models.add(sigma)
                partial[step_id] = models

            defined[step_id] = clause

    # Find the empty clause step
    empty_step = None
    for step_id, clause, _ in steps:
        if len(clause) == 0:
            empty_step = step_id
            break

    if empty_step is None:
        return shared_sorted, []

    interp_models = partial[empty_step]
    # Convert to sorted list of sorted lists
    result = []
    for sigma in interp_models:
        model = sorted(sigma, key=abs)
        result.append(model)
    result.sort()
    return shared_sorted, result


def analyze_resolution_instance(instance_dir):
    """Analyze an instance with a resolution proof."""
    cnf_path = os.path.join(instance_dir, "formula.cnf")
    proof_path = os.path.join(instance_dir, "proof.res")
    partition_path = os.path.join(instance_dir, "partition.json")

    formula_clauses, _ = parse_cnf(cnf_path)
    steps = parse_proof(proof_path)

    # Solver-verified unsatisfiability
    is_sat, _ = run_minisat(cnf_path)
    formula_unsat = not is_sat

    # Validate proof
    is_valid, error_info = validate_proof(steps, formula_clauses)
    if not is_valid:
        return {"valid": False, "formula_unsatisfiable": formula_unsat, **error_info}

    # Step counts
    total = len(steps)
    input_count = sum(1 for _, _, a in steps if not a)
    derived_count = total - input_count

    # Depths
    depths = compute_depths(steps)
    proof_depth = max(depths.values())

    # Width
    proof_width = compute_width(steps)

    # Tree-like
    is_tree = check_tree_like(steps)

    # Find first empty clause
    empty_clause_step = None
    for sid, clause, ants in steps:
        if len(clause) == 0:
            empty_clause_step = sid
            break

    if empty_clause_step is None:
        return {"valid": False, "formula_unsatisfiable": formula_unsat,
                "first_error_step": -1, "error_type": "incomplete_proof"}

    # Trim
    trimmed_ids = trim_proof(steps, empty_clause_step)
    trimmed_total = len(trimmed_ids)
    step_dict = {sid: (clause, ants) for sid, clause, ants in steps}
    trimmed_input_count = sum(1 for sid in trimmed_ids if not step_dict[sid][1])
    trimmed_derived_count = trimmed_total - trimmed_input_count

    # Trimmed depth
    trimmed_set = set(trimmed_ids)
    trimmed_depths = {}
    for sid, clause, ants in steps:
        if sid not in trimmed_set:
            continue
        if not ants:
            trimmed_depths[sid] = 0
        else:
            trimmed_depths[sid] = 1 + max(trimmed_depths[a] for a in ants)
    trimmed_proof_depth = trimmed_depths[empty_clause_step]

    # Pivots and regularity
    pivots = find_pivots(steps)
    is_regular = check_regularity(steps, empty_clause_step, pivots)

    result = {
        "valid": True,
        "formula_unsatisfiable": formula_unsat,
        "total_steps": total,
        "input_steps": input_count,
        "derived_steps": derived_count,
        "proof_depth": proof_depth,
        "proof_width": proof_width,
        "is_tree_like": is_tree,
        "trimmed_total_steps": trimmed_total,
        "trimmed_derived_steps": trimmed_derived_count,
        "essential_inputs": trimmed_input_count,
        "trimmed_proof_depth": trimmed_proof_depth,
        "trimmed_step_ids": trimmed_ids,
        "is_regular": is_regular,
    }

    # Craig interpolation (if partition exists)
    if os.path.exists(partition_path):
        with open(partition_path) as f:
            partition = json.load(f)

        # Determine A and B variable sets from the partition
        step_clause_map = {sid: clause for sid, clause, ants in steps if not ants}
        a_vars = set()
        for sid in partition["A"]:
            a_vars.update(abs(l) for l in step_clause_map[sid])
        b_vars = set()
        for sid in partition["B"]:
            b_vars.update(abs(l) for l in step_clause_map[sid])

        shared_vars, interp_models = compute_interpolant(steps, partition, a_vars, b_vars)
        result["shared_variables"] = shared_vars
        result["interpolant_models"] = interp_models

    return result


def analyze_bare_instance(instance_dir):
    """Analyze an instance with only a formula (no proof)."""
    cnf_path = os.path.join(instance_dir, "formula.cnf")
    is_sat, assignment = run_minisat(cnf_path)
    return {
        "satisfiable": is_sat,
        "solution": assignment,
    }


def analyze_instance(instance_dir):
    """Determine instance type and analyze accordingly."""
    proof_path = os.path.join(instance_dir, "proof.res")
    if os.path.exists(proof_path):
        return analyze_resolution_instance(instance_dir)
    else:
        return analyze_bare_instance(instance_dir)


def main():
    instances_dir = "/app/instances"
    results = {}

    for instance_name in sorted(os.listdir(instances_dir)):
        instance_path = os.path.join(instances_dir, instance_name)
        if os.path.isdir(instance_path):
            results[instance_name] = analyze_instance(instance_path)

    output = {"results": results}
    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Analyzed {len(results)} instances. Results written to /app/results.json")


if __name__ == "__main__":
    main()
