
import json
import os
import numpy as np
import pytest

PROBLEMS_DIR = "/app/problems"
OUTPUT_DIR = "/app/output"

# Known optimal FLOP counts for each problem (computed analytically)
OPTIMAL_FLOPS = {
    "problem_1": 40200000,
    "problem_2": 256000000,
    "problem_3": 105000000,
    "problem_4": 234000000,
    "problem_5": 469493333,
}

TOLERANCE = 0.03  # 3% tolerance

VALID_KERNELS = {
    "multiply": {"GEMM", "TRMM", "DIAGMM"},
    "left_solve": {"GESV", "TRSM", "POSV", "DIAGSOLVE"},
    "right_solve": {"GESV_R", "TRSM_R", "POSV_R", "DIAGSOLVE_R"},
    "inverse": {"GETRI", "TRTRI", "DIAG_INV"},
}
ALL_KERNELS = set()
for v in VALID_KERNELS.values():
    ALL_KERNELS |= v


def load_problem(problem_id):
    path = os.path.join(PROBLEMS_DIR, f"{problem_id}.json")
    with open(path) as f:
        return json.load(f)


def load_output(problem_id):
    path = os.path.join(OUTPUT_DIR, f"{problem_id}.json")
    with open(path) as f:
        return json.load(f)


def generate_matrix(rows, cols, properties, rng):
    """Generate a random matrix with the given properties."""
    props = set(properties)
    n = max(rows, cols)
    if "diagonal" in props:
        assert rows == cols
        return np.diag(rng.standard_normal(rows) + 2.0)
    elif "lower_triangular" in props:
        assert rows == cols
        m = np.tril(rng.standard_normal((rows, cols)))
        np.fill_diagonal(m, np.abs(m.diagonal()) + 1.0)
        return m
    elif "upper_triangular" in props:
        assert rows == cols
        m = np.triu(rng.standard_normal((rows, cols)))
        np.fill_diagonal(m, np.abs(m.diagonal()) + 1.0)
        return m
    elif "spd" in props:
        assert rows == cols
        a = rng.standard_normal((rows, rows))
        return a @ a.T + rows * np.eye(rows)
    elif "symmetric" in props:
        assert rows == cols
        a = rng.standard_normal((rows, rows))
        return (a + a.T) / 2 + 2 * np.eye(rows)
    else:
        return rng.standard_normal((rows, cols))


def compute_expression_directly(problem, matrices_np):
    """Evaluate the chain expression directly using numpy."""
    result = None
    for term in problem["chain"]:
        mat = matrices_np[term["matrix"]].copy()
        if term.get("transpose", False):
            mat = mat.T
        if term.get("invert", False):
            mat = np.linalg.inv(mat)
        if result is None:
            result = mat
        else:
            result = result @ mat
    return result


def execute_plan(problem, plan, matrices_np):
    """Execute the plan step-by-step and return the final result."""
    known = {}
    for name, arr in matrices_np.items():
        known[name] = arr

    for step in plan["steps"]:
        kernel = step["kernel"]
        operands = step["operands"]
        output_name = step["output"]

        if kernel in VALID_KERNELS["multiply"]:
            left = known[operands[0]]
            right = known[operands[1]]
            known[output_name] = left @ right

        elif kernel in VALID_KERNELS["left_solve"]:
            # solve(A, B) = inv(A) @ B
            A = known[operands[0]]
            B = known[operands[1]]
            known[output_name] = np.linalg.solve(A, B)

        elif kernel in VALID_KERNELS["right_solve"]:
            # B @ inv(A) = solve(A^T, B^T)^T
            B = known[operands[0]]
            A = known[operands[1]]
            known[output_name] = np.linalg.solve(A.T, B.T).T

        elif kernel in VALID_KERNELS["inverse"]:
            A = known[operands[0]]
            known[output_name] = np.linalg.inv(A)

        else:
            raise ValueError(f"Unknown kernel: {kernel}")

    return known.get("RESULT")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(params=list(OPTIMAL_FLOPS.keys()))
def problem_id(request):
    return request.param


class TestOutputExists:
    def test_output_file_exists(self, problem_id):
        path = os.path.join(OUTPUT_DIR, f"{problem_id}.json")
        assert os.path.isfile(path), f"Output file missing: {path}"


class TestOutputSchema:
    def test_valid_json_schema(self, problem_id):
        plan = load_output(problem_id)
        assert "problem_id" in plan
        assert "total_flops" in plan
        assert "steps" in plan
        assert isinstance(plan["steps"], list)
        assert len(plan["steps"]) > 0

    def test_problem_id_matches(self, problem_id):
        plan = load_output(problem_id)
        assert plan["problem_id"] == problem_id

    def test_last_step_output_is_result(self, problem_id):
        plan = load_output(problem_id)
        assert plan["steps"][-1]["output"] == "RESULT"

    def test_step_fields(self, problem_id):
        plan = load_output(problem_id)
        for i, step in enumerate(plan["steps"]):
            assert "kernel" in step, f"Step {i} missing 'kernel'"
            assert "operands" in step, f"Step {i} missing 'operands'"
            assert "output" in step, f"Step {i} missing 'output'"
            assert "dims" in step, f"Step {i} missing 'dims'"
            assert "flops" in step, f"Step {i} missing 'flops'"

    def test_valid_kernel_names(self, problem_id):
        plan = load_output(problem_id)
        for step in plan["steps"]:
            assert step["kernel"] in ALL_KERNELS, (
                f"Invalid kernel: {step['kernel']}"
            )


