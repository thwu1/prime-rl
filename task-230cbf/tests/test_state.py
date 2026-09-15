"""
Test suite for CFD solver benchmark evaluation pipeline.

"""

import json
import math
import os
import struct
import pytest


EVAL_PATH = "/app/evaluation.json"
PLOTS_DIR = "/app/plots"

SOLVER_NAMES = ["FUN3D_SA", "OVERFLOW_SST", "SU2_SA", "TAU_RSM", "CFL3D_SA"]

# Reference convergence orders (from Richardson extrapolation on the
# three finest grids with uniform refinement ratio r=2)
REF_CONV_ORDER = {
    "FUN3D_SA": 2.0,
    "OVERFLOW_SST": 2.0,
    "SU2_SA": 1.0,
    "TAU_RSM": 2.0,
    "CFL3D_SA": 2.0,
}

# Reference grid-independent extrapolated values
REF_EXTRAP_CL = {
    "FUN3D_SA": 0.6850,
    "OVERFLOW_SST": 0.6920,
    "SU2_SA": 0.7000,
    "TAU_RSM": 0.6880,
    "CFL3D_SA": 0.6850,
}

REF_EXTRAP_CD = {
    "FUN3D_SA": 0.01550,
    "OVERFLOW_SST": 0.01620,
    "SU2_SA": 0.01700,
    "TAU_RSM": 0.01580,
    "CFL3D_SA": 0.01550,
}

# Expected ranking (best to worst) and key positions
EXPECTED_BEST = "CFL3D_SA"
EXPECTED_WORST = "SU2_SA"
EXPECTED_SECOND = "FUN3D_SA"
# TAU_RSM and OVERFLOW_SST order may vary by metric choice

# TAU_RSM should have anomaly detected (grid level 1 is inconsistent)
ANOMALY_SOLVER = "TAU_RSM"


@pytest.fixture(scope="module")
def evaluation():
    assert os.path.isfile(EVAL_PATH), f"Evaluation file not found at {EVAL_PATH}"
    with open(EVAL_PATH) as f:
        data = json.load(f)
    return data


# ------------------------------------------------------------------ #
#  Structure tests                                                    #
# ------------------------------------------------------------------ #

class TestStructure:
    def test_file_exists(self, evaluation):
        assert evaluation is not None

    def test_top_level_keys(self, evaluation):
        for key in ["solvers", "ranking", "best_solver", "worst_solver"]:
            assert key in evaluation, f"Missing top-level key: {key}"

    def test_all_solvers_present(self, evaluation):
        solvers = evaluation["solvers"]
        for name in SOLVER_NAMES:
            assert name in solvers, f"Missing solver: {name}"

    def test_solver_fields(self, evaluation):
        required = [
            "convergence_order", "converged_cl", "converged_cd",
            "cl_rms_error", "cd_rms_error", "anomaly"
        ]
        for name in SOLVER_NAMES:
            solver = evaluation["solvers"][name]
            for field in required:
                assert field in solver, (
                    f"Missing field '{field}' for solver {name}"
                )

    def test_ranking_length(self, evaluation):
        assert len(evaluation["ranking"]) == 5, "Ranking must have 5 entries"

    def test_ranking_contains_all_solvers(self, evaluation):
        ranked = set(evaluation["ranking"])
        expected = set(SOLVER_NAMES)
        assert ranked == expected, (
            f"Ranking solvers {ranked} != expected {expected}"
        )


# ------------------------------------------------------------------ #
#  Grid convergence order tests                                       #
# ------------------------------------------------------------------ #

