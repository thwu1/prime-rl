
import subprocess
import os
import pytest


INSTANCES = [
    ("/app/instances/instance1.wcnf", 1),
    ("/app/instances/instance2.wcnf", 2),
    ("/app/instances/instance3.wcnf", 3),
    ("/app/instances/instance4.wcnf", 6),
    ("/app/instances/instance5.wcnf", 8),
]


def parse_wcnf(filepath):
    """Parse a WCNF file. Returns (nvars, top, hard_clauses, soft_clauses)."""
    nvars = 0
    top = 0
    hard_clauses = []
    soft_clauses = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                nvars = int(parts[2])
                top = int(parts[4])
                continue
            parts = list(map(int, line.split()))
            weight = parts[0]
            lits = parts[1:-1]  # exclude trailing 0
            if weight >= top:
                hard_clauses.append(lits)
            else:
                soft_clauses.append(lits)
    return nvars, top, hard_clauses, soft_clauses


def parse_maxsat_output(output):
    """Parse MaxSAT solver output. Returns (cost, assignment_dict)."""
    cost = None
    assignment = {}
    for line in output.strip().split("\n"):
        line = line.strip()
        if line.startswith("o "):
            cost = int(line.split()[1])
        elif line.startswith("v "):
            tokens = line.split()[1:]
            for tok in tokens:
                val = int(tok)
                if val == 0:
                    break
                var = abs(val)
                assignment[var] = val > 0
    return cost, assignment


def eval_clause(clause, assignment):
    """Check if a clause is satisfied under the given assignment."""
    for lit in clause:
        var = abs(lit)
        val = assignment.get(var, False)
        if (lit > 0 and val) or (lit < 0 and not val):
            return True
    return False


def test_binary_exists():
    """The MaxSAT solver binary must exist and be executable."""
    assert os.path.isfile("/app/maxsat"), "/app/maxsat binary not found"
    assert os.access("/app/maxsat", os.X_OK), "/app/maxsat is not executable"


def test_cadical_library_built():
    """CaDiCaL must have been built from source."""
    assert os.path.isfile(
        "/app/cadical/build/libcadical.a"
    ), "CaDiCaL library not built at /app/cadical/build/libcadical.a"


def test_solver_links_cadical():
    """The solver binary must dynamically or statically link against CaDiCaL."""
    result = subprocess.run(
        ["nm", "/app/maxsat"], capture_output=True, text=True
    )
    combined = result.stdout + result.stderr
    # Check for CaDiCaL symbols (Solver constructor or solve method)
    assert "CaDiCaL" in combined or "cadical" in combined.lower(), (
        "Binary does not appear to link against CaDiCaL library"
    )


@pytest.mark.parametrize("instance,expected_cost", INSTANCES)
def test_optimal_cost(instance, expected_cost):
    """Solver must report the correct optimal cost."""
    result = subprocess.run(
        ["/app/maxsat", instance],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Solver exited with code {result.returncode} on {instance}.\n"
        f"stderr: {result.stderr[:500]}"
    )
    cost, assignment = parse_maxsat_output(result.stdout)
    assert cost is not None, (
        f"Could not parse cost from output:\n{result.stdout[:500]}"
    )
    assert cost == expected_cost, (
        f"Expected optimal cost {expected_cost}, got {cost} on {instance}"
    )


@pytest.mark.parametrize("instance,expected_cost", INSTANCES)
def test_hard_clauses_satisfied(instance, expected_cost):
    """The reported assignment must satisfy all hard clauses."""
    result = subprocess.run(
        ["/app/maxsat", instance],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0
    cost, assignment = parse_maxsat_output(result.stdout)
    assert assignment, f"No assignment parsed from output on {instance}"

    nvars, top, hard_clauses, soft_clauses = parse_wcnf(instance)
    for i, clause in enumerate(hard_clauses):
        assert eval_clause(clause, assignment), (
            f"Hard clause {i} {clause} not satisfied on {instance}"
        )


@pytest.mark.parametrize("instance,expected_cost", INSTANCES)
def test_cost_matches_violations(instance, expected_cost):
    """The reported cost must equal the number of violated soft clauses."""
    result = subprocess.run(
        ["/app/maxsat", instance],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0
    cost, assignment = parse_maxsat_output(result.stdout)
    assert assignment, f"No assignment parsed from output on {instance}"

    nvars, top, hard_clauses, soft_clauses = parse_wcnf(instance)
    violated = sum(1 for cl in soft_clauses if not eval_clause(cl, assignment))
    assert violated == cost, (
        f"Reported cost {cost} but {violated} soft clauses "
        f"are actually violated on {instance}"
    )


@pytest.mark.parametrize("instance,expected_cost", INSTANCES)
def test_all_variables_assigned(instance, expected_cost):
    """The assignment must cover all original variables."""
    result = subprocess.run(
        ["/app/maxsat", instance],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0
    cost, assignment = parse_maxsat_output(result.stdout)

    nvars, top, hard_clauses, soft_clauses = parse_wcnf(instance)
    for v in range(1, nvars + 1):
        assert v in assignment, (
            f"Variable {v} not assigned in output on {instance}"
        )
