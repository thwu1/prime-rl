
import json
import os
import pytest

REPORT_PATH = "/app/report.json"

# Reference values computed from the NASA TMR data using standard
# grid convergence procedures on the three finest grids.
GC_REFERENCE = {
    "cf_cfl3d": {"order": 1.9839, "uncertainty": 0.0174, "extrap": 0.002705},
    "cf_fun3d": {"order": 1.3411, "uncertainty": 0.0277, "extrap": 0.002706},
    "cd_cfl3d": {"order": 1.7500, "uncertainty": 0.0269, "extrap": 0.002860},
    "cd_fun3d": {"order": 0.7982, "uncertainty": 0.2684, "extrap": 0.002859},
}

EXPECTED_VERDICTS = {
    "cf_cfl3d": "nominal",
    "cf_fun3d": "degraded",
    "cd_cfl3d": "nominal",
    "cd_fun3d": "degraded",
}


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ─── Structure tests ───────────────────────────────────────────────────────

class TestReportStructure:
    def test_has_grid_convergence(self, report):
        assert "grid_convergence" in report

    def test_has_solver_ranking(self, report):
        assert "solver_ranking" in report

    def test_has_boundary_layer(self, report):
        assert "boundary_layer" in report

    def test_has_wall_law_fit(self, report):
        assert "wall_law_fit" in report

    def test_has_publication_ready(self, report):
        assert "publication_ready" in report

    def test_gc_has_all_cases(self, report):
        gc = report["grid_convergence"]
        for key in ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"]:
            assert key in gc, f"grid_convergence must contain '{key}'"

    def test_gc_cases_have_fields(self, report):
        gc = report["grid_convergence"]
        for case in ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"]:
            for field in ["observed_order", "fine_grid_uncertainty_pct",
                          "extrapolated_value", "order_verdict"]:
                assert field in gc[case], f"grid_convergence.{case} must contain '{field}'"

    def test_boundary_layer_fields(self, report):
        bl = report["boundary_layer"]
        for field in ["delta_99", "displacement_thickness", "momentum_thickness",
                      "shape_factor", "re_theta", "wall_cf", "physically_consistent"]:
            assert field in bl, f"boundary_layer must contain '{field}'"

    def test_wall_law_fit_fields(self, report):
        wl = report["wall_law_fit"]
        for field in ["rms_deviation", "max_deviation", "num_points",
                      "log_layer_quality"]:
            assert field in wl, f"wall_law_fit must contain '{field}'"


# ─── Grid convergence value tests ──────────────────────────────────────────

def _approx(computed, reference, label, tol_rel=0.15, tol_abs=0.005):
    if reference == 0:
        assert abs(computed) < tol_abs, f"{label}: expected ~0, got {computed}"
        return
    rel_err = abs(computed - reference) / abs(reference)
    abs_err = abs(computed - reference)
    ok = (rel_err < tol_rel) or (abs_err < tol_abs)
    assert ok, (
        f"{label}: computed={computed:.6f}, reference={reference:.6f}, "
        f"rel_err={rel_err:.2%}, abs_err={abs_err:.6f}"
    )


