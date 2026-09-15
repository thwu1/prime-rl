
import json
import os
import pytest
from itertools import product


# --- Expected results for resolution proof instances ---
RESOLUTION_EXPECTED = {
    "simple_valid": {
        "valid": True,
        "formula_unsatisfiable": True,
        "total_steps": 7,
        "input_steps": 4,
        "derived_steps": 3,
        "proof_depth": 2,
        "proof_width": 2,
        "is_tree_like": True,
        "trimmed_total_steps": 7,
        "trimmed_derived_steps": 3,
        "essential_inputs": 4,
        "trimmed_proof_depth": 2,
        "trimmed_step_ids": [1, 2, 3, 4, 5, 6, 7],
        "is_regular": True,
    },
    "redundant_valid": {
        "valid": True,
        "formula_unsatisfiable": True,
        "total_steps": 14,
        "input_steps": 6,
        "derived_steps": 8,
        "proof_depth": 4,
        "proof_width": 2,
        "is_tree_like": False,
        "trimmed_total_steps": 10,
        "trimmed_derived_steps": 5,
        "essential_inputs": 5,
        "trimmed_proof_depth": 4,
        "trimmed_step_ids": [1, 2, 3, 4, 5, 7, 10, 12, 13, 14],
        "is_regular": False,
    },
    "complex_valid": {
        "valid": True,
        "formula_unsatisfiable": True,
        "total_steps": 18,
        "input_steps": 9,
        "derived_steps": 9,
        "proof_depth": 6,
        "proof_width": 2,
        "is_tree_like": False,
        "trimmed_total_steps": 10,
        "trimmed_derived_steps": 5,
        "essential_inputs": 5,
        "trimmed_proof_depth": 5,
        "trimmed_step_ids": [1, 2, 3, 4, 5, 10, 11, 12, 13, 14],
        "is_regular": False,
    },
    "phantom_clause": {
        "valid": False,
        "first_error_step": 4,
        "error_type": "phantom_clause",
        "formula_unsatisfiable": False,
    },
    "invalid_reference": {
        "valid": False,
        "first_error_step": 6,
        "error_type": "invalid_reference",
        "formula_unsatisfiable": True,
    },
    "invalid_resolvent": {
        "valid": False,
        "first_error_step": 8,
        "error_type": "invalid_resolvent",
        "formula_unsatisfiable": True,
    },
}

# --- Expected results for interpolation instances (non-interpolant fields) ---
INTERP_EXPECTED = {
    "interp_linear": {
        "valid": True,
        "formula_unsatisfiable": True,
        "total_steps": 12,
        "input_steps": 6,
        "derived_steps": 6,
        "proof_depth": 6,
        "proof_width": 2,
        "is_tree_like": False,
        "trimmed_total_steps": 12,
        "trimmed_derived_steps": 6,
        "essential_inputs": 6,
        "trimmed_proof_depth": 6,
        "trimmed_step_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "is_regular": False,
        "shared_variables": [2, 3],
    },
    "interp_diamond": {
        "valid": True,
        "formula_unsatisfiable": True,
        "total_steps": 15,
        "input_steps": 8,
        "derived_steps": 7,
        "proof_depth": 6,
        "proof_width": 3,
        "is_tree_like": False,
        "trimmed_total_steps": 13,
        "trimmed_derived_steps": 7,
        "essential_inputs": 6,
        "trimmed_proof_depth": 6,
        "trimmed_step_ids": [1, 2, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15],
        "is_regular": False,
        "shared_variables": [2, 3],
    },
}

# --- Expected results for bare formula instances ---
BARE_EXPECTED = {
    "sat_easy": {"satisfiable": True},
    "unsat_bare": {"satisfiable": False},
}


# --- Helper functions for interpolation property verification ---

def parse_cnf_for_test(filepath):
    """Parse a DIMACS CNF file and return list of clauses (each a set of ints)."""
    clauses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            lits = list(map(int, line.split()))
            if lits and lits[-1] == 0:
                lits = lits[:-1]
            clauses.append(set(lits))
    return clauses