class TestFlopConsistency:
    def test_total_flops_matches_sum(self, problem_id):
        plan = load_output(problem_id)
        step_sum = sum(s["flops"] for s in plan["steps"])
        assert plan["total_flops"] == step_sum, (
            f"total_flops={plan['total_flops']} != sum={step_sum}"
        )


class TestDimensionConsistency:
    def test_dimensions_consistent(self, problem_id):
        problem = load_problem(problem_id)
        plan = load_output(problem_id)

        # Build dimension map from problem matrices
        dim_map = {}
        for name, mat in problem["matrices"].items():
            dim_map[name] = (mat["rows"], mat["cols"])

        for i, step in enumerate(plan["steps"]):
            kernel = step["kernel"]
            operands = step["operands"]
            out_dims = tuple(step["dims"])

            if kernel in VALID_KERNELS["multiply"]:
                left_dims = dim_map[operands[0]]
                right_dims = dim_map[operands[1]]
                assert left_dims[1] == right_dims[0], (
                    f"Step {i}: dimension mismatch {left_dims} x {right_dims}"
                )
                expected = (left_dims[0], right_dims[1])
                assert out_dims == expected, (
                    f"Step {i}: output dims {out_dims} != expected {expected}"
                )

            elif kernel in VALID_KERNELS["left_solve"]:
                a_dims = dim_map[operands[0]]
                b_dims = dim_map[operands[1]]
                assert a_dims[0] == a_dims[1], f"Step {i}: solve matrix not square"
                assert a_dims[0] == b_dims[0], f"Step {i}: solve dimension mismatch"
                expected = (a_dims[0], b_dims[1])
                assert out_dims == expected

            elif kernel in VALID_KERNELS["right_solve"]:
                b_dims = dim_map[operands[0]]
                a_dims = dim_map[operands[1]]
                assert a_dims[0] == a_dims[1], f"Step {i}: solve matrix not square"
                assert b_dims[1] == a_dims[0], f"Step {i}: right-solve dim mismatch"
                expected = (b_dims[0], a_dims[1])
                assert out_dims == expected

            elif kernel in VALID_KERNELS["inverse"]:
                a_dims = dim_map[operands[0]]
                assert a_dims[0] == a_dims[1], f"Step {i}: inverse matrix not square"
                assert out_dims == a_dims

            # Register output dimensions
            dim_map[step["output"]] = out_dims


class TestFlopOptimality:
    def test_flops_near_optimal(self, problem_id):
        plan = load_output(problem_id)
        optimal = OPTIMAL_FLOPS[problem_id]
        threshold = int(optimal * (1 + TOLERANCE))
        actual = plan["total_flops"]
        assert actual <= threshold, (
            f"{problem_id}: total_flops={actual} exceeds threshold={threshold} "
            f"(optimal={optimal}, tolerance={TOLERANCE*100}%)"
        )

    def test_flops_not_below_optimal(self, problem_id):
        """Sanity check: FLOP count shouldn't be impossibly low."""
        plan = load_output(problem_id)
        optimal = OPTIMAL_FLOPS[problem_id]
        lower_bound = int(optimal * 0.5)
        actual = plan["total_flops"]
        assert actual >= lower_bound, (
            f"{problem_id}: total_flops={actual} suspiciously below "
            f"lower_bound={lower_bound} (optimal={optimal})"
        )


class TestNumericalCorrectness:
    """Execute plans with random matrices and verify results match direct evaluation."""

    def test_numerical_result(self, problem_id):
        problem = load_problem(problem_id)
        plan = load_output(problem_id)
        rng = np.random.default_rng(42)

        # Use scaled-down dimensions for faster numerical test
        scale = 10
        matrices_spec = {}
        for name, mat in problem["matrices"].items():
            r = max(mat["rows"] // scale, 2)
            c = max(mat["cols"] // scale, 2)
            # Square matrices must stay square
            if mat["rows"] == mat["cols"]:
                r = c = max(r, c)
            matrices_spec[name] = {
                "rows": r,
                "cols": c,
                "properties": mat["properties"],
            }

        # Generate random matrices
        matrices_np = {}
        for name, spec in matrices_spec.items():
            matrices_np[name] = generate_matrix(
                spec["rows"], spec["cols"], spec["properties"], rng
            )

        # Compute expression directly
        # Build a scaled problem for direct computation
        scaled_problem = {
            "chain": problem["chain"],
            "matrices": matrices_spec,
        }
        direct_result = compute_expression_directly(scaled_problem, matrices_np)

        # Rebuild the plan with scaled dims for execution
        # We can't use the plan's dims directly since they correspond to
        # original dimensions. We just execute kernels and check final shape.
        plan_result = execute_plan(problem, plan, matrices_np)

        assert plan_result is not None, "Plan did not produce RESULT"
        assert direct_result.shape == plan_result.shape, (
            f"Shape mismatch: direct={direct_result.shape}, "
            f"plan={plan_result.shape}"
        )
        np.testing.assert_allclose(
            plan_result, direct_result, rtol=1e-4, atol=1e-6,
            err_msg=f"Numerical mismatch for {problem_id}",
        )
