
import math
import os
import json
import glob
import pytest


SCENARIO_DIR = "/app/data/scenarios"
INSTANCE_DIR = "/app/data/instances"
OUTPUT_DIR = "/app/output"


def load_scenarios():
    """Discover and load all scenario configurations."""
    scenarios = {}
    for fpath in sorted(glob.glob(os.path.join(SCENARIO_DIR, "*.json"))):
        with open(fpath) as fh:
            cfg = json.load(fh)
        scenarios[cfg["name"]] = cfg
    return scenarios


SCENARIOS = load_scenarios()


def parse_instance(filepath):
    """Parse a facility location instance data file."""
    with open(filepath) as f:
        lines = f.read().strip().split("\n")
    parts = lines[0].split()
    n_fac = int(parts[0])
    n_cust = int(parts[1])

    facilities = []
    for i in range(n_fac):
        p = lines[1 + i].split()
        facilities.append(
            {
                "setup": float(p[0]),
                "cap": int(float(p[1])),
                "x": float(p[2]),
                "y": float(p[3]),
            }
        )

    customers = []
    for j in range(n_cust):
        p = lines[1 + n_fac + j].split()
        customers.append(
            {"demand": int(float(p[0])), "x": float(p[1]), "y": float(p[2])}
        )

    return facilities, customers


