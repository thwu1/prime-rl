"""
"""

import json
import os
import pytest
from mpmath import mp, mpf, besselj, bessely, fabs, pi

mp.dps = 80


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json", "r") as f:
        return json.load(f)


def get_problem(results, problem_id):
    for p in results["problems"]:
        if p["id"] == problem_id:
            return p
    return None


# ── Secular equation definitions (independent of solution) ──────────────


def annular_m0_f(x):
    """J_0(3x)*Y_0(x) - Y_0(3x)*J_0(x)"""
    return besselj(0, 3 * x) * bessely(0, x) - bessely(0, 3 * x) * besselj(0, x)


def annular_m1_f(x):
    """J_1(3x)*Y_1(x) - Y_1(3x)*J_1(x)"""
    return besselj(1, 3 * x) * bessely(1, x) - bessely(1, 3 * x) * besselj(1, x)


def robin_dirichlet_f(x):
    """x*[J_0(2x)*Y_1(x) - J_1(x)*Y_0(2x)] - 5*[J_0(x)*Y_0(2x) - J_0(2x)*Y_0(x)]"""
    return (
        x * (besselj(0, 2 * x) * bessely(1, x) - besselj(1, x) * bessely(0, 2 * x))
        - 5 * (besselj(0, x) * bessely(0, 2 * x) - besselj(0, 2 * x) * bessely(0, x))
    )


def count_sig_digits(s):
    """Count significant digits in a decimal string."""
    s = s.strip().lstrip("-").lstrip("+")
    if "e" in s.lower():
        s = s.lower().split("e")[0]
    s = s.replace(".", "")
    s = s.lstrip("0")
    return len(s)


# ── Structure tests ─────────────────────────────────────────────────────


class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_has_problems_key(self, results):
        assert "problems" in results, "Top-level 'problems' key missing"

    def test_all_problem_ids_present(self, results):
        ids = {p["id"] for p in results["problems"]}
        for pid in ["annular_m0", "annular_m1", "robin_dirichlet"]:
            assert pid in ids, f"{pid} missing from problems"

    def test_annular_m0_count(self, results):
        p = get_problem(results, "annular_m0")
        assert p is not None
        assert len(p["zeros"]) == 15, f"Expected 15 zeros, got {len(p['zeros'])}"

    def test_annular_m1_count(self, results):
        p = get_problem(results, "annular_m1")
        assert p is not None
        assert len(p["zeros"]) == 15, f"Expected 15 zeros, got {len(p['zeros'])}"

    def test_robin_dirichlet_count(self, results):
        p = get_problem(results, "robin_dirichlet")
        assert p is not None
        assert len(p["zeros"]) == 10, f"Expected 10 zeros, got {len(p['zeros'])}"

    def test_has_spectral_zeta(self, results):
        assert "spectral_zeta_Z4" in results, "spectral_zeta_Z4 key missing"

    def test_has_asymptotic_products(self, results):
        assert "asymptotic_products" in results, "asymptotic_products key missing"
        assert len(results["asymptotic_products"]) == 15

    def test_zero_entries_have_required_fields(self, results):
        for p in results["problems"]:
            for z in p["zeros"]:
                assert "value" in z, f"Missing 'value' in {p['id']} #{z.get('index', '?')}"
                assert "residual" in z, f"Missing 'residual' in {p['id']} #{z.get('index', '?')}"
                assert "index" in z, f"Missing 'index' in {p['id']}"


# ── Annular m=0 eigenvalue tests ────────────────────────────────────────


class TestAnnularM0:
    def test_residuals(self, results):
        p = get_problem(results, "annular_m0")
        for z in p["zeros"]:
            x = mpf(z["value"])
            res = fabs(annular_m0_f(x))
            assert res < mpf(10) ** (-58), (
                f"Zero #{z['index']}: |f(x)| = {float(res):.2e} >= 1e-58"
            )

    def test_all_positive(self, results):
        p = get_problem(results, "annular_m0")
        for z in p["zeros"]:
            assert mpf(z["value"]) > 0, f"Zero #{z['index']} is not positive"

    def test_ascending_order(self, results):
        p = get_problem(results, "annular_m0")
        vals = [mpf(z["value"]) for z in p["zeros"]]
        for i in range(len(vals) - 1):
            assert vals[i] < vals[i + 1], f"Zeros not ascending at {i + 1},{i + 2}"

    def test_well_separated(self, results):
        p = get_problem(results, "annular_m0")
        vals = [mpf(z["value"]) for z in p["zeros"]]
        for i in range(len(vals) - 1):
            gap = vals[i + 1] - vals[i]
            assert gap > mpf("0.5"), f"Zeros {i + 1},{i + 2} too close: gap={float(gap):.4f}"

    def test_precision(self, results):
        p = get_problem(results, "annular_m0")
        for z in p["zeros"]:
            n = count_sig_digits(z["value"])
            assert n >= 60, f"#{z['index']}: only {n} significant digits"

    def test_first_zero_range(self, results):
        p = get_problem(results, "annular_m0")
        v = float(mpf(p["zeros"][0]["value"]))
        assert 1.0 < v < 2.5, f"First zero {v} outside expected range (1.0, 2.5)"

    def test_last_zero_range(self, results):
        p = get_problem(results, "annular_m0")
        v = float(mpf(p["zeros"][-1]["value"]))
        assert 22.0 < v < 25.0, f"Last zero {v} outside expected range (22.0, 25.0)"