def parse_proof_for_test(filepath):
    """Parse a resolution proof file into list of (step_id, clause_set, antecedents)."""
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
            steps.append((step_id, set(clause_lits), tuple(ant_tokens)))
    return steps


def verify_assignment(clauses, assignment):
    """Check that assignment (list of signed literals) satisfies all clauses."""
    assigned = set(assignment)
    for clause in clauses:
        if not clause.intersection(assigned):
            return False
    return True


def all_assignments(variables):
    """Generate all truth assignments over a set of variables."""
    variables = sorted(variables)
    for bits in range(2 ** len(variables)):
        asgn = []
        for i, v in enumerate(variables):
            if (bits >> i) & 1:
                asgn.append(v)
            else:
                asgn.append(-v)
        yield tuple(asgn)


def is_satisfiable_under(clauses, fixed_assignment, free_vars):
    """Check if clauses are satisfiable when some vars are fixed."""
    fixed = set(fixed_assignment)
    for ext in all_assignments(free_vars):
        full = fixed | set(ext)
        if all(any(l in full for l in c) for c in clauses):
            return True
    return False


def verify_interpolant_properties(instance_dir, shared_vars, models):
    """Verify Craig interpolant properties by exhaustive enumeration."""
    # Parse partition
    with open(os.path.join(instance_dir, "partition.json")) as f:
        partition = json.load(f)

    # Parse proof to get clause contents for each input step
    proof_steps = parse_proof_for_test(os.path.join(instance_dir, "proof.res"))
    step_clauses = {sid: clause for sid, clause, ants in proof_steps if not ants}

    a_clauses = [step_clauses[sid] for sid in partition["A"]]
    b_clauses = [step_clauses[sid] for sid in partition["B"]]

    a_vars = set()
    for c in a_clauses:
        a_vars.update(abs(l) for l in c)
    b_vars = set()
    for c in b_clauses:
        b_vars.update(abs(l) for l in c)

    expected_shared = sorted(a_vars & b_vars)
    assert sorted(shared_vars) == expected_shared, (
        f"shared_variables mismatch: got {sorted(shared_vars)}, expected {expected_shared}"
    )

    shared_set = set(shared_vars)
    a_local = a_vars - shared_set
    b_local = b_vars - shared_set

    # Convert models to set of frozensets for lookup
    model_set = set()
    for m in models:
        assert len(m) == len(shared_vars), (
            f"Model {m} does not cover all shared variables {shared_vars}"
        )
        model_vars = set(abs(l) for l in m)
        assert model_vars == shared_set, (
            f"Model {m} variables {model_vars} != shared {shared_set}"
        )
        model_set.add(frozenset(m))

    # Property 1: A-implication — every model of A projected to shared must be in models
    for sigma in all_assignments(shared_set):
        if is_satisfiable_under(a_clauses, sigma, a_local):
            assert frozenset(sigma) in model_set, (
                f"A-implication violated: A is satisfiable under {sigma} "
                f"but interpolant is false there"
            )

    # Property 2: B-separation — no model of B projected to shared is in models
    for sigma in all_assignments(shared_set):
        if frozenset(sigma) in model_set:
            assert not is_satisfiable_under(b_clauses, sigma, b_local), (
                f"B-separation violated: interpolant is true under {sigma} "
                f"but B is satisfiable there"
            )


# --- Fixtures ---

@pytest.fixture(scope="session")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        data = json.load(f)
    assert "results" in data, "results.json must have a top-level 'results' key"
    return data["results"]


# --- Test: all instances present ---

def test_all_instances_present(results):
    """Check that all expected instances are present in the output."""
    all_expected = (
        set(RESOLUTION_EXPECTED.keys())
        | set(INTERP_EXPECTED.keys())
        | set(BARE_EXPECTED.keys())
    )
    for name in all_expected:
        assert name in results, f"Missing instance '{name}' in results"


