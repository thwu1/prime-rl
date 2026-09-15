
import json
import math
import os
import pytest


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    def test_top_level_keys(self, results):
        required = {"gci_analysis", "boundary_layer", "sa_model", "law_of_wall", "grid_metrics"}
        assert required.issubset(set(results.keys())), (
            f"Missing top-level keys: {required - set(results.keys())}"
        )

    def test_gci_has_skin_friction_and_drag(self, results):
        gci = results["gci_analysis"]
        assert "skin_friction" in gci
        assert "drag" in gci

    def test_gci_has_both_codes(self, results):
        for qty in ["skin_friction", "drag"]:
            section = results["gci_analysis"][qty]
            assert "cfl3d" in section, f"Missing cfl3d in gci_analysis.{qty}"
            assert "fun3d" in section, f"Missing fun3d in gci_analysis.{qty}"


class TestGCISkinFriction:
    """Verify Richardson extrapolation and GCI for skin friction at x=0.97."""

    def test_cfl3d_apparent_order(self, results):
        p = results["gci_analysis"]["skin_friction"]["cfl3d"]["apparent_order"]
        assert abs(p - 1.984) < 0.06, f"CFL3D Cf apparent order {p} not near 1.984"

    def test_fun3d_apparent_order(self, results):
        p = results["gci_analysis"]["skin_friction"]["fun3d"]["apparent_order"]
        assert abs(p - 1.341) < 0.06, f"FUN3D Cf apparent order {p} not near 1.341"

    def test_cfl3d_relative_error(self, results):
        e = results["gci_analysis"]["skin_friction"]["cfl3d"]["relative_error_percent"]
        assert abs(e - 0.0412) < 0.005, f"CFL3D Cf relative error {e}% not near 0.041%"

    def test_fun3d_relative_error(self, results):
        e = results["gci_analysis"]["skin_friction"]["fun3d"]["relative_error_percent"]
        assert abs(e - 0.0340) < 0.005, f"FUN3D Cf relative error {e}% not near 0.034%"

    def test_cfl3d_gci(self, results):
        g = results["gci_analysis"]["skin_friction"]["cfl3d"]["gci_fine_percent"]
        assert abs(g - 0.0174) < 0.005, f"CFL3D Cf GCI {g}% not near 0.017%"

    def test_fun3d_gci(self, results):
        g = results["gci_analysis"]["skin_friction"]["fun3d"]["gci_fine_percent"]
        assert abs(g - 0.0277) < 0.005, f"FUN3D Cf GCI {g}% not near 0.028%"

    def test_cfl3d_fine_grid_value(self, results):
        v = results["gci_analysis"]["skin_friction"]["cfl3d"]["fine_grid_value"]
        assert abs(v - 0.00270562) < 1e-6, f"CFL3D fine Cf={v} not near 0.002706"

    def test_fun3d_fine_grid_value(self, results):
        v = results["gci_analysis"]["skin_friction"]["fun3d"]["fine_grid_value"]
        assert abs(v - 0.00270540) < 1e-6, f"FUN3D fine Cf={v} not near 0.002705"

    def test_extrapolated_values_consistent(self, results):
        """Both codes should extrapolate to nearly the same grid-converged value."""
        ext_cfl3d = results["gci_analysis"]["skin_friction"]["cfl3d"]["extrapolated_value"]
        ext_fun3d = results["gci_analysis"]["skin_friction"]["fun3d"]["extrapolated_value"]
        assert abs(ext_cfl3d - ext_fun3d) / ext_cfl3d < 0.002, (
            f"Extrapolated Cf values differ too much: CFL3D={ext_cfl3d}, FUN3D={ext_fun3d}"
        )


class TestGCIDrag:
    """Verify Richardson extrapolation and GCI for integrated drag coefficient."""

    def test_cfl3d_apparent_order(self, results):
        p = results["gci_analysis"]["drag"]["cfl3d"]["apparent_order"]
        assert abs(p - 1.750) < 0.06, f"CFL3D drag apparent order {p} not near 1.75"

    def test_fun3d_apparent_order(self, results):
        p = results["gci_analysis"]["drag"]["fun3d"]["apparent_order"]
        assert abs(p - 0.798) < 0.06, f"FUN3D drag apparent order {p} not near 0.80"

    def test_cfl3d_relative_error(self, results):
        e = results["gci_analysis"]["drag"]["cfl3d"]["relative_error_percent"]
        assert abs(e - 0.0509) < 0.005, f"CFL3D drag relative error {e}% not near 0.051%"

    def test_fun3d_relative_error(self, results):
        e = results["gci_analysis"]["drag"]["fun3d"]["relative_error_percent"]
        assert abs(e - 0.159) < 0.01, f"FUN3D drag relative error {e}% not near 0.159%"

    def test_cfl3d_gci(self, results):
        g = results["gci_analysis"]["drag"]["cfl3d"]["gci_fine_percent"]
        assert abs(g - 0.0269) < 0.005, f"CFL3D drag GCI {g}% not near 0.027%"

    def test_fun3d_gci(self, results):
        g = results["gci_analysis"]["drag"]["fun3d"]["gci_fine_percent"]
        assert abs(g - 0.269) < 0.015, f"FUN3D drag GCI {g}% not near 0.269%"