# ── Annular m=1 eigenvalue tests ────────────────────────────────────────


class TestAnnularM1:
    def test_residuals(self, results):
        p = get_problem(results, "annular_m1")
        for z in p["zeros"]:
            x = mpf(z["value"])
            res = fabs(annular_m1_f(x))
            assert res < mpf(10) ** (-58), (
                f"Zero #{z['index']}: |g(x)| = {float(res):.2e} >= 1e-58"
            )

    def test_all_positive(self, results):
        p = get_problem(results, "annular_m1")
        for z in p["zeros"]:
            assert mpf(z["value"]) > 0, f"Zero #{z['index']} is not positive"

    def test_ascending_order(self, results):
        p = get_problem(results, "annular_m1")
        vals = [mpf(z["value"]) for z in p["zeros"]]
        for i in range(len(vals) - 1):
            assert vals[i] < vals[i + 1], f"Zeros not ascending at {i + 1},{i + 2}"

    def test_well_separated(self, results):
        p = get_problem(results, "annular_m1")
        vals = [mpf(z["value"]) for z in p["zeros"]]
        for i in range(len(vals) - 1):
            gap = vals[i + 1] - vals[i]
            assert gap > mpf("0.5"), f"Zeros {i + 1},{i + 2} too close: gap={float(gap):.4f}"

    def test_precision(self, results):
        p = get_problem(results, "annular_m1")
        for z in p["zeros"]:
            n = count_sig_digits(z["value"])
            assert n >= 60, f"#{z['index']}: only {n} significant digits"

    def test_first_zero_range(self, results):
        p = get_problem(results, "annular_m1")
        v = float(mpf(p["zeros"][0]["value"]))
        assert 1.0 < v < 3.0, f"First zero {v} outside expected range (1.0, 3.0)"

    def test_last_zero_range(self, results):
        p = get_problem(results, "annular_m1")
        v = float(mpf(p["zeros"][-1]["value"]))
        assert 22.0 < v < 26.0, f"Last zero {v} outside expected range (22.0, 26.0)"


# ── Robin-Dirichlet eigenvalue tests ────────────────────────────────────


class TestRobinDirichlet:
    def test_residuals(self, results):
        p = get_problem(results, "robin_dirichlet")
        for z in p["zeros"]:
            x = mpf(z["value"])
            res = fabs(robin_dirichlet_f(x))
            assert res < mpf(10) ** (-58), (
                f"Zero #{z['index']}: |h(x)| = {float(res):.2e} >= 1e-58"
            )

    def test_all_positive(self, results):
        p = get_problem(results, "robin_dirichlet")
        for z in p["zeros"]:
            assert mpf(z["value"]) > 0, f"Zero #{z['index']} is not positive"

    def test_ascending_order(self, results):
        p = get_problem(results, "robin_dirichlet")
        vals = [mpf(z["value"]) for z in p["zeros"]]
        for i in range(len(vals) - 1):
            assert vals[i] < vals[i + 1], f"Zeros not ascending at {i + 1},{i + 2}"

    def test_well_separated(self, results):
        p = get_problem(results, "robin_dirichlet")
        vals = [mpf(z["value"]) for z in p["zeros"]]
        for i in range(len(vals) - 1):
            gap = vals[i + 1] - vals[i]
            assert gap > mpf("1.0"), f"Zeros {i + 1},{i + 2} too close: gap={float(gap):.4f}"

    def test_precision(self, results):
        p = get_problem(results, "robin_dirichlet")
        for z in p["zeros"]:
            n = count_sig_digits(z["value"])
            assert n >= 60, f"#{z['index']}: only {n} significant digits"

    def test_first_zero_range(self, results):
        p = get_problem(results, "robin_dirichlet")
        v = float(mpf(p["zeros"][0]["value"]))
        assert 1.0 < v < 4.0, f"First zero {v} outside expected range (1.0, 4.0)"

    def test_last_zero_range(self, results):
        p = get_problem(results, "robin_dirichlet")
        v = float(mpf(p["zeros"][-1]["value"]))
        assert 27.0 < v < 33.0, f"Last zero {v} outside expected range (27.0, 33.0)"


