
import pytest
import numpy as np
from scipy import stats
import sys

sys.path.insert(0, "/app")
import nicob


# ===================================================================
# Module API
# ===================================================================


class TestModuleAPI:
    def test_required_functions_exist(self):
        for name in [
            "parse_ncb",
            "dersimonian_laird",
            "sample_tau2",
            "symmetrical_bootstrap_ci",
            "linear_pool",
            "doe_unilateral_dl",
            "doe_bilateral_dl",
        ]:
            assert callable(getattr(nicob, name, None)), f"Missing: {name}"


# ===================================================================
# parse_ncb
# ===================================================================


class TestParseNCB:
    def test_pcb28(self):
        d = nicob.parse_ncb("/app/data/pcb28.ncb")
        assert d["labels"] == ["IRMM", "KRISS", "NARL", "NIST", "NMIJ", "NRC"]
        np.testing.assert_allclose(
            d["x"], [34.30, 32.90, 34.53, 32.42, 31.90, 35.80]
        )
        np.testing.assert_allclose(d["u"], [1.03, 0.69, 0.83, 0.29, 0.40, 0.38])
        np.testing.assert_allclose(d["nu"], [60, 4, 18, 2, 13, 60])
        assert d["coverage"] == pytest.approx(0.95)

    def test_radionuclide_infinite_df(self):
        d = nicob.parse_ncb("/app/data/radionuclide.ncb")
        assert len(d["labels"]) == 19
        assert len(d["x"]) == 19
        assert np.all(np.isinf(d["nu"]))

    def test_gauge(self):
        d = nicob.parse_ncb("/app/data/gauge.ncb")
        assert len(d["labels"]) == 9
        assert d["labels"][0] == "OFMET"
        assert d["labels"][-1] == "KRISS"
        np.testing.assert_allclose(d["nu"], [500, 119, 94, 9, 50, 72, 205, 5, 55])


# ===================================================================
# dersimonian_laird
# ===================================================================


def _reference_dl(x, u, coverage=0.95):
    """Independent reference computation of DL + HKSJ."""
    n = len(x)
    w0 = 1.0 / u**2
    x0 = np.sum(w0 * x) / np.sum(w0)
    S1, S2 = np.sum(w0), np.sum(w0**2)
    tau2 = max(0.0, (np.sum(w0 * (x - x0) ** 2) - (n - 1)) / (S1 - S2 / S1))
    w = 1.0 / (u**2 + tau2)
    mu = np.sum(w * x) / np.sum(w)
    qs = max(1.0, np.sum(w * (x - mu) ** 2) / (n - 1))
    se = np.sqrt(qs / np.sum(w))
    t_c = stats.t.ppf((1 + coverage) / 2, n - 1)
    hw = np.sqrt(qs) * se * t_c
    return dict(mu=mu, tau2=tau2, qstar=qs, se=se, w=w, ci_lb=mu - hw, ci_ub=mu + hw)


