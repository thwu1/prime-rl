"""
Tests for nonclassical Gauss quadrature computation.

Verifies that the agent correctly computed quadrature nodes and weights
for three nonclassical weight functions, that the rules satisfy moment
conditions, and that the resulting integral approximations are accurate.

"""

import json
import pytest
from mpmath import mp, mpf, gamma, pi, sin, cos, exp, log, besselj, quad, inf

mp.dps = 60

# ---------------------------------------------------------------------------
# Reference helpers
# ---------------------------------------------------------------------------

def ref_moment(w_name, k):
    """Compute the exact k-th moment for weight w_name."""
    if w_name == "w1":
        return mpf(1) / (k + 1) ** 2
    elif w_name == "w2":
        return gamma(k + mpf(3) / 4) * gamma(mpf(4) / 3) / gamma(k + mpf(25) / 12)
    elif w_name == "w3":
        return gamma((k + 1) / mpf(4)) / 4
    raise ValueError(w_name)


def ref_integrand(w_name, x):
    """Evaluate the smooth integrand f(x) for weight w_name."""
    if w_name == "w1":
        return sin(pi * x) / (1 + x)
    elif w_name == "w2":
        return exp(x) * cos(pi * x)
    elif w_name == "w3":
        return besselj(0, x)
    raise ValueError(w_name)


_integral_cache = {}


def ref_integral(w_name):
    """Compute the reference integral using mpmath.quad."""
    if w_name in _integral_cache:
        return _integral_cache[w_name]
    old_dps = mp.dps
    mp.dps = 50
    if w_name == "w1":
        val = quad(lambda x: -log(x) * sin(pi * x) / (1 + x), [mpf(0), mpf(1)])
    elif w_name == "w2":
        val = quad(
            lambda x: x ** (mpf(-1) / 4) * (1 - x) ** (mpf(1) / 3) * exp(x) * cos(pi * x),
            [mpf(0), mpf(1)],
        )
    elif w_name == "w3":
        # Split at 4 to help the quadrature routine; beyond x=4 the weight
        # exp(-x^4) < 10^{-111} and is negligible.
        val = quad(lambda x: exp(-(x ** 4)) * besselj(0, x), [mpf(0), mpf(4)])
    else:
        raise ValueError(w_name)
    mp.dps = old_dps
    _integral_cache[w_name] = val
    return val


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_top_level_keys(self, results):
        for key in ("quadrature_rules", "integrals", "moment_check"):
            assert key in results, f"Missing top-level key '{key}'"

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    def test_weight_keys(self, results, w):
        assert w in results["quadrature_rules"], f"Missing weight '{w}' in quadrature_rules"
        assert w in results["integrals"], f"Missing weight '{w}' in integrals"
        assert w in results["moment_check"], f"Missing weight '{w}' in moment_check"

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_rule_shape(self, results, w, N_str):
        N = int(N_str)
        rule = results["quadrature_rules"][w][N_str]
        assert "nodes" in rule and "weights" in rule
        assert len(rule["nodes"]) == N, f"Expected {N} nodes, got {len(rule['nodes'])}"
        assert len(rule["weights"]) == N, f"Expected {N} weights, got {len(rule['weights'])}"

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_integral_present(self, results, w, N_str):
        assert N_str in results["integrals"][w], f"Missing integral for {w}, N={N_str}"


# ---------------------------------------------------------------------------
# Node / weight property tests
# ---------------------------------------------------------------------------

class TestNodeProperties:
    @pytest.mark.parametrize("w", ["w1", "w2"])
    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_nodes_in_unit_interval(self, results, w, N_str):
        nodes = [mpf(x) for x in results["quadrature_rules"][w][N_str]["nodes"]]
        for x in nodes:
            assert 0 < float(x) < 1, f"Node {x} outside (0,1) for {w}, N={N_str}"

    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_w3_nodes_positive(self, results, N_str):
        nodes = [mpf(x) for x in results["quadrature_rules"]["w3"][N_str]["nodes"]]
        for x in nodes:
            assert float(x) > 0, f"Non-positive node {x} for w3, N={N_str}"

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_weights_positive(self, results, w, N_str):
        weights = [mpf(x) for x in results["quadrature_rules"][w][N_str]["weights"]]
        for wt in weights:
            assert float(wt) > 0, f"Non-positive weight {wt} for {w}, N={N_str}"

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_nodes_sorted_and_distinct(self, results, w, N_str):
        nodes = [mpf(x) for x in results["quadrature_rules"][w][N_str]["nodes"]]
        for i in range(len(nodes) - 1):
            assert nodes[i] < nodes[i + 1], (
                f"Nodes not sorted/distinct at index {i} for {w}, N={N_str}"
            )

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    @pytest.mark.parametrize("N_str", ["4", "8", "16", "32"])
    def test_weights_sum(self, results, w, N_str):
        """Weights should sum to mu_0."""
        weights = [mpf(x) for x in results["quadrature_rules"][w][N_str]["weights"]]
        wsum = sum(weights)
        mu0 = ref_moment(w, 0)
        rel = abs(wsum - mu0) / abs(mu0)
        assert float(rel) < 1e-15, f"Weight sum {wsum} != mu_0 {mu0} for {w}, N={N_str}"