# ---- Resolution proof instance tests ----

@pytest.mark.parametrize("instance", sorted(RESOLUTION_EXPECTED.keys()))
def test_validity_classification(results, instance):
    assert instance in results, f"Missing instance '{instance}'"
    assert results[instance]["valid"] == RESOLUTION_EXPECTED[instance]["valid"], (
        f"Instance '{instance}': expected valid={RESOLUTION_EXPECTED[instance]['valid']}, "
        f"got valid={results[instance]['valid']}"
    )


@pytest.mark.parametrize("instance", sorted(RESOLUTION_EXPECTED.keys()))
def test_formula_unsatisfiable(results, instance):
    assert instance in results, f"Missing instance '{instance}'"
    assert results[instance]["formula_unsatisfiable"] == RESOLUTION_EXPECTED[instance]["formula_unsatisfiable"], (
        f"Instance '{instance}': expected formula_unsatisfiable="
        f"{RESOLUTION_EXPECTED[instance]['formula_unsatisfiable']}, "
        f"got {results[instance]['formula_unsatisfiable']}"
    )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if not v["valid"]],
)
def test_error_detection(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    assert result["first_error_step"] == expected["first_error_step"], (
        f"Instance '{instance}': expected first_error_step={expected['first_error_step']}, "
        f"got {result['first_error_step']}"
    )
    assert result["error_type"] == expected["error_type"], (
        f"Instance '{instance}': expected error_type='{expected['error_type']}', "
        f"got '{result['error_type']}'"
    )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if v["valid"]],
)
def test_step_counts(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    for key in ["total_steps", "input_steps", "derived_steps"]:
        assert result[key] == expected[key], (
            f"Instance '{instance}': {key} expected={expected[key]}, got={result[key]}"
        )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if v["valid"]],
)
def test_proof_depth(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    assert result["proof_depth"] == expected["proof_depth"], (
        f"Instance '{instance}': proof_depth expected={expected['proof_depth']}, "
        f"got={result['proof_depth']}"
    )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if v["valid"]],
)
def test_proof_width(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    assert result["proof_width"] == expected["proof_width"], (
        f"Instance '{instance}': proof_width expected={expected['proof_width']}, "
        f"got={result['proof_width']}"
    )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if v["valid"]],
)
def test_tree_like(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    assert result["is_tree_like"] == expected["is_tree_like"], (
        f"Instance '{instance}': is_tree_like expected={expected['is_tree_like']}, "
        f"got={result['is_tree_like']}"
    )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if v["valid"]],
)
def test_trimming(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    for key in ["trimmed_total_steps", "trimmed_derived_steps", "essential_inputs"]:
        assert result[key] == expected[key], (
            f"Instance '{instance}': {key} expected={expected[key]}, got={result[key]}"
        )
    assert result["trimmed_proof_depth"] == expected["trimmed_proof_depth"], (
        f"Instance '{instance}': trimmed_proof_depth "
        f"expected={expected['trimmed_proof_depth']}, got={result['trimmed_proof_depth']}"
    )
    assert sorted(result["trimmed_step_ids"]) == sorted(expected["trimmed_step_ids"]), (
        f"Instance '{instance}': trimmed_step_ids mismatch. "
        f"Expected={sorted(expected['trimmed_step_ids'])}, "
        f"got={sorted(result['trimmed_step_ids'])}"
    )


@pytest.mark.parametrize(
    "instance",
    [k for k, v in RESOLUTION_EXPECTED.items() if v["valid"]],
)
def test_regularity(results, instance):
    result = results[instance]
    expected = RESOLUTION_EXPECTED[instance]
    assert result["is_regular"] == expected["is_regular"], (
        f"Instance '{instance}': is_regular expected={expected['is_regular']}, "
        f"got={result['is_regular']}"
    )


# ---- Interpolation instance tests ----

@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_validity(results, instance):
    assert instance in results, f"Missing instance '{instance}'"
    assert results[instance]["valid"] is True, (
        f"Instance '{instance}': expected valid=True"
    )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_unsat(results, instance):
    assert results[instance]["formula_unsatisfiable"] is True, (
        f"Instance '{instance}': expected formula_unsatisfiable=True"
    )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_step_counts(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    for key in ["total_steps", "input_steps", "derived_steps"]:
        assert result[key] == expected[key], (
            f"Instance '{instance}': {key} expected={expected[key]}, got={result[key]}"
        )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_depth(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    assert result["proof_depth"] == expected["proof_depth"], (
        f"Instance '{instance}': proof_depth expected={expected['proof_depth']}, "
        f"got={result['proof_depth']}"
    )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_width(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    assert result["proof_width"] == expected["proof_width"], (
        f"Instance '{instance}': proof_width expected={expected['proof_width']}, "
        f"got={result['proof_width']}"
    )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_tree_like(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    assert result["is_tree_like"] == expected["is_tree_like"], (
        f"Instance '{instance}': is_tree_like expected={expected['is_tree_like']}, "
        f"got={result['is_tree_like']}"
    )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_trimming(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    for key in ["trimmed_total_steps", "trimmed_derived_steps", "essential_inputs"]:
        assert result[key] == expected[key], (
            f"Instance '{instance}': {key} expected={expected[key]}, got={result[key]}"
        )
    assert result["trimmed_proof_depth"] == expected["trimmed_proof_depth"]
    assert sorted(result["trimmed_step_ids"]) == sorted(expected["trimmed_step_ids"])


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_regularity(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    assert result["is_regular"] == expected["is_regular"]


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interp_shared_variables(results, instance):
    result = results[instance]
    expected = INTERP_EXPECTED[instance]
    assert sorted(result["shared_variables"]) == sorted(expected["shared_variables"]), (
        f"Instance '{instance}': shared_variables mismatch"
    )


@pytest.mark.parametrize("instance", sorted(INTERP_EXPECTED.keys()))
def test_interpolant_properties(results, instance):
    """Verify the Craig interpolant satisfies A-implication, B-separation,
    and variable restriction by exhaustive enumeration."""
    result = results[instance]
    assert "interpolant_models" in result, (
        f"Instance '{instance}': missing 'interpolant_models' field"
    )
    assert "shared_variables" in result, (
        f"Instance '{instance}': missing 'shared_variables' field"
    )

    instance_dir = f"/app/instances/{instance}"
    verify_interpolant_properties(
        instance_dir,
        result["shared_variables"],
        result["interpolant_models"],
    )


# ---- Bare formula instance tests ----

@pytest.mark.parametrize("instance", sorted(BARE_EXPECTED.keys()))
def test_bare_satisfiability(results, instance):
    assert instance in results, f"Missing instance '{instance}'"
    expected = BARE_EXPECTED[instance]
    assert results[instance]["satisfiable"] == expected["satisfiable"], (
        f"Instance '{instance}': expected satisfiable={expected['satisfiable']}, "
        f"got {results[instance]['satisfiable']}"
    )


def test_sat_easy_solution_valid(results):
    """For the satisfiable bare instance, verify the reported solution satisfies the formula."""
    result = results["sat_easy"]
    assert result["satisfiable"] is True
    assert "solution" in result, "sat_easy must have a 'solution' field"
    solution = result["solution"]
    assert isinstance(solution, list) and len(solution) > 0, "solution must be a non-empty list"

    clauses = parse_cnf_for_test("/app/instances/sat_easy/formula.cnf")
    assert verify_assignment(clauses, solution), (
        f"Reported solution {solution} does not satisfy the formula"
    )


def test_unsat_bare_no_solution(results):
    """For the unsatisfiable bare instance, solution must be null."""
    result = results["unsat_bare"]
    assert result["satisfiable"] is False
    assert result.get("solution") is None, "unsat_bare solution must be null"
