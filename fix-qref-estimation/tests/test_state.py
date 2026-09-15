
import json
import pytest
from bartiq import compile_routine, evaluate
from qref import SchemaV1


_compiled_cache = {}


def _load_and_compile(path):
    """Load a QREF JSON, validate, and compile, caching the result."""
    if path not in _compiled_cache:
        with open(path) as f:
            data = json.load(f)
        schema = SchemaV1(**data)
        _compiled_cache[path] = compile_routine(schema)
    return _compiled_cache[path]


def _eval(compiled, N, K):
    """Evaluate a compiled routine and return (t_gates, rotations)."""
    result = evaluate(compiled.routine, {"N": N, "K": K})
    t = int(result.routine.resources["T_gates"].value)
    r = int(result.routine.resources["rotations"].value)
    return t, r


# Expected evaluation results for variant A (select: T=2*K*n, rot=K)
EXPECTED_A = {
    (8, 5): (116, 23),
    (8, 8): (152, 29),
    (8, 15): (244, 45),
    (32, 10): (368, 39),
    (32, 12): (408, 43),
    (32, 20): (576, 61),
    (64, 13): (612, 47),
    (64, 14): (636, 49),
    (64, 25): (908, 73),
}

# Expected evaluation results for variant B (select: T=4*n^2+K, rot=n)
EXPECTED_B = {
    (8, 5): (127, 21),
    (8, 8): (148, 24),
    (8, 15): (205, 33),
    (32, 10): (378, 34),
    (32, 12): (400, 36),
    (32, 20): (496, 46),
    (64, 13): (613, 40),
    (64, 14): (626, 41),
    (64, 25): (777, 54),
}

EXPECTED_BETTER = {
    (8, 5): "A", (8, 8): "B", (8, 15): "B",
    (32, 10): "A", (32, 12): "B", (32, 20): "B",
    (64, 13): "A", (64, 14): "B", (64, 25): "B",
}

EXPECTED_CROSSOVER = {8: 8, 32: 12, 64: 14}

PARAM_SETS = list(EXPECTED_A.keys())


class TestVariantSpecs:
    """Verify both variant JSON files exist and are loadable as QREF schemas."""

    def test_variant_a_is_valid_schema(self):
        with open("/app/variant_a.json") as f:
            data = json.load(f)
        schema = SchemaV1(**data)
        assert schema is not None

    def test_variant_b_is_valid_schema(self):
        with open("/app/variant_b.json") as f:
            data = json.load(f)
        schema = SchemaV1(**data)
        assert schema is not None


class TestCompilation:
    """Verify both variants compile successfully with bartiq."""

    def test_variant_a_compiles(self):
        compiled = _load_and_compile("/app/variant_a.json")
        assert compiled is not None

    def test_variant_b_compiles(self):
        compiled = _load_and_compile("/app/variant_b.json")
        assert compiled is not None

    def test_variant_a_has_resources(self):
        compiled = _load_and_compile("/app/variant_a.json")
        res = set(compiled.routine.resources.keys())
        assert "T_gates" in res, f"Variant A missing T_gates, has: {res}"
        assert "rotations" in res, f"Variant A missing rotations, has: {res}"

    def test_variant_b_has_resources(self):
        compiled = _load_and_compile("/app/variant_b.json")
        res = set(compiled.routine.resources.keys())
        assert "T_gates" in res, f"Variant B missing T_gates, has: {res}"
        assert "rotations" in res, f"Variant B missing rotations, has: {res}"


class TestEvaluationA:
    """Verify variant A resource counts for all parameter sets."""

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_t_gates(self, N, K):
        compiled = _load_and_compile("/app/variant_a.json")
        t, _ = _eval(compiled, N, K)
        exp_t, _ = EXPECTED_A[(N, K)]
        assert t == exp_t, f"A T_gates(N={N},K={K}): got {t}, expected {exp_t}"

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_rotations(self, N, K):
        compiled = _load_and_compile("/app/variant_a.json")
        _, r = _eval(compiled, N, K)
        _, exp_r = EXPECTED_A[(N, K)]
        assert r == exp_r, f"A rotations(N={N},K={K}): got {r}, expected {exp_r}"


class TestEvaluationB:
    """Verify variant B resource counts for all parameter sets."""

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_t_gates(self, N, K):
        compiled = _load_and_compile("/app/variant_b.json")
        t, _ = _eval(compiled, N, K)
        exp_t, _ = EXPECTED_B[(N, K)]
        assert t == exp_t, f"B T_gates(N={N},K={K}): got {t}, expected {exp_t}"

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_rotations(self, N, K):
        compiled = _load_and_compile("/app/variant_b.json")
        _, r = _eval(compiled, N, K)
        _, exp_r = EXPECTED_B[(N, K)]
        assert r == exp_r, f"B rotations(N={N},K={K}): got {r}, expected {exp_r}"


