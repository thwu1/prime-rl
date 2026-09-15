
"""
Tests for the black-box optimizer at /app/optimizer.py.
Verifies correctness across BBOB function classes covering separable,
ill-conditioned, valley-structured, and multimodal landscapes.
"""

import sys
import os
import ast
import numpy as np

sys.path.insert(0, "/app")

FORBIDDEN_IMPORTS = {"scipy", "pycma", "cma", "nevergrad", "optuna", "pymoo"}


class TestModuleInterface:
    """Verify the optimizer module exists, has correct interface, and is original."""

    def test_module_importable(self):
        """The optimizer module must be importable with an optimize function."""
        import optimizer
        assert hasattr(optimizer, "optimize"), "optimizer module must have 'optimize' function"
        assert callable(optimizer.optimize), "'optimize' must be callable"

    def test_no_forbidden_imports(self):
        """The implementation must not wrap existing optimizer libraries."""
        source_path = "/app/optimizer.py"
        assert os.path.exists(source_path), "optimizer.py must exist at /app/optimizer.py"
        with open(source_path, "r") as f:
            source = f.read()
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])
        violations = imported_modules & FORBIDDEN_IMPORTS
        assert not violations, (
            f"Forbidden optimizer libraries imported: {violations}. "
            f"Implementation must be from scratch."
        )

    def test_optimize_returns_tuple(self):
        """optimize must return (best_x, best_f) tuple."""
        from optimizer import optimize

        def sphere(x):
            return float(np.sum(x ** 2))

        np.random.seed(42)
        result = optimize(sphere, 2, -5 * np.ones(2), 5 * np.ones(2), 500)
        assert isinstance(result, (tuple, list)) and len(result) == 2, (
            "optimize must return a tuple of (best_x, best_f)"
        )
        best_x, best_f = result
        assert hasattr(best_x, "__len__"), "best_x must be array-like"
        assert len(best_x) == 2, "best_x must have correct dimension"
        assert isinstance(float(best_f), float), "best_f must be a number"


class TestBasicConvergence:
    """Test convergence on known analytic functions (no COCO dependency)."""

    def test_sphere_2d(self):
        """Must minimize 2D Sphere to high precision."""
        from optimizer import optimize

        def sphere(x):
            return float(np.sum(x ** 2))

        np.random.seed(42)
        _, best_f = optimize(sphere, 2, -5 * np.ones(2), 5 * np.ones(2), 5000)
        assert best_f < 1e-8, f"Sphere 2D: best_f={best_f:.2e}, expected < 1e-8"

    def test_sphere_10d(self):
        """Must minimize 10D Sphere."""
        from optimizer import optimize

        def sphere(x):
            return float(np.sum(x ** 2))

        np.random.seed(123)
        _, best_f = optimize(sphere, 10, -5 * np.ones(10), 5 * np.ones(10), 20000)
        assert best_f < 1e-6, f"Sphere 10D: best_f={best_f:.2e}, expected < 1e-6"

    def test_rosenbrock_5d(self):
        """Must make significant progress on 5D Rosenbrock."""
        from optimizer import optimize

        def rosenbrock(x):
            return float(sum(
                100 * (x[i + 1] - x[i] ** 2) ** 2 + (1 - x[i]) ** 2
                for i in range(len(x) - 1)
            ))

        np.random.seed(7)
        _, best_f = optimize(rosenbrock, 5, -5 * np.ones(5), 5 * np.ones(5), 50000)
        assert best_f < 1.0, f"Rosenbrock 5D: best_f={best_f:.2e}, expected < 1.0"

    def test_ellipsoid_5d(self):
        """Must handle ill-conditioned Ellipsoid (condition ~1e6)."""
        from optimizer import optimize

        def ellipsoid(x):
            D = len(x)
            return float(sum(10 ** (6 * i / (D - 1)) * x[i] ** 2 for i in range(D)))

        np.random.seed(99)
        _, best_f = optimize(ellipsoid, 5, -5 * np.ones(5), 5 * np.ones(5), 50000)
        assert best_f < 1e-4, f"Ellipsoid 5D: best_f={best_f:.2e}, expected < 1e-4"


class TestBBOBSeparable:
    """BBOB separable functions — basic optimizer correctness."""

    def test_bbob_sphere_f1_5d(self):
        """Must reach final target on BBOB Sphere (f1, 5D) on all 3 instances."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 1 dimensions: 5")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 100)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 100000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 3, f"BBOB f1 5D: only {hits}/3 instances hit final target"

    def test_bbob_sphere_f1_10d(self):
        """Must reach final target on BBOB Sphere (f1, 10D)."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 1 dimensions: 10")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 110)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 200000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, f"BBOB f1 10D: only {hits}/3 instances hit final target"

    def test_bbob_ellipsoidal_sep_f2_5d(self):
        """Must reach final target on BBOB separable Ellipsoidal (f2, 5D)."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 2 dimensions: 5")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 200)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 100000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, f"BBOB f2 5D: only {hits}/3 instances hit final target"


class TestBBOBValleyStructure:
    """BBOB functions with narrow valley — requires directional adaptation."""

    def test_bbob_rosenbrock_f8_5d(self):
        """Must reach final target on BBOB Rosenbrock (f8, 5D)."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 8 dimensions: 5")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 400)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 100000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, f"BBOB f8 5D: only {hits}/3 instances hit final target"


class TestBBOBHighConditioning:
    """BBOB high-conditioning unimodal functions — requires covariance adaptation."""

    def test_bbob_ellipsoidal_rot_f10_5d(self):
        """Must reach final target on rotated Ellipsoidal (f10, 5D, cond ~1e6)."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 10 dimensions: 5")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 500)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 100000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, f"BBOB f10 5D: only {hits}/3 instances hit final target"

    def test_bbob_discus_f11_5d(self):
        """Must reach final target on Discus (f11, 5D, cond ~1e6)."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 11 dimensions: 5")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 600)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 100000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, f"BBOB f11 5D: only {hits}/3 instances hit final target"

    def test_bbob_bent_cigar_f12_5d(self):
        """Must reach final target on Bent Cigar (f12, 5D, ridge following)."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 12 dimensions: 5")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 700)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 100000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, f"BBOB f12 5D: only {hits}/3 instances hit final target"


class TestBBOBMultimodal:
    """BBOB multimodal functions — requires restart mechanisms."""

    def test_bbob_rastrigin_sep_f3_2d(self):
        """Must reach final target on separable Rastrigin (f3, 2D) via restarts."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 3 dimensions: 2")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 800)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 40000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 2, (
            f"BBOB f3 2D: only {hits}/3 instances hit final target. "
            f"Likely indicates missing or broken restart mechanism."
        )

    def test_bbob_rastrigin_nonsep_f15_2d(self):
        """Must reach final target on non-separable Rastrigin (f15, 2D) via restarts."""
        import cocoex
        from optimizer import optimize

        suite = cocoex.Suite("bbob", "instances: 1-3", "function_indices: 15 dimensions: 2")
        hits = 0
        for problem in suite:
            np.random.seed(problem.id_instance + 900)
            optimize(problem, problem.dimension, problem.lower_bounds,
                     problem.upper_bounds, 40000, x0=problem.initial_solution)
            if problem.final_target_hit:
                hits += 1
            problem.free()
        assert hits >= 1, (
            f"BBOB f15 2D: {hits}/3 instances hit final target. "
            f"Requires restart mechanism on non-separable multimodal landscape."
        )