class TestGridConvergenceValues:
    @pytest.mark.parametrize("case", ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"])
    def test_observed_order(self, report, case):
        p = report["grid_convergence"][case]["observed_order"]
        ref = GC_REFERENCE[case]["order"]
        _approx(p, ref, f"{case}.observed_order", tol_rel=0.10, tol_abs=0.15)

    @pytest.mark.parametrize("case", ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"])
    def test_fine_grid_uncertainty(self, report, case):
        u = report["grid_convergence"][case]["fine_grid_uncertainty_pct"]
        ref = GC_REFERENCE[case]["uncertainty"]
        _approx(u, ref, f"{case}.fine_grid_uncertainty_pct", tol_rel=0.20, tol_abs=0.01)

    @pytest.mark.parametrize("case", ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"])
    def test_extrapolated_value(self, report, case):
        val = report["grid_convergence"][case]["extrapolated_value"]
        ref = GC_REFERENCE[case]["extrap"]
        _approx(val, ref, f"{case}.extrapolated_value", tol_rel=0.005, tol_abs=1e-5)

    @pytest.mark.parametrize("case", ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"])
    def test_all_orders_positive(self, report, case):
        p = report["grid_convergence"][case]["observed_order"]
        assert p > 0, f"{case} observed_order must be positive, got {p}"

    @pytest.mark.parametrize("case", ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"])
    def test_all_uncertainties_positive(self, report, case):
        u = report["grid_convergence"][case]["fine_grid_uncertainty_pct"]
        assert u > 0, f"{case} fine_grid_uncertainty_pct must be positive, got {u}"


# ─── Verdict and ranking tests ─────────────────────────────────────────────

class TestVerdicts:
    @pytest.mark.parametrize("case,expected", list(EXPECTED_VERDICTS.items()))
    def test_order_verdict(self, report, case, expected):
        verdict = report["grid_convergence"][case]["order_verdict"]
        assert verdict == expected, (
            f"{case}: expected order_verdict='{expected}', got '{verdict}'"
        )

    def test_verdict_consistency_with_order(self, report):
        """Verify each verdict is consistent with the reported observed_order."""
        for case in ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"]:
            gc = report["grid_convergence"][case]
            p = gc["observed_order"]
            v = gc["order_verdict"]
            if p >= 1.5:
                assert v == "nominal", f"{case}: order={p} >= 1.5 should be 'nominal'"
            elif p >= 0.5:
                assert v == "degraded", f"{case}: order={p} in [0.5,1.5) should be 'degraded'"
            else:
                assert v == "anomalous", f"{case}: order={p} < 0.5 should be 'anomalous'"


class TestSolverRanking:
    def test_skin_friction_ranking(self, report):
        rank = report["solver_ranking"]["skin_friction"]
        assert rank == "cfl3d", (
            f"CFL3D should rank higher for skin friction, got '{rank}'"
        )

    def test_drag_ranking(self, report):
        rank = report["solver_ranking"]["drag"]
        assert rank == "cfl3d", (
            f"CFL3D should rank higher for drag, got '{rank}'"
        )

    def test_ranking_consistency(self, report):
        """Verify ranking matches the reported uncertainties."""
        gc = report["grid_convergence"]
        for qty, key_a, key_b in [
            ("skin_friction", "cf_cfl3d", "cf_fun3d"),
            ("drag", "cd_cfl3d", "cd_fun3d"),
        ]:
            u_a = gc[key_a]["fine_grid_uncertainty_pct"]
            u_b = gc[key_b]["fine_grid_uncertainty_pct"]
            winner = report["solver_ranking"][qty]
            if u_a < u_b:
                assert winner == "cfl3d", f"{qty}: cfl3d has lower uncertainty but '{winner}' ranked first"
            else:
                assert winner == "fun3d", f"{qty}: fun3d has lower uncertainty but '{winner}' ranked first"


class TestPublicationReady:
    @pytest.mark.parametrize("case", ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"])
    def test_publication_ready_value(self, report, case):
        pr = report["publication_ready"][case]
        assert isinstance(pr, bool), f"{case}: publication_ready must be boolean"

    def test_all_cases_publication_ready(self, report):
        """All four cases should be publication-ready (uncertainty << 1%, order > 0.5)."""
        for case in ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"]:
            assert report["publication_ready"][case] is True, (
                f"{case} should be publication_ready=true"
            )

    def test_publication_ready_consistency(self, report):
        """Verify publication_ready matches the criteria."""
        for case in ["cf_cfl3d", "cf_fun3d", "cd_cfl3d", "cd_fun3d"]:
            gc = report["grid_convergence"][case]
            expected = gc["fine_grid_uncertainty_pct"] < 1.0 and gc["observed_order"] >= 0.5
            assert report["publication_ready"][case] == expected, (
                f"{case}: publication_ready inconsistent with criteria"
            )


# ─── Boundary layer tests ─────────────────────────────────────────────────

class TestBoundaryLayer:
    def test_delta_99_range(self, report):
        d99 = report["boundary_layer"]["delta_99"]
        assert 0.008 < d99 < 0.025, f"delta_99 should be ~0.014, got {d99}"

    def test_displacement_thickness_range(self, report):
        ds = report["boundary_layer"]["displacement_thickness"]
        assert 0.001 < ds < 0.005, f"displacement_thickness should be ~0.002, got {ds}"

    def test_momentum_thickness_range(self, report):
        th = report["boundary_layer"]["momentum_thickness"]
        assert 0.0005 < th < 0.004, f"momentum_thickness should be ~0.0015, got {th}"

    def test_shape_factor_range(self, report):
        H = report["boundary_layer"]["shape_factor"]
        assert 1.15 < H < 1.65, f"Shape factor should be 1.2-1.5, got {H}"

    def test_ordering(self, report):
        bl = report["boundary_layer"]
        assert bl["momentum_thickness"] < bl["displacement_thickness"] < bl["delta_99"]

    def test_shape_factor_consistency(self, report):
        bl = report["boundary_layer"]
        H_computed = bl["displacement_thickness"] / bl["momentum_thickness"]
        H_reported = bl["shape_factor"]
        rel_err = abs(H_computed - H_reported) / H_computed
        assert rel_err < 0.01, (
            f"shape_factor should equal disp/mom: {H_reported} vs {H_computed:.4f}"
        )

    def test_re_theta_range(self, report):
        Re_th = report["boundary_layer"]["re_theta"]
        assert 3000 < Re_th < 15000, f"re_theta should be ~7700, got {Re_th}"

    def test_wall_cf_range(self, report):
        cf = report["boundary_layer"]["wall_cf"]
        assert 0.001 < cf < 0.005, f"wall_cf should be ~0.0027, got {cf}"

    def test_wall_cf_close_to_reference(self, report):
        cf = report["boundary_layer"]["wall_cf"]
        ref_cf = 0.002706
        rel_err = abs(cf - ref_cf) / ref_cf
        assert rel_err < 0.10, (
            f"wall_cf should be within 10% of 0.002706, got {cf} (err={rel_err:.1%})"
        )

    def test_physically_consistent(self, report):
        bl = report["boundary_layer"]
        H = bl["shape_factor"]
        expected = 1.2 <= H <= 1.5
        assert bl["physically_consistent"] == expected, (
            f"physically_consistent should be {expected} for H={H}"
        )


# ─── Wall-law fit tests ───────────────────────────────────────────────────

class TestWallLawFit:
    def test_rms_deviation_range(self, report):
        rms = report["wall_law_fit"]["rms_deviation"]
        assert 0 < rms < 0.10, f"rms_deviation should be small but nonzero, got {rms}"

    def test_max_deviation_range(self, report):
        maxd = report["wall_law_fit"]["max_deviation"]
        assert 0 < maxd < 0.20, f"max_deviation should be moderate, got {maxd}"

    def test_rms_leq_max(self, report):
        wl = report["wall_law_fit"]
        assert wl["rms_deviation"] <= wl["max_deviation"] + 1e-9

    def test_sufficient_points(self, report):
        n = report["wall_law_fit"]["num_points"]
        assert n >= 20, f"Should have >=20 points in log layer, got {n}"

    def test_quality_consistent_with_rms(self, report):
        wl = report["wall_law_fit"]
        rms = wl["rms_deviation"]
        quality = wl["log_layer_quality"]
        if rms < 0.02:
            assert quality == "excellent"
        elif rms < 0.05:
            assert quality == "good"
        elif rms < 0.10:
            assert quality == "acceptable"
        else:
            assert quality == "poor"

    def test_quality_valid_value(self, report):
        q = report["wall_law_fit"]["log_layer_quality"]
        assert q in ("excellent", "good", "acceptable", "poor"), (
            f"log_layer_quality must be one of the four categories, got '{q}'"
        )


# ─── Convergence plot tests ───────────────────────────────────────────────

class TestConvergencePlots:
    def test_cf_plot_exists(self):
        assert os.path.exists("/app/plot_cf.svg"), "Missing /app/plot_cf.svg"

    def test_cd_plot_exists(self):
        assert os.path.exists("/app/plot_cd.svg"), "Missing /app/plot_cd.svg"

    def test_cf_plot_is_svg(self):
        with open("/app/plot_cf.svg") as f:
            content = f.read(500)
        assert "<svg" in content.lower() or "<?xml" in content.lower(), (
            "plot_cf.svg does not appear to be valid SVG"
        )

    def test_cd_plot_is_svg(self):
        with open("/app/plot_cd.svg") as f:
            content = f.read(500)
        assert "<svg" in content.lower() or "<?xml" in content.lower(), (
            "plot_cd.svg does not appear to be valid SVG"
        )

    def test_cf_plot_has_solver_labels(self):
        with open("/app/plot_cf.svg") as f:
            content = f.read()
        content_lower = content.lower()
        assert "cfl3d" in content_lower or "CFL3D" in content, (
            "plot_cf.svg should label CFL3D data"
        )
        assert "fun3d" in content_lower or "FUN3D" in content, (
            "plot_cf.svg should label FUN3D data"
        )

    def test_cd_plot_has_solver_labels(self):
        with open("/app/plot_cd.svg") as f:
            content = f.read()
        content_lower = content.lower()
        assert "cfl3d" in content_lower or "CFL3D" in content, (
            "plot_cd.svg should label CFL3D data"
        )
        assert "fun3d" in content_lower or "FUN3D" in content, (
            "plot_cd.svg should label FUN3D data"
        )

    def test_cf_plot_nontrival_size(self):
        size = os.path.getsize("/app/plot_cf.svg")
        assert size > 1000, f"plot_cf.svg too small ({size} bytes), likely empty"

    def test_cd_plot_nontrival_size(self):
        size = os.path.getsize("/app/plot_cd.svg")
        assert size > 1000, f"plot_cd.svg too small ({size} bytes), likely empty"