class TestConvergenceOrder:
    @pytest.mark.parametrize("solver", ["FUN3D_SA", "OVERFLOW_SST", "CFL3D_SA"])
    def test_second_order_solvers(self, evaluation, solver):
        p = float(evaluation["solvers"][solver]["convergence_order"])
        ref = REF_CONV_ORDER[solver]
        assert abs(p - ref) < 0.3, (
            f"{solver} convergence order: got {p}, expected {ref} +/- 0.3"
        )

    def test_su2_first_order(self, evaluation):
        p = float(evaluation["solvers"]["SU2_SA"]["convergence_order"])
        ref = REF_CONV_ORDER["SU2_SA"]
        assert abs(p - ref) < 0.3, (
            f"SU2_SA convergence order: got {p}, expected {ref} +/- 0.3"
        )

    def test_tau_convergence_order(self, evaluation):
        """TAU_RSM should show ~2.0 if the outlier at L1 is properly handled."""
        p = float(evaluation["solvers"]["TAU_RSM"]["convergence_order"])
        ref = REF_CONV_ORDER["TAU_RSM"]
        assert abs(p - ref) < 0.5, (
            f"TAU_RSM convergence order: got {p}, expected {ref} +/- 0.5 "
            f"(agent should detect L1 outlier and use finer grids)"
        )

    def test_su2_lower_than_others(self, evaluation):
        """SU2_SA convergence order should be distinctly lower than second-order solvers."""
        p_su2 = float(evaluation["solvers"]["SU2_SA"]["convergence_order"])
        for solver in ["FUN3D_SA", "OVERFLOW_SST", "CFL3D_SA"]:
            p_other = float(evaluation["solvers"][solver]["convergence_order"])
            assert p_su2 < p_other - 0.3, (
                f"SU2_SA order ({p_su2}) should be distinctly below "
                f"{solver} order ({p_other})"
            )


# ------------------------------------------------------------------ #
#  Extrapolated value tests                                           #
# ------------------------------------------------------------------ #

class TestExtrapolatedValues:
    @pytest.mark.parametrize("solver,ref", list(REF_EXTRAP_CL.items()))
    def test_converged_cl(self, evaluation, solver, ref):
        val = float(evaluation["solvers"][solver]["converged_cl"])
        assert abs(val - ref) < 0.005, (
            f"{solver} converged CL: got {val}, expected {ref} +/- 0.005"
        )

    @pytest.mark.parametrize("solver,ref", list(REF_EXTRAP_CD.items()))
    def test_converged_cd(self, evaluation, solver, ref):
        val = float(evaluation["solvers"][solver]["converged_cd"])
        assert abs(val - ref) < 0.002, (
            f"{solver} converged CD: got {val}, expected {ref} +/- 0.002"
        )

    def test_cl_ordering(self, evaluation):
        """Extrapolated CL values should follow: SU2 > OVERFLOW > TAU ~ FUN3D ~ CFL3D."""
        cl_su2 = float(evaluation["solvers"]["SU2_SA"]["converged_cl"])
        cl_ovf = float(evaluation["solvers"]["OVERFLOW_SST"]["converged_cl"])
        cl_fun = float(evaluation["solvers"]["FUN3D_SA"]["converged_cl"])
        assert cl_su2 > cl_ovf > cl_fun - 0.005


# ------------------------------------------------------------------ #
#  Ranking tests                                                      #
# ------------------------------------------------------------------ #

class TestRanking:
    def test_best_solver(self, evaluation):
        assert evaluation["best_solver"] == EXPECTED_BEST, (
            f"Best solver: got {evaluation['best_solver']}, "
            f"expected {EXPECTED_BEST}"
        )

    def test_worst_solver(self, evaluation):
        assert evaluation["worst_solver"] == EXPECTED_WORST, (
            f"Worst solver: got {evaluation['worst_solver']}, "
            f"expected {EXPECTED_WORST}"
        )

    def test_ranking_first(self, evaluation):
        assert evaluation["ranking"][0] == EXPECTED_BEST, (
            f"Ranking[0]: got {evaluation['ranking'][0]}, "
            f"expected {EXPECTED_BEST}"
        )

    def test_ranking_second(self, evaluation):
        assert evaluation["ranking"][1] == EXPECTED_SECOND, (
            f"Ranking[1]: got {evaluation['ranking'][1]}, "
            f"expected {EXPECTED_SECOND}"
        )

    def test_ranking_last(self, evaluation):
        assert evaluation["ranking"][-1] == EXPECTED_WORST, (
            f"Ranking[-1]: got {evaluation['ranking'][-1]}, "
            f"expected {EXPECTED_WORST}"
        )

    def test_best_matches_ranking(self, evaluation):
        assert evaluation["best_solver"] == evaluation["ranking"][0]

    def test_worst_matches_ranking(self, evaluation):
        assert evaluation["worst_solver"] == evaluation["ranking"][-1]


# ------------------------------------------------------------------ #
#  Anomaly detection tests                                            #
# ------------------------------------------------------------------ #