class TestBoundaryLayer:
    """Verify boundary layer integral quantities from velocity profile at x=0.97."""

    def test_u_edge(self, results):
        ue = results["boundary_layer"]["u_edge"]
        assert abs(ue - 1.0) < 0.01, f"u_edge={ue} should be near 1.0"

    def test_delta_99_range(self, results):
        d99 = results["boundary_layer"]["delta_99"]
        assert 0.012 < d99 < 0.020, f"delta_99={d99} out of range [0.012, 0.020]"

    def test_delta_99_value(self, results):
        d99 = results["boundary_layer"]["delta_99"]
        assert abs(d99 - 0.01457) < 0.002, f"delta_99={d99} not near 0.01457"

    def test_displacement_thickness(self, results):
        ds = results["boundary_layer"]["displacement_thickness"]
        assert 0.0015 < ds < 0.004, f"displacement_thickness={ds} out of range"

    def test_momentum_thickness(self, results):
        th = results["boundary_layer"]["momentum_thickness"]
        assert 0.001 < th < 0.003, f"momentum_thickness={th} out of range"

    def test_shape_factor_turbulent(self, results):
        H = results["boundary_layer"]["shape_factor"]
        assert 1.2 < H < 1.5, f"Shape factor H={H} not in turbulent range [1.2, 1.5]"

    def test_shape_factor_value(self, results):
        H = results["boundary_layer"]["shape_factor"]
        assert abs(H - 1.306) < 0.05, f"Shape factor H={H} not near 1.306"

    def test_displacement_gt_momentum(self, results):
        ds = results["boundary_layer"]["displacement_thickness"]
        th = results["boundary_layer"]["momentum_thickness"]
        assert ds > th, "Displacement thickness must be > momentum thickness"


class TestSAModel:
    """Verify Spalart-Allmaras turbulence model auxiliary function implementations."""

    def test_fv1_chi_1(self, results):
        v = results["sa_model"]["fv1_at_chi_1"]
        expected = 1.0 / (1.0 + 7.1**3)
        assert abs(v - expected) < 1e-6, f"fv1(1)={v} expected {expected}"

    def test_fv1_chi_10(self, results):
        v = results["sa_model"]["fv1_at_chi_10"]
        expected = 1000.0 / (1000.0 + 7.1**3)
        assert abs(v - expected) < 1e-4, f"fv1(10)={v} expected {expected}"

    def test_fv2_chi_1(self, results):
        v = results["sa_model"]["fv2_at_chi_1"]
        fv1_1 = 1.0 / (1.0 + 7.1**3)
        expected = 1.0 - 1.0 / (1.0 + fv1_1)
        assert abs(v - expected) < 1e-5, f"fv2(1)={v} expected {expected}"

    def test_fv2_chi_10(self, results):
        v = results["sa_model"]["fv2_at_chi_10"]
        fv1_10 = 1000.0 / (1000.0 + 7.1**3)
        expected = 1.0 - 10.0 / (1.0 + 10.0 * fv1_10)
        assert abs(v - expected) < 1e-4, f"fv2(10)={v} expected {expected}"

    def test_fw_at_r_0p5(self, results):
        v = results["sa_model"]["fw_at_r_0p5"]
        cw2, cw3 = 0.3, 2.0
        r = 0.5
        g = r + cw2 * (r**6 - r)
        expected = g * ((1 + cw3**6) / (g**6 + cw3**6)) ** (1.0 / 6.0)
        assert abs(v - expected) < 1e-5, f"fw(0.5)={v} expected {expected}"

    def test_fw_at_r_1(self, results):
        v = results["sa_model"]["fw_at_r_1"]
        assert abs(v - 1.0) < 1e-6, f"fw(1)={v} should be exactly 1.0"

    def test_cw1(self, results):
        v = results["sa_model"]["cw1"]
        expected = 0.1355 / 0.41**2 + (1 + 0.622) / (2.0 / 3.0)
        assert abs(v - expected) < 1e-4, f"cw1={v} expected {expected}"

    def test_peak_mut_positive(self, results):
        pm = results["sa_model"]["peak_mut_over_mu_inf"]
        assert pm > 100, f"peak_mut_over_mu_inf={pm} should be > 100"

    def test_peak_mut_value(self, results):
        pm = results["sa_model"]["peak_mut_over_mu_inf"]
        assert abs(pm - 208.3) < 5.0, f"peak_mut_over_mu_inf={pm} not near 208.3"

    def test_y_at_peak_mut(self, results):
        yp = results["sa_model"]["y_at_peak_mut"]
        assert 0.005 < yp < 0.010, f"y_at_peak_mut={yp} out of expected range"


