"""
Tests for CFD Boundary Layer Validation and Grid Convergence Analysis.

"""

import json
import os
import pytest


@pytest.fixture
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        data = json.load(f)
    return data


class TestJSONStructure:
    """Verify the output JSON has all required top-level and nested keys."""

    def test_top_level_keys(self, results):
        for key in ["boundary_layer", "skin_friction", "grid_convergence"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_boundary_layer_keys(self, results):
        bl = results["boundary_layer"]
        for re in ["re250k", "re650k"]:
            assert re in bl, f"Missing boundary_layer.{re}"
            for param in ["delta_star", "theta", "H"]:
                assert param in bl[re], f"Missing boundary_layer.{re}.{param}"
                assert isinstance(bl[re][param], (int, float)), \
                    f"boundary_layer.{re}.{param} must be numeric"

    def test_skin_friction_keys(self, results):
        sf = results["skin_friction"]
        for re in ["re250k", "re650k"]:
            assert re in sf, f"Missing skin_friction.{re}"
            for param in ["u_tau", "Cf"]:
                assert param in sf[re], f"Missing skin_friction.{re}.{param}"
                assert isinstance(sf[re][param], (int, float)), \
                    f"skin_friction.{re}.{param} must be numeric"

    def test_grid_convergence_keys(self, results):
        gc = results["grid_convergence"]
        for qty in ["Cd", "Cf_crest", "Cp_te"]:
            assert qty in gc, f"Missing grid_convergence.{qty}"
            assert "convergence_type" in gc[qty], \
                f"Missing grid_convergence.{qty}.convergence_type"


class TestBoundaryLayerIntegrals:
    """Verify BL integral parameters match published experimental values."""

    # Published values from Virginia Tech wind tunnel measurements
    # Tolerances account for different integration methods and sparse data
    PUBLISHED_RE250K = {"delta_star": 0.0084, "theta": 0.0061}
    PUBLISHED_RE650K = {"delta_star": 0.0069, "theta": 0.0052}
    TOLERANCE = 0.20  # 20% relative tolerance

    def test_re250k_delta_star(self, results):
        val = results["boundary_layer"]["re250k"]["delta_star"]
        ref = self.PUBLISHED_RE250K["delta_star"]
        assert val > 0, "delta_star must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < self.TOLERANCE, \
            f"Re250K delta*={val:.6f}, expected ~{ref} (err={rel_err*100:.1f}%)"

    def test_re250k_theta(self, results):
        val = results["boundary_layer"]["re250k"]["theta"]
        ref = self.PUBLISHED_RE250K["theta"]
        assert val > 0, "theta must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < self.TOLERANCE, \
            f"Re250K theta={val:.6f}, expected ~{ref} (err={rel_err*100:.1f}%)"

    def test_re250k_shape_factor(self, results):
        bl = results["boundary_layer"]["re250k"]
        H = bl["H"]
        # For turbulent BL, H is typically between 1.2 and 1.6
        assert 1.1 < H < 1.7, f"Re250K shape factor H={H:.3f} outside physical range [1.1, 1.7]"
        # Check consistency: H = delta_star / theta
        H_computed = bl["delta_star"] / bl["theta"]
        assert abs(H - H_computed) / H_computed < 0.01, \
            f"H={H:.4f} inconsistent with delta*/theta={H_computed:.4f}"

    def test_re650k_delta_star(self, results):
        val = results["boundary_layer"]["re650k"]["delta_star"]
        ref = self.PUBLISHED_RE650K["delta_star"]
        assert val > 0, "delta_star must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < self.TOLERANCE, \
            f"Re650K delta*={val:.6f}, expected ~{ref} (err={rel_err*100:.1f}%)"

    def test_re650k_theta(self, results):
        val = results["boundary_layer"]["re650k"]["theta"]
        ref = self.PUBLISHED_RE650K["theta"]
        assert val > 0, "theta must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < self.TOLERANCE, \
            f"Re650K theta={val:.6f}, expected ~{ref} (err={rel_err*100:.1f}%)"

    def test_re650k_shape_factor(self, results):
        bl = results["boundary_layer"]["re650k"]
        H = bl["H"]
        assert 1.1 < H < 1.7, f"Re650K shape factor H={H:.3f} outside physical range"

    def test_reynolds_number_trend(self, results):
        """Higher Re should give thinner BL (smaller delta*, theta)."""
        bl250 = results["boundary_layer"]["re250k"]
        bl650 = results["boundary_layer"]["re650k"]
        assert bl650["delta_star"] < bl250["delta_star"], \
            "delta* should decrease with increasing Re"
        assert bl650["theta"] < bl250["theta"], \
            "theta should decrease with increasing Re"


class TestSkinFriction:
    """Verify Spalding-derived skin friction parameters."""

    # Published u_tau from PIV measurements
    UTAU_RE250K = 0.8   # m/s
    UTAU_RE650K = 2.0   # m/s
    TOLERANCE = 0.20    # 20% relative tolerance

    def test_re250k_utau(self, results):
        val = results["skin_friction"]["re250k"]["u_tau"]
        assert val > 0, "u_tau must be positive"
        rel_err = abs(val - self.UTAU_RE250K) / self.UTAU_RE250K
        assert rel_err < self.TOLERANCE, \
            f"Re250K u_tau={val:.4f}, expected ~{self.UTAU_RE250K} (err={rel_err*100:.1f}%)"

    def test_re250k_cf(self, results):
        sf = results["skin_friction"]["re250k"]
        Cf = sf["Cf"]
        assert Cf > 0, "Cf must be positive"
        # Verify Cf = 2 * (u_tau / U_e)^2 consistency
        # U_e for PIV Re250K is 22.15
        Cf_from_utau = 2.0 * (sf["u_tau"] / 22.15) ** 2
        rel_err = abs(Cf - Cf_from_utau) / Cf_from_utau
        assert rel_err < 0.05, \
            f"Cf={Cf:.6f} inconsistent with 2*(u_tau/U_e)^2={Cf_from_utau:.6f}"
        # Physical range for turbulent BL Cf
        assert 0.001 < Cf < 0.01, f"Cf={Cf:.6f} outside physical range [0.001, 0.01]"

    def test_re650k_utau(self, results):
        val = results["skin_friction"]["re650k"]["u_tau"]
        assert val > 0, "u_tau must be positive"
        rel_err = abs(val - self.UTAU_RE650K) / self.UTAU_RE650K
        assert rel_err < self.TOLERANCE, \
            f"Re650K u_tau={val:.4f}, expected ~{self.UTAU_RE650K} (err={rel_err*100:.1f}%)"

    def test_re650k_cf(self, results):
        sf = results["skin_friction"]["re650k"]
        Cf = sf["Cf"]
        assert Cf > 0, "Cf must be positive"
        Cf_from_utau = 2.0 * (sf["u_tau"] / 58.35) ** 2
        rel_err = abs(Cf - Cf_from_utau) / Cf_from_utau
        assert rel_err < 0.05, \
            f"Cf={Cf:.6f} inconsistent with 2*(u_tau/U_e)^2={Cf_from_utau:.6f}"
        assert 0.001 < Cf < 0.01, f"Cf={Cf:.6f} outside physical range"

    def test_reynolds_number_trend(self, results):
        """Cf should decrease with increasing Re for ZPG TBL."""
        sf250 = results["skin_friction"]["re250k"]
        sf650 = results["skin_friction"]["re650k"]
        assert sf650["Cf"] < sf250["Cf"], \
            "Cf should decrease with increasing Re"
        assert sf650["u_tau"] > sf250["u_tau"], \
            "u_tau should increase with increasing Re (higher velocities)"


class TestGridConvergence:
    """Verify Richardson extrapolation and GCI computation."""

    # Analytically computed reference values from the provided grid data
    # Using 3 finest grids with r = 2.0

    # Cd: eps21=3.7e-5, eps32=1.3e-4, p=1.8129, f_ext=0.004641, GCI=0.003952
    CD_P = 1.8129
    CD_FEXT = 0.004641
    CD_GCI = 0.003952

    # Cf_crest: eps21=4.0e-5, eps32=1.2e-4, p=1.5850, f_ext=0.006061, GCI=0.004111
    CF_P = 1.5850
    CF_FEXT = 0.006061
    CF_GCI = 0.004111

    TIGHT_TOL = 0.05  # 5% for numerical results

    def test_cd_convergence_type(self, results):
        gc = results["grid_convergence"]["Cd"]
        assert gc["convergence_type"] == "monotonic", \
            "Cd convergence should be monotonic"

    def test_cd_observed_order(self, results):
        gc = results["grid_convergence"]["Cd"]
        p = gc["observed_order"]
        rel_err = abs(p - self.CD_P) / self.CD_P
        assert rel_err < self.TIGHT_TOL, \
            f"Cd observed order p={p:.4f}, expected {self.CD_P:.4f} (err={rel_err*100:.1f}%)"

    def test_cd_extrapolated(self, results):
        gc = results["grid_convergence"]["Cd"]
        f_ext = gc["f_extrapolated"]
        rel_err = abs(f_ext - self.CD_FEXT) / abs(self.CD_FEXT)
        assert rel_err < self.TIGHT_TOL, \
            f"Cd f_ext={f_ext:.6f}, expected {self.CD_FEXT:.6f} (err={rel_err*100:.1f}%)"

    def test_cd_gci(self, results):
        gc = results["grid_convergence"]["Cd"]
        gci = gc["GCI_fine"]
        rel_err = abs(gci - self.CD_GCI) / self.CD_GCI
        assert rel_err < 0.10, \
            f"Cd GCI={gci:.6f}, expected {self.CD_GCI:.6f} (err={rel_err*100:.1f}%)"

    def test_cf_crest_convergence_type(self, results):
        gc = results["grid_convergence"]["Cf_crest"]
        assert gc["convergence_type"] == "monotonic", \
            "Cf_crest convergence should be monotonic"

    def test_cf_crest_observed_order(self, results):
        gc = results["grid_convergence"]["Cf_crest"]
        p = gc["observed_order"]
        rel_err = abs(p - self.CF_P) / self.CF_P
        assert rel_err < self.TIGHT_TOL, \
            f"Cf_crest observed order p={p:.4f}, expected {self.CF_P:.4f}"

    def test_cf_crest_extrapolated(self, results):
        gc = results["grid_convergence"]["Cf_crest"]
        f_ext = gc["f_extrapolated"]
        rel_err = abs(f_ext - self.CF_FEXT) / abs(self.CF_FEXT)
        assert rel_err < self.TIGHT_TOL, \
            f"Cf_crest f_ext={f_ext:.6f}, expected {self.CF_FEXT:.6f}"

    def test_cf_crest_gci(self, results):
        gc = results["grid_convergence"]["Cf_crest"]
        gci = gc["GCI_fine"]
        rel_err = abs(gci - self.CF_GCI) / self.CF_GCI
        assert rel_err < 0.10, \
            f"Cf_crest GCI={gci:.6f}, expected {self.CF_GCI:.6f}"

    def test_cp_te_oscillatory(self, results):
        gc = results["grid_convergence"]["Cp_te"]
        assert gc["convergence_type"] == "oscillatory", \
            "Cp_te convergence should be oscillatory (eps32/eps21 < 0)"

    def test_cp_te_no_extrapolation(self, results):
        gc = results["grid_convergence"]["Cp_te"]
        # Should NOT have extrapolated value for oscillatory convergence
        if "f_extrapolated" in gc:
            assert gc["f_extrapolated"] is None, \
                "Oscillatory convergence should not have f_extrapolated"

    def test_observed_order_physical(self, results):
        """Observed order should be between 0 and 3 for realistic CFD."""
        for qty in ["Cd", "Cf_crest"]:
            gc = results["grid_convergence"][qty]
            if gc["convergence_type"] == "monotonic":
                p = gc["observed_order"]
                assert 0.5 < p < 3.5, \
                    f"{qty} observed order p={p:.2f} outside physical range [0.5, 3.5]"

    def test_gci_positive(self, results):
        """GCI values must be positive."""
        for qty in ["Cd", "Cf_crest"]:
            gc = results["grid_convergence"][qty]
            if gc["convergence_type"] == "monotonic":
                assert gc["GCI_fine"] > 0, f"{qty} GCI must be positive"
                assert gc["GCI_fine"] < 0.5, f"{qty} GCI={gc['GCI_fine']:.4f} unreasonably large"
