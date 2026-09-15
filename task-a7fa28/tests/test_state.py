
"""
Tests for CFD verification audit report.
Validates discretization uncertainty analysis, grid quality metrics,
convergence assessment, boundary layer quantities, and SA model verification
against NASA Turbulence Modeling Resource reference values.
"""

import json
import math
import os
import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.isfile(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ---------- Structure tests ----------

class TestStructure:
    def test_top_level_keys(self, results):
        for key in ("gci", "convergence_assessment", "grid_quality",
                     "boundary_layer", "sa_verification"):
            assert key in results, f"Missing top-level key: {key}"

    def test_gci_structure(self, results):
        gci = results["gci"]
        for metric in ("skin_friction", "drag"):
            assert metric in gci, f"Missing gci.{metric}"
            for code in ("CFL3D", "FUN3D"):
                assert code in gci[metric], f"Missing gci.{metric}.{code}"
                entry = gci[metric][code]
                for field in ("p", "ea21_pct", "eext21_pct",
                              "gci_fine_pct", "f_extrapolated"):
                    assert field in entry, f"Missing gci.{metric}.{code}.{field}"

    def test_convergence_assessment_structure(self, results):
        ca = results["convergence_assessment"]
        for metric in ("skin_friction", "drag"):
            assert metric in ca, f"Missing convergence_assessment.{metric}"
            for code in ("CFL3D", "FUN3D"):
                assert code in ca[metric], f"Missing convergence_assessment.{metric}.{code}"
                entry = ca[metric][code]
                for field in ("monotonic", "in_asymptotic_range"):
                    assert field in entry, (
                        f"Missing convergence_assessment.{metric}.{code}.{field}"
                    )

    def test_grid_quality_structure(self, results):
        gq = results["grid_quality"]
        for field in ("dimensions", "min_wall_spacing",
                      "max_stretching_ratio", "plate_points"):
            assert field in gq, f"Missing grid_quality.{field}"

    def test_boundary_layer_structure(self, results):
        bl = results["boundary_layer"]
        for field in ("delta_99", "delta_star", "theta", "shape_factor"):
            assert field in bl, f"Missing boundary_layer.{field}"

    def test_sa_verification_structure(self, results):
        sa = results["sa_verification"]
        for field in ("peak_chi", "peak_y", "freestream_chi",
                      "peak_mut_over_mu"):
            assert field in sa, f"Missing sa_verification.{field}"


# ---------- GCI analysis tests ----------
# Reference values derived from NASA TMR flat plate SA verification data

GCI_REFS = {
    "skin_friction": {
        "CFL3D": {"p": 1.98, "ea21_pct": 0.041, "eext21_pct": 0.014,
                   "gci_fine_pct": 0.017},
        "FUN3D": {"p": 1.34, "ea21_pct": 0.034, "eext21_pct": 0.022,
                   "gci_fine_pct": 0.028},
    },
    "drag": {
        "CFL3D": {"p": 1.75, "ea21_pct": 0.051, "eext21_pct": 0.022,
                   "gci_fine_pct": 0.027},
        "FUN3D": {"p": 0.80, "ea21_pct": 0.159, "eext21_pct": 0.215,
                   "gci_fine_pct": 0.269},
    },
}

F_EXT_REFS = {
    "skin_friction": {
        "CFL3D": 2.7052e-3,
        "FUN3D": 2.7060e-3,
    },
    "drag": {
        "CFL3D": 2.8592e-3,
        "FUN3D": 2.8586e-3,
    },
}


class TestGCI:
    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_apparent_order(self, results, metric, code):
        p = results["gci"][metric][code]["p"]
        ref = GCI_REFS[metric][code]["p"]
        assert abs(p - ref) < 0.08, (
            f"Apparent order p for {code} {metric}: got {p:.4f}, expected ~{ref}"
        )

    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_approximate_error(self, results, metric, code):
        ea = results["gci"][metric][code]["ea21_pct"]
        ref = GCI_REFS[metric][code]["ea21_pct"]
        assert abs(ea - ref) < 0.01, (
            f"ea21 for {code} {metric}: got {ea:.4f}%, expected ~{ref}%"
        )

    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_extrapolated_error(self, results, metric, code):
        eext = results["gci"][metric][code]["eext21_pct"]
        ref = GCI_REFS[metric][code]["eext21_pct"]
        tol = max(0.008, 0.15 * ref)
        assert abs(eext - ref) < tol, (
            f"eext21 for {code} {metric}: got {eext:.4f}%, expected ~{ref}%"
        )

    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_gci_fine(self, results, metric, code):
        gci = results["gci"][metric][code]["gci_fine_pct"]
        ref = GCI_REFS[metric][code]["gci_fine_pct"]
        tol = max(0.008, 0.15 * ref)
        assert abs(gci - ref) < tol, (
            f"GCI_fine for {code} {metric}: got {gci:.4f}%, expected ~{ref}%"
        )

    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_extrapolated_value(self, results, metric, code):
        f_ext = results["gci"][metric][code]["f_extrapolated"]
        ref = F_EXT_REFS[metric][code]
        rel_err = abs(f_ext - ref) / ref
        assert rel_err < 0.005, (
            f"f_extrapolated for {code} {metric}: got {f_ext:.6e}, "
            f"expected ~{ref:.4e}"
        )

    def test_cfl3d_cf_converges_from_above(self, results):
        """CFL3D skin friction should converge monotonically from above."""
        f_ext = results["gci"]["skin_friction"]["CFL3D"]["f_extrapolated"]
        assert f_ext < 0.00270562153 + 1e-7

    def test_extrapolated_cf_agreement(self, results):
        """Both codes should extrapolate to approximately the same cf."""
        f_cfl3d = results["gci"]["skin_friction"]["CFL3D"]["f_extrapolated"]
        f_fun3d = results["gci"]["skin_friction"]["FUN3D"]["f_extrapolated"]
        rel_diff = abs(f_cfl3d - f_fun3d) / f_cfl3d
        assert rel_diff < 0.005, (
            f"Extrapolated cf disagree: CFL3D={f_cfl3d:.6e}, FUN3D={f_fun3d:.6e}"
        )


# ---------- Convergence assessment tests ----------

class TestConvergenceAssessment:
    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_monotonic_is_bool(self, results, metric, code):
        val = results["convergence_assessment"][metric][code]["monotonic"]
        assert isinstance(val, bool), f"monotonic should be bool, got {type(val)}"

    @pytest.mark.parametrize("metric", ["skin_friction", "drag"])
    @pytest.mark.parametrize("code", ["CFL3D", "FUN3D"])
    def test_all_convergence_is_monotonic(self, results, metric, code):
        """All four code/metric combinations converge monotonically."""
        val = results["convergence_assessment"][metric][code]["monotonic"]
        assert val is True, (
            f"{code} {metric} convergence should be monotonic"
        )

    def test_cfl3d_cf_in_asymptotic_range(self, results):
        """CFL3D cf has p~1.98, clearly in asymptotic range for 2nd order."""
        val = results["convergence_assessment"]["skin_friction"]["CFL3D"]
        assert val["in_asymptotic_range"] is True

    def test_fun3d_cf_not_in_asymptotic_range(self, results):
        """FUN3D cf has p~1.34, not in asymptotic range for 2nd order."""
        val = results["convergence_assessment"]["skin_friction"]["FUN3D"]
        assert val["in_asymptotic_range"] is False

    def test_cfl3d_drag_in_asymptotic_range(self, results):
        """CFL3D drag has p~1.75, reasonably in asymptotic range."""
        val = results["convergence_assessment"]["drag"]["CFL3D"]
        assert val["in_asymptotic_range"] is True

    def test_fun3d_drag_not_in_asymptotic_range(self, results):
        """FUN3D drag has p~0.80, clearly not in asymptotic range."""
        val = results["convergence_assessment"]["drag"]["FUN3D"]
        assert val["in_asymptotic_range"] is False

    def test_asymptotic_consistency_with_p(self, results):
        """Asymptotic range should correlate with p being close to 2."""
        for metric in ("skin_friction", "drag"):
            for code in ("CFL3D", "FUN3D"):
                p = results["gci"][metric][code]["p"]
                asym = results["convergence_assessment"][metric][code][
                    "in_asymptotic_range"
                ]
                if asym:
                    assert p > 1.4, (
                        f"{code} {metric}: claims asymptotic but p={p:.2f}<1.4"
                    )
                else:
                    assert p < 1.6, (
                        f"{code} {metric}: claims not asymptotic but p={p:.2f}>1.6"
                    )


# ---------- Grid quality tests ----------

class TestGridQuality:
    def test_dimensions(self, results):
        dims = results["grid_quality"]["dimensions"]
        assert dims == [35, 25], f"Expected [35, 25], got {dims}"

    def test_min_wall_spacing(self, results):
        ws = results["grid_quality"]["min_wall_spacing"]
        assert abs(ws - 8.32e-6) < 0.1e-6, (
            f"min_wall_spacing = {ws:.4e}, expected ~8.32e-6"
        )

    def test_min_wall_spacing_order(self, results):
        """Wall spacing should be O(10^-6) for this grid."""
        ws = results["grid_quality"]["min_wall_spacing"]
        assert 1e-7 < ws < 1e-4, f"min_wall_spacing = {ws} out of range"

    def test_max_stretching_ratio(self, results):
        sr = results["grid_quality"]["max_stretching_ratio"]
        assert abs(sr - 1.629) < 0.02, (
            f"max_stretching_ratio = {sr:.4f}, expected ~1.629"
        )

    def test_stretching_ratio_reasonable(self, results):
        """Stretching ratio should be between 1.0 and 2.0 for a CFD grid."""
        sr = results["grid_quality"]["max_stretching_ratio"]
        assert 1.0 < sr < 2.0, f"max_stretching_ratio = {sr} unreasonable"

    def test_plate_points(self, results):
        pp = results["grid_quality"]["plate_points"]
        assert pp == 29, f"plate_points = {pp}, expected 29"

    def test_plate_points_reasonable(self, results):
        """Should have more than 10 points on plate for any useful grid."""
        pp = results["grid_quality"]["plate_points"]
        assert pp > 10, f"plate_points = {pp} too few"


# ---------- Boundary layer tests ----------

class TestBoundaryLayer:
    def test_delta_99_range(self, results):
        d99 = results["boundary_layer"]["delta_99"]
        assert 0.010 < d99 < 0.020, f"delta_99 = {d99} out of physical range"

    def test_delta_99_value(self, results):
        d99 = results["boundary_layer"]["delta_99"]
        assert abs(d99 - 0.0143) < 0.002, f"delta_99 = {d99}, expected ~0.0143"

    def test_delta_star_range(self, results):
        ds = results["boundary_layer"]["delta_star"]
        assert 1.5e-3 < ds < 2.5e-3, f"delta_star = {ds} out of physical range"

    def test_delta_star_value(self, results):
        ds = results["boundary_layer"]["delta_star"]
        assert abs(ds - 1.963e-3) < 0.15e-3, (
            f"delta_star = {ds}, expected ~1.963e-3"
        )

    def test_theta_range(self, results):
        th = results["boundary_layer"]["theta"]
        assert 1.0e-3 < th < 2.0e-3, f"theta = {th} out of physical range"

    def test_theta_value(self, results):
        th = results["boundary_layer"]["theta"]
        assert abs(th - 1.463e-3) < 0.15e-3, (
            f"theta = {th}, expected ~1.463e-3"
        )

    def test_shape_factor_range(self, results):
        H = results["boundary_layer"]["shape_factor"]
        assert 1.2 < H < 1.5, f"Shape factor H = {H} out of turbulent BL range"

    def test_shape_factor_value(self, results):
        H = results["boundary_layer"]["shape_factor"]
        assert abs(H - 1.34) < 0.05, f"Shape factor H = {H}, expected ~1.34"

    def test_consistency(self, results):
        """H must equal delta_star / theta."""
        bl = results["boundary_layer"]
        computed_H = bl["delta_star"] / bl["theta"]
        assert abs(computed_H - bl["shape_factor"]) < 0.01, (
            f"H = {bl['shape_factor']} but delta_star/theta = {computed_H}"
        )


# ---------- SA model verification tests ----------

class TestSAVerification:
    def test_peak_chi_value(self, results):
        peak_chi = results["sa_verification"]["peak_chi"]
        assert abs(peak_chi - 208.34) < 12.0, (
            f"peak_chi = {peak_chi}, expected ~208.34"
        )

    def test_peak_y_in_boundary_layer(self, results):
        peak_y = results["sa_verification"]["peak_y"]
        assert 3e-3 < peak_y < 1.2e-2, (
            f"peak_y = {peak_y}, expected within BL"
        )

    def test_peak_y_value(self, results):
        peak_y = results["sa_verification"]["peak_y"]
        assert abs(peak_y - 6.725e-3) < 1e-3, (
            f"peak_y = {peak_y}, expected ~6.725e-3"
        )

    def test_freestream_chi(self, results):
        fs_chi = results["sa_verification"]["freestream_chi"]
        assert abs(fs_chi - 3.0) < 0.3, (
            f"freestream_chi = {fs_chi}, expected ~3.0"
        )

    def test_peak_mut_over_mu(self, results):
        peak_mm = results["sa_verification"]["peak_mut_over_mu"]
        assert abs(peak_mm - 208.33) < 5.0, (
            f"peak_mut_over_mu = {peak_mm}, expected ~208.33"
        )

    def test_chi_fv1_consistency(self, results):
        """At peak, chi*fv1(chi) should equal peak_mut_over_mu."""
        chi = results["sa_verification"]["peak_chi"]
        cv1 = 7.1
        fv1 = chi ** 3 / (chi ** 3 + cv1 ** 3)
        computed_mut = chi * fv1
        reported_mut = results["sa_verification"]["peak_mut_over_mu"]
        rel_err = abs(computed_mut - reported_mut) / reported_mut
        assert rel_err < 0.01, (
            f"chi*fv1={computed_mut:.4f} but peak_mut={reported_mut:.4f}"
        )

    def test_freestream_chi_fv1_consistency(self, results):
        """Freestream chi~3.0 should give mut/mu~0.21."""
        chi = results["sa_verification"]["freestream_chi"]
        cv1 = 7.1
        fv1 = chi ** 3 / (chi ** 3 + cv1 ** 3)
        fs_mut = chi * fv1
        assert abs(fs_mut - 0.2105) < 0.03, (
            f"Freestream chi={chi:.4f} gives mut/mu={fs_mut:.4f}, expected ~0.21"
        )
