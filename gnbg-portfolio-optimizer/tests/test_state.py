
import pytest
import sys
import numpy as np

sys.path.insert(0, "/app")


def test_solver_module_exists():
    """Verify solver module is importable and exposes the required interface."""
    from solver import solve

    assert callable(solve), "solve must be callable"


def test_solver_on_sphere():
    """Verify solver works on a trivial 2D sphere function."""
    from solver import solve

    def sphere(x):
        return float(np.sum(np.asarray(x) ** 2))

    best_x, best_f = solve(sphere, 2, [-5.0, -5.0], [5.0, 5.0], 10_000)
    assert best_x is not None, "best_x must not be None"
    assert len(best_x) == 2, "best_x dimension mismatch"
    assert isinstance(best_f, (int, float, np.floating)), "best_f must be numeric"
    assert best_f < 0.01, f"Sphere not solved: best_f={best_f}"


def _run_gnbg_problem(problem_id, budget, threshold):
    """Helper: run solver on a GNBG problem and check the error threshold."""
    import iohgnbg
    from solver import solve

    problem = iohgnbg.get_problem(problem_id)
    dim = problem.meta_data.n_variables
    lb = [float(v) for v in problem.bounds.lb]
    ub = [float(v) for v in problem.bounds.ub]
    f_opt = float(problem.optimum.y)

    eval_count = [0]

    def objective(x):
        eval_count[0] += 1
        return float(problem(x))

    best_x, best_f = solve(objective, dim, lb, ub, budget)

    error = abs(best_f - f_opt)

    # Budget compliance (allow 1% slack for off-by-one in population loops)
    assert eval_count[0] <= int(budget * 1.02), (
        f"Problem {problem_id}: budget exceeded ({eval_count[0]} > {budget})"
    )

    assert error < threshold, (
        f"Problem {problem_id}: error {error:.6e} >= threshold {threshold:.6e} "
        f"(best_f={best_f:.6e}, f_opt={f_opt:.6e}, evals={eval_count[0]})"
    )


# ---------------------------------------------------------------------------
# GNBG benchmark tests — problems spanning the difficulty spectrum
# Budget: 200 000 FEs per problem
# ---------------------------------------------------------------------------

BUDGET = 200_000


class TestGNBGFoundational:
    """Problems from the foundational (unimodal / low-modality) category."""

    def test_problem_1(self):
        _run_gnbg_problem(1, BUDGET, threshold=1e-2)

    def test_problem_4(self):
        _run_gnbg_problem(4, BUDGET, threshold=1e-1)


class TestGNBGCoupled:
    """Problems with coupled variable interactions."""

    def test_problem_8(self):
        _run_gnbg_problem(8, BUDGET, threshold=1.0)


class TestGNBGMultimodal:
    """Multimodal / asymmetric landscape problems."""

    def test_problem_12(self):
        _run_gnbg_problem(12, BUDGET, threshold=10.0)
