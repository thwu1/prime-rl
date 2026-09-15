
import sys
import pytest

sys.path.insert(0, "/app")
import functions
import region_checker


# Expected feasible region counts (infeasible paths excluded)
EXPECTED_REGIONS = {
    "classify_simple": 4,
    "quadrant": 4,
    "tricky": 2,
    "complex_classify": 5,
    "nested_let": 4,
    "range_check": 3,
}


def _get_test_inputs(func_name):
    """Generate comprehensive test inputs for each function."""
    if func_name in ("classify_simple", "tricky"):
        return [{"x": x} for x in range(-50, 150)]
    else:
        return [{"x": x, "y": y} for x in range(-30, 31) for y in range(-30, 31)]


def _get_function(func_name):
    return getattr(functions, func_name)


class TestAllFunctionsPresent:
    @pytest.mark.parametrize("func_name", list(EXPECTED_REGIONS.keys()))
    def test_function_handled(self, func_name):
        n = region_checker.num_regions(func_name)
        assert n > 0, f"Function {func_name} has 0 regions or is missing"


class TestRegionCounts:
    @pytest.mark.parametrize(
        "func_name,expected", list(EXPECTED_REGIONS.items())
    )
    def test_region_count(self, func_name, expected):
        actual = region_checker.num_regions(func_name)
        assert actual == expected, (
            f"{func_name}: expected {expected} feasible regions, got {actual}"
        )


class TestCoverageAndCorrectness:
    """For each function and a grid of inputs, verify exactly one region
    matches and its invariant equals the function's actual output."""

    @pytest.mark.parametrize("func_name", list(EXPECTED_REGIONS.keys()))
    def test_full_coverage(self, func_name):
        func = _get_function(func_name)
        n_regions = region_checker.num_regions(func_name)
        test_inputs = _get_test_inputs(func_name)

        for inputs in test_inputs:
            matching = [
                i
                for i in range(n_regions)
                if region_checker.check_region(func_name, i, **inputs)
            ]

            assert len(matching) == 1, (
                f"{func_name}({inputs}): {len(matching)} regions match "
                f"(expected exactly 1). Matching indices: {matching}"
            )

            actual = func(**inputs)
            region_val = region_checker.evaluate_region(
                func_name, matching[0], **inputs
            )
            assert region_val == actual, (
                f"{func_name}({inputs}): region {matching[0]} evaluates to "
                f"{region_val}, but function returns {actual}"
            )


class TestBoundaryValues:
    """Explicitly test critical boundary values."""

    def test_classify_simple_boundaries(self):
        cases = [
            (-100, 99),
            (-3, 99),
            (-2, 99),
            (-1, 103),
            (0, 103),
            (20, 103),
            (21, 30),
            (50, 59),
            (99, 108),
            (100, 100),
            (200, 100),
        ]
        for x, expected in cases:
            actual = functions.classify_simple(x)
            assert actual == expected
            matching = [
                i
                for i in range(region_checker.num_regions("classify_simple"))
                if region_checker.check_region("classify_simple", i, x=x)
            ]
            assert len(matching) == 1
            assert (
                region_checker.evaluate_region(
                    "classify_simple", matching[0], x=x
                )
                == expected
            )

    def test_tricky_boundaries(self):
        cases = [
            (-10, -9),
            (0, 1),
            (5, 6),
            (10, 11),
            (11, 22),
            (15, 30),
            (100, 200),
        ]
        for x, expected in cases:
            actual = functions.tricky(x)
            assert actual == expected
            matching = [
                i
                for i in range(region_checker.num_regions("tricky"))
                if region_checker.check_region("tricky", i, x=x)
            ]
            assert len(matching) == 1
            assert (
                region_checker.evaluate_region("tricky", matching[0], x=x)
                == expected
            )

    def test_range_check_diagonal(self):
        """Test x == y, x > y, and x < y cases."""
        for v in [-20, -5, -1, 0, 1, 5, 20]:
            # x == y
            assert functions.range_check(v, v) == 0
            matching = [
                i
                for i in range(region_checker.num_regions("range_check"))
                if region_checker.check_region("range_check", i, x=v, y=v)
            ]
            assert len(matching) == 1
            assert (
                region_checker.evaluate_region(
                    "range_check", matching[0], x=v, y=v
                )
                == 0
            )

            # x > y (by 1)
            assert functions.range_check(v + 1, v) == 1
            matching = [
                i
                for i in range(region_checker.num_regions("range_check"))
                if region_checker.check_region(
                    "range_check", i, x=v + 1, y=v
                )
            ]
            assert len(matching) == 1
            assert (
                region_checker.evaluate_region(
                    "range_check", matching[0], x=v + 1, y=v
                )
                == 1
            )

            # x < y (by 1)
            assert functions.range_check(v, v + 1) == 1
            matching = [
                i
                for i in range(region_checker.num_regions("range_check"))
                if region_checker.check_region(
                    "range_check", i, x=v, y=v + 1
                )
            ]
            assert len(matching) == 1
            assert (
                region_checker.evaluate_region(
                    "range_check", matching[0], x=v, y=v + 1
                )
                == 1
            )

    def test_complex_classify_infeasible_region(self):
        """Verify the infeasible region (return 4) never appears.
        That region requires: x+y>10, not(x>0 and y>0), x<=10, y<=10,
        which is logically unsatisfiable."""
        n = region_checker.num_regions("complex_classify")
        # Test a grid that spans the infeasible region's constraint space
        for x in range(-15, 16):
            for y in range(-15, 16):
                matching = [
                    i
                    for i in range(n)
                    if region_checker.check_region(
                        "complex_classify", i, x=x, y=y
                    )
                ]
                assert len(matching) == 1, (
                    f"complex_classify(x={x}, y={y}): {len(matching)} regions"
                )
                actual = functions.complex_classify(x, y)
                val = region_checker.evaluate_region(
                    "complex_classify", matching[0], x=x, y=y
                )
                assert val == actual

    def test_nested_let_substitution(self):
        """Verify let-binding substitution works correctly.
        nested_let effectively computes:
        region 0 (x>y, x+y>0): 2x
        region 1 (x>y, x+y<=0): -2y
        region 2 (x<=y, x+y>0): 2y
        region 3 (x<=y, x+y<=0): -2x
        """
        cases = [
            (10, 3, 20),
            (3, -5, 10),
            (1, 5, 10),
            (-5, 1, 10),
        ]
        for x, y, expected in cases:
            actual = functions.nested_let(x, y)
            assert actual == expected, f"nested_let({x}, {y}) = {actual}"
            matching = [
                i
                for i in range(region_checker.num_regions("nested_let"))
                if region_checker.check_region("nested_let", i, x=x, y=y)
            ]
            assert len(matching) == 1
            assert (
                region_checker.evaluate_region(
                    "nested_let", matching[0], x=x, y=y
                )
                == expected
            )