class TestLawOfWall:
    """Verify Spalding law of the wall fitting to CFD velocity profile."""

    def test_kappa_near_041(self, results):
        k = results["law_of_wall"]["kappa"]
        assert 0.35 < k < 0.50, f"Fitted kappa={k} not in range [0.35, 0.50]"

    def test_B_reasonable(self, results):
        B = results["law_of_wall"]["B"]
        assert 3.5 < B < 8.0, f"Fitted B={B} not in range [3.5, 8.0]"

    def test_rms_deviation_small(self, results):
        rms = results["law_of_wall"]["rms_log_deviation"]
        assert rms < 0.1, f"RMS log deviation={rms} too large (should be < 0.1)"

    def test_kappa_positive(self, results):
        k = results["law_of_wall"]["kappa"]
        assert k > 0, "kappa must be positive"

    def test_B_positive(self, results):
        B = results["law_of_wall"]["B"]
        assert B > 0, "B must be positive"


class TestGridMetrics:
    """Verify PLOT2D grid parsing and mesh quality metrics."""

    def test_nx(self, results):
        assert results["grid_metrics"]["nx"] == 35, f"nx={results['grid_metrics']['nx']} should be 35"

    def test_ny(self, results):
        assert results["grid_metrics"]["ny"] == 25, f"ny={results['grid_metrics']['ny']} should be 25"

    def test_x_range_min(self, results):
        xr = results["grid_metrics"]["x_range"]
        assert abs(xr[0] - (-0.33333)) < 0.001, f"x_min={xr[0]} should be near -0.333"

    def test_x_range_max(self, results):
        xr = results["grid_metrics"]["x_range"]
        assert abs(xr[1] - 2.0) < 0.001, f"x_max={xr[1]} should be near 2.0"

    def test_y_range_min(self, results):
        yr = results["grid_metrics"]["y_range"]
        assert abs(yr[0]) < 1e-4, f"y_min={yr[0]} should be near 0"

    def test_y_range_max(self, results):
        yr = results["grid_metrics"]["y_range"]
        assert abs(yr[1] - 1.0) < 0.01, f"y_max={yr[1]} should be near 1.0"

    def test_first_cell_height(self, results):
        fch = results["grid_metrics"]["first_cell_height"]
        assert 1e-6 < fch < 1e-4, f"first_cell_height={fch} out of range"

    def test_stretching_ratio(self, results):
        sr = results["grid_metrics"]["max_wall_normal_stretching_ratio"]
        assert 1.0 < sr < 2.0, f"stretching_ratio={sr} out of reasonable range [1.0, 2.0]"


class TestPhysicalConsistency:
    """Cross-check physical consistency of the results."""

    def test_gci_cf_codes_agree(self, results):
        """Both codes should produce similar fine-grid skin friction."""
        cf_cfl3d = results["gci_analysis"]["skin_friction"]["cfl3d"]["fine_grid_value"]
        cf_fun3d = results["gci_analysis"]["skin_friction"]["fun3d"]["fine_grid_value"]
        rel_diff = abs(cf_cfl3d - cf_fun3d) / cf_cfl3d
        assert rel_diff < 0.001, f"Fine-grid Cf values differ by {rel_diff*100:.3f}%"

    def test_gci_drag_codes_agree(self, results):
        """Both codes should produce similar fine-grid drag."""
        cd_cfl3d = results["gci_analysis"]["drag"]["cfl3d"]["fine_grid_value"]
        cd_fun3d = results["gci_analysis"]["drag"]["fun3d"]["fine_grid_value"]
        rel_diff = abs(cd_cfl3d - cd_fun3d) / cd_cfl3d
        assert rel_diff < 0.005, f"Fine-grid drag values differ by {rel_diff*100:.3f}%"

    def test_drag_gt_cf(self, results):
        """Integrated drag should be larger than local Cf at x=0.97."""
        cf = results["gci_analysis"]["skin_friction"]["cfl3d"]["fine_grid_value"]
        cd = results["gci_analysis"]["drag"]["cfl3d"]["fine_grid_value"]
        assert cd > cf, "Integrated drag should exceed local skin friction"

    def test_bl_consistent_with_re(self, results):
        """Boundary layer thickness should be consistent with Re_x ~ 5M."""
        d99 = results["boundary_layer"]["delta_99"]
        theta = results["boundary_layer"]["momentum_thickness"]
        re_theta = theta * 5e6 / 0.97
        assert 2000 < re_theta < 15000, f"Re_theta={re_theta} not in turbulent range"