class TestResults:
    """Verify results.json structure and data correctness."""

    def _load_results(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_results_has_required_keys(self):
        results = self._load_results()
        for key in ["variant_a", "variant_b", "better_variant", "crossover_k"]:
            assert key in results, f"results.json missing '{key}'"

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_results_variant_a(self, N, K):
        results = self._load_results()
        key = f"{N}_{K}"
        assert key in results["variant_a"], f"Missing variant_a[{key}]"
        exp_t, exp_r = EXPECTED_A[(N, K)]
        entry = results["variant_a"][key]
        assert entry["t_gates"] == exp_t, (
            f"results variant_a[{key}].t_gates: got {entry['t_gates']}, expected {exp_t}"
        )
        assert entry["rotations"] == exp_r, (
            f"results variant_a[{key}].rotations: got {entry['rotations']}, expected {exp_r}"
        )

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_results_variant_b(self, N, K):
        results = self._load_results()
        key = f"{N}_{K}"
        assert key in results["variant_b"], f"Missing variant_b[{key}]"
        exp_t, exp_r = EXPECTED_B[(N, K)]
        entry = results["variant_b"][key]
        assert entry["t_gates"] == exp_t, (
            f"results variant_b[{key}].t_gates: got {entry['t_gates']}, expected {exp_t}"
        )
        assert entry["rotations"] == exp_r, (
            f"results variant_b[{key}].rotations: got {entry['rotations']}, expected {exp_r}"
        )

    @pytest.mark.parametrize("N,K", PARAM_SETS)
    def test_better_variant(self, N, K):
        results = self._load_results()
        key = f"{N}_{K}"
        assert key in results["better_variant"], f"Missing better_variant[{key}]"
        expected = EXPECTED_BETTER[(N, K)]
        got = results["better_variant"][key]
        assert got == expected, (
            f"better_variant[{key}]: got {got}, expected {expected}"
        )

    def test_crossover_k(self):
        results = self._load_results()
        for N, expected_k in EXPECTED_CROSSOVER.items():
            n_str = str(N)
            assert n_str in results["crossover_k"], f"Missing crossover_k[{n_str}]"
            got = results["crossover_k"][n_str]
            assert got == expected_k, (
                f"crossover_k[{n_str}]: got {got}, expected {expected_k}"
            )


class TestAntiCheat:
    """Verify the specifications are genuine QREF models, not hardcoded results."""

    def _load_spec(self, path):
        with open(path) as f:
            return json.load(f)

    def _check_symbolic_resources(self, node):
        """Return True if any resource in the subtree has a symbolic expression."""
        for r in node.get("resources", []):
            val = str(r.get("value", ""))
            if any(c.isalpha() for c in val):
                return True
        for child in node.get("children", []):
            if self._check_symbolic_resources(child):
                return True
        return False

    def _check_has_children(self, node):
        """Return True if the subtree has at least one level of children."""
        children = node.get("children", [])
        if len(children) > 0:
            return True
        return False

    def _count_connections(self, node):
        """Count connections in the subtree."""
        count = len(node.get("connections", []))
        for child in node.get("children", []):
            count += self._count_connections(child)
        return count

    def test_variant_a_has_symbolic_resources(self):
        spec = self._load_spec("/app/variant_a.json")
        assert self._check_symbolic_resources(spec["program"]), (
            "Variant A must use symbolic resource expressions"
        )

    def test_variant_b_has_symbolic_resources(self):
        spec = self._load_spec("/app/variant_b.json")
        assert self._check_symbolic_resources(spec["program"]), (
            "Variant B must use symbolic resource expressions"
        )

    def test_variant_a_has_hierarchy(self):
        spec = self._load_spec("/app/variant_a.json")
        assert self._check_has_children(spec["program"]), (
            "Variant A must have hierarchical subroutine structure"
        )

    def test_variant_b_has_hierarchy(self):
        spec = self._load_spec("/app/variant_b.json")
        assert self._check_has_children(spec["program"]), (
            "Variant B must have hierarchical subroutine structure"
        )

    def test_variant_a_has_connections(self):
        spec = self._load_spec("/app/variant_a.json")
        assert self._count_connections(spec["program"]) >= 5, (
            "Variant A must have proper port connections"
        )

    def test_variant_b_has_connections(self):
        spec = self._load_spec("/app/variant_b.json")
        assert self._count_connections(spec["program"]) >= 5, (
            "Variant B must have proper port connections"
        )

    def test_variant_a_has_input_params(self):
        spec = self._load_spec("/app/variant_a.json")
        params = spec["program"].get("input_params", [])
        assert len(params) >= 2, (
            f"Variant A must have at least 2 input parameters, got: {params}"
        )

    def test_variant_b_has_input_params(self):
        spec = self._load_spec("/app/variant_b.json")
        params = spec["program"].get("input_params", [])
        assert len(params) >= 2, (
            f"Variant B must have at least 2 input parameters, got: {params}"
        )

    def test_variants_differ(self):
        """Verify the two variant specs are not identical."""
        spec_a = self._load_spec("/app/variant_a.json")
        spec_b = self._load_spec("/app/variant_b.json")
        assert json.dumps(spec_a, sort_keys=True) != json.dumps(spec_b, sort_keys=True), (
            "Variant A and B specifications must differ"
        )