# ---------------------------------------------------------------------------
# Moment condition tests
# ---------------------------------------------------------------------------

class TestMomentCondition:
    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    @pytest.mark.parametrize("N_str", ["4", "8"])
    def test_moments_small_N(self, results, w, N_str):
        """For small N the moment condition should hold to ~20 digits."""
        N = int(N_str)
        nodes = [mpf(x) for x in results["quadrature_rules"][w][N_str]["nodes"]]
        weights = [mpf(x) for x in results["quadrature_rules"][w][N_str]["weights"]]
        max_rel = mpf(0)
        for k in range(2 * N):
            computed = sum(wt * nd ** k for nd, wt in zip(nodes, weights))
            exact = ref_moment(w, k)
            if abs(exact) > mpf("1e-50"):
                rel = abs(computed - exact) / abs(exact)
                if rel > max_rel:
                    max_rel = rel
        assert float(max_rel) < 1e-18, (
            f"Moment condition failed for {w}, N={N}: max_rel_err={max_rel}"
        )

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    def test_moments_N16(self, results, w):
        N = 16
        nodes = [mpf(x) for x in results["quadrature_rules"][w]["16"]["nodes"]]
        weights = [mpf(x) for x in results["quadrature_rules"][w]["16"]["weights"]]
        max_rel = mpf(0)
        for k in range(2 * N):
            computed = sum(wt * nd ** k for nd, wt in zip(nodes, weights))
            exact = ref_moment(w, k)
            if abs(exact) > mpf("1e-50"):
                rel = abs(computed - exact) / abs(exact)
                if rel > max_rel:
                    max_rel = rel
        assert float(max_rel) < 1e-15, (
            f"Moment condition failed for {w}, N=16: max_rel_err={max_rel}"
        )

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    def test_moments_N32_first_half(self, results, w):
        """For N=32, check the first 32 moments (k=0..31) with relaxed tolerance."""
        nodes = [mpf(x) for x in results["quadrature_rules"][w]["32"]["nodes"]]
        weights = [mpf(x) for x in results["quadrature_rules"][w]["32"]["weights"]]
        max_rel = mpf(0)
        for k in range(32):
            computed = sum(wt * nd ** k for nd, wt in zip(nodes, weights))
            exact = ref_moment(w, k)
            if abs(exact) > mpf("1e-50"):
                rel = abs(computed - exact) / abs(exact)
                if rel > max_rel:
                    max_rel = rel
        assert float(max_rel) < 1e-10, (
            f"Moment condition (first 32) failed for {w}, N=32: max_rel_err={max_rel}"
        )


# ---------------------------------------------------------------------------
# Integral accuracy tests
# ---------------------------------------------------------------------------

class TestIntegralAccuracy:
    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    def test_integral_N32_vs_reference(self, results, w):
        """N=32 integral should match mpmath.quad reference to 12+ digits."""
        ref = ref_integral(w)
        val = mpf(results["integrals"][w]["32"])
        if abs(ref) > mpf("1e-50"):
            rel = abs(val - ref) / abs(ref)
            assert float(rel) < 1e-12, (
                f"Integral {w} N=32 rel_err={float(rel):.3e}, ref={ref}, got={val}"
            )
        else:
            assert abs(val - ref) < mpf("1e-20")

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    def test_integral_consistency(self, results, w):
        """Reported integral must equal sum(w_i * f(x_i)) from reported nodes/weights."""
        nodes = [mpf(x) for x in results["quadrature_rules"][w]["32"]["nodes"]]
        weights = [mpf(x) for x in results["quadrature_rules"][w]["32"]["weights"]]
        recomputed = sum(wt * ref_integrand(w, nd) for nd, wt in zip(nodes, weights))
        reported = mpf(results["integrals"][w]["32"])
        if abs(reported) > mpf("1e-50"):
            rel = abs(recomputed - reported) / abs(reported)
            assert float(rel) < 1e-20, (
                f"Consistency check failed for {w}: rel_err={rel}"
            )
        else:
            assert abs(recomputed - reported) < mpf("1e-25")

    @pytest.mark.parametrize("w", ["w1", "w2", "w3"])
    def test_convergence(self, results, w):
        """N=32 integral should be closer to the reference than N=4."""
        ref = ref_integral(w)
        err_4 = abs(mpf(results["integrals"][w]["4"]) - ref)
        err_32 = abs(mpf(results["integrals"][w]["32"]) - ref)
        assert float(err_32) < float(err_4), (
            f"No convergence for {w}: err_4={err_4}, err_32={err_32}"
        )