def euclidean(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def verify_solution(facilities, customers, assignment):
    """Verify feasibility and compute Euclidean objective value."""
    n = len(facilities)
    m = len(customers)

    if len(assignment) != m:
        return None, f"Expected {m} assignments, got {len(assignment)}"

    for j, fi in enumerate(assignment):
        if fi < 0 or fi >= n:
            return None, f"Customer {j} assigned to invalid facility {fi}"

    load = [0] * n
    for j, fi in enumerate(assignment):
        load[fi] += customers[j]["demand"]

    for i in range(n):
        if load[i] > facilities[i]["cap"]:
            return (
                None,
                f"Facility {i} over capacity: demand {load[i]} > capacity {facilities[i]['cap']}",
            )

    used = set(assignment)
    obj = sum(facilities[i]["setup"] for i in used)
    for j in range(m):
        fi = assignment[j]
        obj += euclidean(
            facilities[fi]["x"], facilities[fi]["y"],
            customers[j]["x"], customers[j]["y"],
        )

    return obj, None


def parse_solution_file(filepath):
    """Parse a solution .sol file into components."""
    with open(filepath) as f:
        sol_lines = f.read().strip().split("\n")

    if len(sol_lines) < 2:
        return None, None, None, f"Solution must have >= 2 lines, got {len(sol_lines)}"

    obj_parts = sol_lines[0].split()
    if len(obj_parts) < 2:
        return None, None, None, f"First line needs >= 2 values, got {len(obj_parts)}"

    try:
        reported_obj = float(obj_parts[0])
    except ValueError:
        return None, None, None, f"Cannot parse objective: {obj_parts[0]}"

    try:
        assignment = list(map(int, sol_lines[1].split()))
    except ValueError:
        return None, None, None, "Cannot parse assignment line as integers"

    # Look for LP_BOUND line
    lp_bound = None
    for line in sol_lines[2:]:
        stripped = line.strip()
        if stripped.startswith("LP_BOUND"):
            parts = stripped.split()
            if len(parts) >= 2:
                try:
                    lp_bound = float(parts[-1])
                except ValueError:
                    pass
            break

    return reported_obj, assignment, lp_bound, None


@pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
def test_solution_exists(scenario_name):
    """Each scenario must have a solution file in the output directory."""
    sol_path = os.path.join(OUTPUT_DIR, f"{scenario_name}.sol")
    assert os.path.exists(sol_path), (
        f"Solution file not found: {sol_path}"
    )


@pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
def test_solution_feasible(scenario_name):
    """Solution must have valid assignments and respect all capacity constraints."""
    cfg = SCENARIOS[scenario_name]
    instance_path = os.path.join(INSTANCE_DIR, cfg["instance_file"])
    sol_path = os.path.join(OUTPUT_DIR, f"{scenario_name}.sol")

    if not os.path.exists(sol_path):
        pytest.skip(f"Solution file missing: {sol_path}")

    facilities, customers = parse_instance(instance_path)
    reported_obj, assignment, _, parse_err = parse_solution_file(sol_path)
    assert parse_err is None, f"Parse error: {parse_err}"

    actual_obj, verify_err = verify_solution(facilities, customers, assignment)
    assert verify_err is None, f"Infeasible solution: {verify_err}"

    tol = max(1.0, actual_obj * 0.002)
    assert abs(actual_obj - reported_obj) < tol, (
        f"Reported objective {reported_obj:.2f} vs computed {actual_obj:.2f}"
    )


@pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
def test_solution_quality(scenario_name):
    """Solution objective must meet scenario quality threshold."""
    cfg = SCENARIOS[scenario_name]
    instance_path = os.path.join(INSTANCE_DIR, cfg["instance_file"])
    sol_path = os.path.join(OUTPUT_DIR, f"{scenario_name}.sol")

    if not os.path.exists(sol_path):
        pytest.skip(f"Solution file missing: {sol_path}")

    facilities, customers = parse_instance(instance_path)
    _, assignment, _, parse_err = parse_solution_file(sol_path)
    assert parse_err is None, f"Parse error: {parse_err}"

    actual_obj, verify_err = verify_solution(facilities, customers, assignment)
    assert verify_err is None, f"Infeasible: {verify_err}"

    threshold = cfg["max_objective"]
    assert actual_obj <= threshold, (
        f"{scenario_name}: objective {actual_obj:.2f} exceeds threshold {threshold}"
    )


@pytest.mark.parametrize(
    "scenario_name",
    [name for name, cfg in load_scenarios().items() if cfg.get("require_lp_bound", False)],
)
def test_lp_bound_present_and_valid(scenario_name):
    """Scenarios requiring LP bounds must include a valid lower bound."""
    cfg = SCENARIOS[scenario_name]
    instance_path = os.path.join(INSTANCE_DIR, cfg["instance_file"])
    sol_path = os.path.join(OUTPUT_DIR, f"{scenario_name}.sol")

    if not os.path.exists(sol_path):
        pytest.skip(f"Solution file missing: {sol_path}")

    facilities, customers = parse_instance(instance_path)
    reported_obj, assignment, lp_bound, parse_err = parse_solution_file(sol_path)
    assert parse_err is None, f"Parse error: {parse_err}"

    assert lp_bound is not None, (
        f"LP_BOUND line missing from {sol_path} — "
        f"scenario requires LP relaxation bound (use glpsol)"
    )
    assert lp_bound > 0, f"LP bound must be positive, got {lp_bound}"

    actual_obj, _ = verify_solution(facilities, customers, assignment)

    # LP bound is a lower bound, so it must be <= objective
    assert lp_bound <= actual_obj + 1.0, (
        f"LP bound {lp_bound:.2f} exceeds objective {actual_obj:.2f} — invalid lower bound"
    )
    # LP bound should be reasonably tight (within factor of 2)
    assert lp_bound >= actual_obj * 0.1, (
        f"LP bound {lp_bound:.2f} is unreasonably low vs objective {actual_obj:.2f}"
    )


def test_solver_nontrivial():
    """Verify a substantive solver implementation exists."""
    candidates = glob.glob("/app/*.py") + glob.glob("/app/pipeline/*.py")
    solver_files = []
    for fp in candidates:
        try:
            with open(fp) as f:
                content = f.read()
            if len(content) > 500:
                lower = content.lower()
                if any(kw in lower for kw in [
                    "facility", "customer", "capacity", "demand",
                    "assignment", "distance", "setup_cost", "setup"
                ]):
                    solver_files.append(fp)
        except Exception:
            pass
    assert len(solver_files) > 0, (
        "No substantive solver implementation found (need >500 bytes, "
        "referencing problem domain concepts)"
    )