class TestAnomalyDetection:
    def test_tau_anomaly_detected(self, evaluation):
        anomaly = evaluation["solvers"][ANOMALY_SOLVER]["anomaly"]
        assert anomaly is True or anomaly == "true" or str(anomaly).lower() == "true", (
            f"TAU_RSM anomaly should be detected (got {anomaly})"
        )

    @pytest.mark.parametrize("solver", ["FUN3D_SA", "OVERFLOW_SST", "CFL3D_SA"])
    def test_clean_solvers_no_anomaly(self, evaluation, solver):
        anomaly = evaluation["solvers"][solver]["anomaly"]
        assert anomaly is False or anomaly == "false" or str(anomaly).lower() == "false", (
            f"{solver} should have no anomaly (got {anomaly})"
        )


# ------------------------------------------------------------------ #
#  Accuracy metric tests                                              #
# ------------------------------------------------------------------ #

class TestAccuracyMetrics:
    def test_rms_errors_are_positive(self, evaluation):
        for name in SOLVER_NAMES:
            s = evaluation["solvers"][name]
            assert float(s["cl_rms_error"]) >= 0, (
                f"{name} cl_rms_error should be >= 0"
            )
            assert float(s["cd_rms_error"]) >= 0, (
                f"{name} cd_rms_error should be >= 0"
            )

    def test_cfl3d_lowest_error(self, evaluation):
        """CFL3D_SA should have the lowest total error."""
        best_cl = float(evaluation["solvers"]["CFL3D_SA"]["cl_rms_error"])
        best_cd = float(evaluation["solvers"]["CFL3D_SA"]["cd_rms_error"])
        best_total = best_cl + best_cd
        for name in ["FUN3D_SA", "OVERFLOW_SST", "SU2_SA", "TAU_RSM"]:
            s = evaluation["solvers"][name]
            total = float(s["cl_rms_error"]) + float(s["cd_rms_error"])
            assert best_total <= total + 1e-6, (
                f"CFL3D_SA total error ({best_total}) should be <= "
                f"{name} total error ({total})"
            )

    def test_su2_highest_error(self, evaluation):
        """SU2_SA should have the highest total error."""
        worst_cl = float(evaluation["solvers"]["SU2_SA"]["cl_rms_error"])
        worst_cd = float(evaluation["solvers"]["SU2_SA"]["cd_rms_error"])
        worst_total = worst_cl + worst_cd
        for name in ["FUN3D_SA", "OVERFLOW_SST", "TAU_RSM", "CFL3D_SA"]:
            s = evaluation["solvers"][name]
            total = float(s["cl_rms_error"]) + float(s["cd_rms_error"])
            assert worst_total >= total - 1e-6, (
                f"SU2_SA total error ({worst_total}) should be >= "
                f"{name} total error ({total})"
            )


# ------------------------------------------------------------------ #
#  Plot and gnuplot script tests                                      #
# ------------------------------------------------------------------ #

class TestPlots:
    def test_plots_directory_exists(self):
        assert os.path.isdir(PLOTS_DIR), f"{PLOTS_DIR} directory not found"

    def test_png_files_exist(self):
        png_files = [f for f in os.listdir(PLOTS_DIR) if f.endswith(".png")]
        assert len(png_files) >= 2, (
            f"Expected at least 2 PNG files in {PLOTS_DIR}, "
            f"found {len(png_files)}: {png_files}"
        )

    def test_gnuplot_scripts_exist(self):
        gp_files = []
        for root, dirs, files in os.walk("/app"):
            for f in files:
                if f.endswith(".gp") or f.endswith(".gnu") or f.endswith(".gnuplot"):
                    gp_files.append(os.path.join(root, f))
        assert len(gp_files) >= 1, (
            f"Expected at least 1 gnuplot script file (.gp/.gnu/.gnuplot), "
            f"found none"
        )

    def test_png_files_valid(self):
        """Check PNG files have valid PNG magic bytes."""
        png_files = [
            os.path.join(PLOTS_DIR, f)
            for f in os.listdir(PLOTS_DIR)
            if f.endswith(".png")
        ]
        png_magic = b'\x89PNG\r\n\x1a\n'
        for png_path in png_files:
            with open(png_path, 'rb') as f:
                header = f.read(8)
            assert header == png_magic, (
                f"{png_path} does not have valid PNG header"
            )