# ── Spectral zeta function tests ───────────────────────────────────────


class TestSpectralZeta:
    def test_recomputed_matches(self, results):
        """Recompute Z_4 from reported zeros with correct multiplicities."""
        mp.dps = 70
        Z4 = mpf(0)
        # m=0 annular: multiplicity 1
        p0 = get_problem(results, "annular_m0")
        for z in p0["zeros"]:
            val = mpf(z["value"])
            Z4 += 1 / val ** 4
        # m=1 annular: multiplicity 2
        p1 = get_problem(results, "annular_m1")
        for z in p1["zeros"]:
            val = mpf(z["value"])
            Z4 += 2 / val ** 4
        # Robin-Dirichlet: multiplicity 1
        pr = get_problem(results, "robin_dirichlet")
        for z in pr["zeros"]:
            val = mpf(z["value"])
            Z4 += 1 / val ** 4

        reported = mpf(results["spectral_zeta_Z4"])
        rel_diff = fabs(Z4 - reported) / fabs(Z4)
        assert rel_diff < mpf(10) ** (-45), (
            f"Z_4 mismatch: recomputed vs reported, rel_diff={float(rel_diff):.2e}"
        )

    def test_precision(self, results):
        n = count_sig_digits(results["spectral_zeta_Z4"])
        assert n >= 50, f"Z_4 has only {n} significant digits, need >= 50"

    def test_positive(self, results):
        val = mpf(results["spectral_zeta_Z4"])
        assert val > 0, "Z_4 must be positive (sum of positive terms)"

    def test_reasonable_magnitude(self, results):
        """Z_4 should be dominated by the smallest eigenvalue terms."""
        val = float(mpf(results["spectral_zeta_Z4"]))
        # The smallest eigenvalue is ~1.5, so 1/1.5^4 ~ 0.2
        # With ~40 terms and multiplicities, Z_4 should be roughly 0.2 - 5.0
        assert 0.1 < val < 10.0, f"Z_4 = {val} outside plausible range [0.1, 10.0]"


# ── McMahon asymptotic convergence product tests ───────────────────────


class TestAsymptoticProducts:
    def test_count(self, results):
        assert len(results["asymptotic_products"]) == 15

    def test_n_values_sequential(self, results):
        ns = [ap["n"] for ap in results["asymptotic_products"]]
        assert ns == list(range(1, 16)), f"n values should be 1..15, got {ns}"

    def test_all_positive(self, results):
        for ap in results["asymptotic_products"]:
            Pn = mpf(ap["product"])
            assert Pn > 0, f"P_{ap['n']} is not positive"

    def test_bounded(self, results):
        """All P_n should be bounded (< 1.0)."""
        for ap in results["asymptotic_products"]:
            Pn = float(mpf(ap["product"]))
            assert Pn < 1.0, f"P_{ap['n']} = {Pn} >= 1.0"

    def test_large_n_range(self, results):
        """P_n for n >= 10 should be near 1/(6*pi^2) ~ 0.01689."""
        for ap in results["asymptotic_products"]:
            if ap["n"] >= 10:
                Pn = float(mpf(ap["product"]))
                assert 0.005 < Pn < 0.1, (
                    f"P_{ap['n']} = {Pn:.8f} outside range [0.005, 0.1]"
                )

    def test_convergence_clustering(self, results):
        """P_n values for n >= 8 should cluster (decreasing spread)."""
        Ps = [
            float(mpf(ap["product"]))
            for ap in results["asymptotic_products"]
            if ap["n"] >= 8
        ]
        mean_P = sum(Ps) / len(Ps)
        max_dev = max(abs(p - mean_P) for p in Ps)
        assert max_dev < 0.02, (
            f"P_n not converging: max deviation from mean = {max_dev:.6f}"
        )

    def test_consistency_with_zeros(self, results):
        """Verify P_n values are consistent with the reported m=0 zeros."""
        p0 = get_problem(results, "annular_m0")
        mp.dps = 65
        for ap in results["asymptotic_products"]:
            n = ap["n"]
            zero_val = mpf(p0["zeros"][n - 1]["value"])
            asymp_pred = n * pi / 2
            expected_P = n ** 2 * fabs(zero_val - asymp_pred) / zero_val
            reported_P = mpf(ap["product"])
            if expected_P > 0:
                rel_diff = fabs(expected_P - reported_P) / expected_P
                assert rel_diff < mpf(10) ** (-10), (
                    f"P_{n} inconsistent with zero: "
                    f"reported={float(reported_P):.12f}, "
                    f"computed={float(expected_P):.12f}"
                )