class TestDerSimonianLaird:
    PCB_X = np.array([34.30, 32.90, 34.53, 32.42, 31.90, 35.80])
    PCB_U = np.array([1.03, 0.69, 0.83, 0.29, 0.40, 0.38])

    def test_pcb28_matches_reference(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        ref = _reference_dl(self.PCB_X, self.PCB_U)
        assert res["mu"] == pytest.approx(ref["mu"], abs=1e-10)
        assert res["tau2"] == pytest.approx(ref["tau2"], abs=1e-10)
        assert res["qstar"] == pytest.approx(ref["qstar"], abs=1e-10)
        assert res["se"] == pytest.approx(ref["se"], abs=1e-10)
        np.testing.assert_allclose(res["weights"], ref["w"], atol=1e-10)

    def test_pcb28_dark_uncertainty(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        assert res["tau2"] > 0
        assert res["tau"] == pytest.approx(np.sqrt(res["tau2"]), abs=1e-12)

    def test_ci_contains_mu(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        assert res["ci_lb"] < res["mu"] < res["ci_ub"]

    def test_hksj_ci_formula(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        t_c = stats.t.ppf(0.975, res["df"])
        hw = np.sqrt(res["qstar"]) * res["se"] * t_c
        assert res["ci_ub"] - res["mu"] == pytest.approx(hw, abs=1e-10)
        assert res["mu"] - res["ci_lb"] == pytest.approx(hw, abs=1e-10)

    def test_qstar_ge_one(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        assert res["qstar"] >= 1.0

    def test_first_order_condition(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        w = np.array(res["weights"])
        assert abs(np.sum(w * (self.PCB_X - res["mu"]))) < 1e-10

    def test_homogeneous_zero_tau(self):
        x = np.array([10.0, 10.01, 9.99, 10.0, 10.005])
        u = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        res = nicob.dersimonian_laird(x, u)
        assert res["tau2"] == 0.0

    def test_df_equals_n_minus_one(self):
        res = nicob.dersimonian_laird(self.PCB_X, self.PCB_U)
        assert res["df"] == 5

    def test_gauge_dataset(self):
        d = nicob.parse_ncb("/app/data/gauge.ncb")
        res = nicob.dersimonian_laird(d["x"], d["u"])
        ref = _reference_dl(d["x"], d["u"])
        assert res["mu"] == pytest.approx(ref["mu"], abs=1e-10)
        assert res["tau2"] == pytest.approx(ref["tau2"], abs=1e-10)
        assert res["ci_lb"] < res["mu"] < res["ci_ub"]

    def test_radionuclide_dataset(self):
        d = nicob.parse_ncb("/app/data/radionuclide.ncb")
        res = nicob.dersimonian_laird(d["x"], d["u"])
        assert 7030 < res["mu"] < 7080
        assert res["tau2"] > 0
        assert res["df"] == 18


# ===================================================================
# sample_tau2
# ===================================================================


class TestSampleTau2:
    def test_nonnegative(self):
        rng = np.random.default_rng(12345)
        x = np.array([34.30, 32.90, 34.53, 32.42, 31.90, 35.80])
        u = np.array([1.03, 0.69, 0.83, 0.29, 0.40, 0.38])
        samples = [nicob.sample_tau2(x, u, rng) for _ in range(2000)]
        assert all(s >= 0.0 for s in samples)

    def test_mean_reasonable(self):
        rng = np.random.default_rng(42)
        x = np.array([34.30, 32.90, 34.53, 32.42, 31.90, 35.80])
        u = np.array([1.03, 0.69, 0.83, 0.29, 0.40, 0.38])
        dl = nicob.dersimonian_laird(x, u)
        samples = np.array([nicob.sample_tau2(x, u, rng) for _ in range(30000)])
        assert np.mean(samples) > 0
        # Mean should be in reasonable neighbourhood of DL tau2
        assert abs(np.mean(samples) - dl["tau2"]) < 3.0

    def test_reproducible(self):
        x = np.array([1.0, 3.0, 2.0, 4.0])
        u = np.array([0.5, 0.5, 0.5, 0.5])
        s1 = nicob.sample_tau2(x, u, np.random.default_rng(99))
        s2 = nicob.sample_tau2(x, u, np.random.default_rng(99))
        assert s1 == s2


# ===================================================================
# symmetrical_bootstrap_ci
# ===================================================================


class TestSymmetricalBootstrapCI:
    def test_normal_95(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, size=200000)
        U = nicob.symmetrical_bootstrap_ci(x, 0.0, 0.95)
        # For N(0,1), 95% symmetric half-width ≈ 1.96
        assert abs(U - 1.96) < 0.02

    def test_coverage_monotone(self):
        rng = np.random.default_rng(42)
        x = rng.normal(5.0, 2.0, size=100000)
        U90 = nicob.symmetrical_bootstrap_ci(x, 5.0, 0.90)
        U95 = nicob.symmetrical_bootstrap_ci(x, 5.0, 0.95)
        U99 = nicob.symmetrical_bootstrap_ci(x, 5.0, 0.99)
        assert U90 < U95 < U99

    def test_positive(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, size=5000)
        U = nicob.symmetrical_bootstrap_ci(x, 0.0, 0.95)
        assert U > 0


# ===================================================================
# linear_pool
# ===================================================================


class TestLinearPool:
    def test_equal_weights_mean(self):
        rng = np.random.default_rng(42)
        x = np.array([10.0, 20.0, 30.0])
        ux = np.array([0.5, 0.5, 0.5])
        nu = np.array([np.inf, np.inf, np.inf])
        w = np.array([1.0, 1.0, 1.0])
        samples = nicob.linear_pool(x, ux, nu, w, 200000, rng)
        assert abs(np.mean(samples) - 20.0) < 0.1

    def test_finite_df_works(self):
        rng = np.random.default_rng(42)
        x = np.array([10.0, 20.0])
        ux = np.array([1.0, 1.0])
        nu = np.array([5.0, 10.0])
        w = np.array([1.0, 1.0])
        samples = nicob.linear_pool(x, ux, nu, w, 50000, rng)
        assert abs(np.mean(samples) - 15.0) < 0.5
        assert len(samples) == 50000

    def test_weighted_concentration(self):
        rng = np.random.default_rng(42)
        x = np.array([0.0, 100.0])
        ux = np.array([0.01, 0.01])
        nu = np.array([np.inf, np.inf])
        w = np.array([3.0, 1.0])
        samples = nicob.linear_pool(x, ux, nu, w, 200000, rng)
        # 75% weight on 0, 25% on 100
        assert abs(np.mean(samples) - 25.0) < 0.2


# ===================================================================
# doe_unilateral_dl
# ===================================================================


class TestDoEUnilateral:
    X = np.array([34.30, 32.90, 34.53, 32.42, 31.90, 35.80])
    U = np.array([1.03, 0.69, 0.83, 0.29, 0.40, 0.38])
    NU = np.array([60.0, 4.0, 18.0, 2.0, 13.0, 60.0])
    LABS = ["IRMM", "KRISS", "NARL", "NIST", "NMIJ", "NRC"]

    def test_mra_doe_x(self):
        dl = nicob.dersimonian_laird(self.X, self.U)
        rng = np.random.default_rng(42)
        res = nicob.doe_unilateral_dl(
            self.X, self.U, self.NU, self.LABS, 5000, False, 0.95, dl, rng
        )
        for j, doe in enumerate(res["DoE"]):
            assert doe["DoE_x"] == pytest.approx(self.X[j] - dl["mu"], abs=1e-10)

    def test_mra_d_shape(self):
        dl = nicob.dersimonian_laird(self.X, self.U)
        K = 3000
        rng = np.random.default_rng(42)
        res = nicob.doe_unilateral_dl(
            self.X, self.U, self.NU, self.LABS, K, False, 0.95, dl, rng
        )
        assert res["D"].shape == (K, 6)

    def test_mra_intervals_bracket(self):
        dl = nicob.dersimonian_laird(self.X, self.U)
        rng = np.random.default_rng(42)
        res = nicob.doe_unilateral_dl(
            self.X, self.U, self.NU, self.LABS, 10000, False, 0.95, dl, rng
        )
        for doe in res["DoE"]:
            assert doe["DoE_Lwr"] < doe["DoE_x"] < doe["DoE_Upr"]
            assert doe["DoE_U95"] > 0

    def test_loo_structure(self):
        dl = nicob.dersimonian_laird(self.X, self.U)
        K = 3000
        rng = np.random.default_rng(42)
        res = nicob.doe_unilateral_dl(
            self.X, self.U, self.NU, self.LABS, K, True, 0.95, dl, rng
        )
        assert res["D"].shape == (K, 6)
        assert len(res["DoE"]) == 6
        for doe in res["DoE"]:
            assert doe["DoE_U95"] > 0
            assert doe["DoE_Lwr"] < doe["DoE_Upr"]


# ===================================================================
# doe_bilateral_dl
# ===================================================================


class TestDoEBilateral:
    X = np.array([34.30, 32.90, 34.53, 32.42, 31.90, 35.80])
    U = np.array([1.03, 0.69, 0.83, 0.29, 0.40, 0.38])
    NU = np.array([60.0, 4.0, 18.0, 2.0, 13.0, 60.0])
    LABS = ["IRMM", "KRISS", "NARL", "NIST", "NMIJ", "NRC"]

    @pytest.fixture(scope="class")
    def bilateral_result(self):
        dl = nicob.dersimonian_laird(self.X, self.U)
        rng = np.random.default_rng(42)
        uni = nicob.doe_unilateral_dl(
            self.X, self.U, self.NU, self.LABS, 5000, False, 0.95, dl, rng
        )
        bi = nicob.doe_bilateral_dl(self.X, self.U, self.NU, self.LABS, 0.95, uni)
        return bi, uni

    def test_bilateral_values_match_x_diffs(self, bilateral_result):
        bi, uni = bilateral_result
        B_x = np.array(bi["B_x"])
        # Bilateral DoE.x = x[i] - x[j] (equals DoE_x[i] - DoE_x[j])
        assert B_x[0, 1] == pytest.approx(1.40, abs=0.01)  # IRMM - KRISS
        assert B_x[0, 2] == pytest.approx(-0.23, abs=0.01)  # IRMM - NARL
        assert B_x[0, 3] == pytest.approx(1.88, abs=0.01)  # IRMM - NIST
        assert B_x[0, 4] == pytest.approx(2.40, abs=0.01)  # IRMM - NMIJ
        assert B_x[0, 5] == pytest.approx(-1.50, abs=0.01)  # IRMM - NRC
        assert B_x[3, 4] == pytest.approx(0.52, abs=0.01)  # NIST - NMIJ
        assert B_x[4, 5] == pytest.approx(-3.90, abs=0.01)  # NMIJ - NRC

    def test_diagonal_zero_and_symmetry(self, bilateral_result):
        bi, _ = bilateral_result
        B_U = np.array(bi["B_U"])
        B_x = np.array(bi["B_x"])
        n = len(self.X)
        for i in range(n):
            assert B_U[i, i] == 0.0
            assert B_x[i, i] == 0.0
        # B_U symmetric, B_x equals x[i]-x[j]
        for i in range(n):
            for j in range(n):
                assert B_U[i, j] == pytest.approx(B_U[j, i], abs=1e-10)
                if i != j:
                    assert B_x[i, j] == pytest.approx(
                        self.X[i] - self.X[j], abs=0.01
                    )

    def test_positive_off_diagonal_uncertainty(self, bilateral_result):
        bi, _ = bilateral_result
        B_U = np.array(bi["B_U"])
        n = len(self.X)
        for i in range(n):
            for j in range(n):
                if i != j:
                    assert B_U[i, j] > 0
