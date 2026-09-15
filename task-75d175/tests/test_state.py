
import os
import json
import re
import math
import pytest


CASE_DIR = "/app/cavity"
REPORT_PATH = "/app/convergence_report.json"
SAFETY_FACTOR = 1.25

# Ghia et al. (1982) Re=100 benchmark: u along vertical centerline at x=0.5
GHIA_REFERENCE = {
    0.9766: 0.84123,
    0.5000: -0.20581,
    0.2813: -0.15662,
    0.1016: -0.06434,
    0.0547: -0.03717,
}


def get_latest_time_dir():
    """Find the latest numerical time directory in the case."""
    time_dirs = []
    for d in os.listdir(CASE_DIR):
        full = os.path.join(CASE_DIR, d)
        if not os.path.isdir(full):
            continue
        try:
            t = float(d)
            if t > 0:
                time_dirs.append((t, d))
        except ValueError:
            pass
    if not time_dirs:
        return None
    return max(time_dirs, key=lambda x: x[0])[1]


# ── Part 1: Base case validation ─────────────────────────────────────────


class TestBlockMesh:
    """Verify blockMesh produced a valid mesh."""

    def test_polymesh_exists(self):
        points = os.path.join(CASE_DIR, "constant", "polyMesh", "points")
        assert os.path.isfile(points), (
            "constant/polyMesh/points does not exist — blockMesh did not complete"
        )

    def test_blockmesh_log_no_fatal(self):
        logfile = os.path.join(CASE_DIR, "log.blockMesh")
        assert os.path.isfile(logfile), "log.blockMesh not found"
        with open(logfile) as f:
            content = f.read()
        assert "FOAM FATAL" not in content, (
            "blockMesh log contains FOAM FATAL ERROR"
        )


class TestSimpleFoam:
    """Verify simpleFoam ran and converged."""

    def test_simplefoam_completed(self):
        logfile = os.path.join(CASE_DIR, "log.simpleFoam")
        assert os.path.isfile(logfile), "log.simpleFoam does not exist"
        with open(logfile) as f:
            content = f.read()
        assert "FOAM FATAL" not in content, (
            "simpleFoam log contains FOAM FATAL ERROR"
        )
        assert "End" in content, (
            "simpleFoam did not complete — 'End' marker not found"
        )

    def test_continuity_residual_converged(self):
        logfile = os.path.join(CASE_DIR, "log.simpleFoam")
        assert os.path.isfile(logfile)
        with open(logfile) as f:
            lines = f.readlines()

        last_cont = None
        for line in lines:
            m = re.search(
                r'time step continuity errors\s*:\s*'
                r'sum local = ([0-9.eE+-]+)',
                line,
            )
            if m:
                last_cont = float(m.group(1))

        assert last_cont is not None, "No continuity error lines found"
        assert last_cont < 1e-3, (
            f"Final continuity error {last_cont} exceeds 1e-3"
        )

    def test_velocity_field_exists(self):
        latest = get_latest_time_dir()
        assert latest is not None, "No time directories found"
        u_path = os.path.join(CASE_DIR, latest, "U")
        assert os.path.isfile(u_path), f"U field not found at {u_path}"


# ── Part 2: Convergence study validation ─────────────────────────────────


class TestAnalyzeScript:
    """Verify the analysis script exists."""

    def test_analyze_script_exists(self):
        assert os.path.isfile("/app/analyze.py"), (
            "analyze.py not found at /app/analyze.py"
        )

    def test_analyze_script_nontrivial(self):
        """Script must contain substantive implementation."""
        with open("/app/analyze.py") as f:
            content = f.read()
        # Must contain Richardson extrapolation logic
        assert "richardson" in content.lower() or "extrapolat" in content.lower(), (
            "analyze.py does not appear to implement Richardson extrapolation"
        )
        # Must reference OpenFOAM
        assert "blockMesh" in content or "simpleFoam" in content or "openfoam" in content.lower(), (
            "analyze.py does not appear to interact with OpenFOAM"
        )


class TestConvergenceReport:
    """Verify the convergence report is correct and internally consistent."""

    @pytest.fixture
    def report(self):
        assert os.path.isfile(REPORT_PATH), f"{REPORT_PATH} not found"
        with open(REPORT_PATH) as f:
            return json.load(f)

    def test_report_top_level_keys(self, report):
        for key in ("mesh_levels", "refinement_ratio", "sample_points", "asymptotic_range"):
            assert key in report, f"Missing top-level key: {key}"
        assert isinstance(report["asymptotic_range"], bool)

    def test_mesh_levels_valid(self, report):
        levels = report["mesh_levels"]
        assert isinstance(levels, list) and len(levels) == 3, (
            f"Expected 3 mesh levels, got {levels}"
        )
        assert levels[0] < levels[1] < levels[2], "Mesh levels not increasing"
        r1 = levels[1] / levels[0]
        r2 = levels[2] / levels[1]
        assert abs(r1 - r2) < 0.01, (
            f"Inconsistent refinement ratios: {r1:.3f} vs {r2:.3f}"
        )

    def test_sample_points_complete(self, report):
        points = report["sample_points"]
        assert len(points) >= 5, f"Expected >=5 sample points, got {len(points)}"
        required = [
            "y_normalized", "u_coarse", "u_medium", "u_fine",
            "u_extrapolated", "u_ghia", "observed_order", "gci_fine",
        ]
        for pt in points:
            for field in required:
                assert field in pt, (
                    f"Missing '{field}' at y={pt.get('y_normalized', '?')}"
                )

    def test_ghia_reference_values_correct(self, report):
        """The stored Ghia values must match the published benchmark."""
        for pt in report["sample_points"]:
            y = pt["y_normalized"]
            closest_y = min(GHIA_REFERENCE.keys(), key=lambda gy: abs(gy - y))
            if abs(closest_y - y) < 0.005:
                expected = GHIA_REFERENCE[closest_y]
                assert abs(pt["u_ghia"] - expected) < 0.001, (
                    f"Wrong Ghia ref at y={y}: got {pt['u_ghia']}, "
                    f"expected {expected}"
                )

    def test_richardson_formula_consistent(self, report):
        """Verify u_extrapolated = u_fine + (u_fine - u_medium) / (r^p - 1)."""
        r = report["refinement_ratio"]
        n_checked = 0
        for pt in report["sample_points"]:
            p = pt["observed_order"]
            u_ext = pt["u_extrapolated"]
            u_fine = pt["u_fine"]
            u_med = pt["u_medium"]

            if p is None or u_ext is None:
                continue

            eps_32 = u_fine - u_med
            if abs(eps_32) < 1e-12:
                continue

            u_ext_computed = u_fine + eps_32 / (r ** p - 1)
            n_checked += 1

            assert abs(u_ext - u_ext_computed) < 1e-4, (
                f"Richardson mismatch at y={pt['y_normalized']}: "
                f"reported {u_ext:.6f}, formula gives {u_ext_computed:.6f}"
            )
        assert n_checked >= 3, (
            f"Could only verify Richardson at {n_checked} points (need >=3)"
        )

    def test_gci_formula_consistent(self, report):
        """Verify gci_fine = Fs * |eps/u_fine| / (r^p - 1)."""
        r = report["refinement_ratio"]
        n_checked = 0
        for pt in report["sample_points"]:
            p = pt["observed_order"]
            gci = pt["gci_fine"]
            u_fine = pt["u_fine"]
            u_med = pt["u_medium"]

            if p is None or gci is None:
                continue
            if abs(u_fine) < 1e-10:
                continue

            eps_rel = abs((u_fine - u_med) / u_fine)
            gci_computed = SAFETY_FACTOR * eps_rel / (r ** p - 1)
            n_checked += 1

            tol = max(1e-6, 0.05 * max(abs(gci), abs(gci_computed)))
            assert abs(gci - gci_computed) < tol, (
                f"GCI mismatch at y={pt['y_normalized']}: "
                f"reported {gci:.6f}, formula gives {gci_computed:.6f}"
            )
        assert n_checked >= 3, (
            f"Could only verify GCI at {n_checked} points (need >=3)"
        )

    def test_extrapolated_values_near_ghia(self, report):
        """Richardson-extrapolated values should approach Ghia benchmark."""
        n_close = 0
        n_total = 0
        for pt in report["sample_points"]:
            u_ext = pt["u_extrapolated"]
            u_ghia = pt["u_ghia"]

            if u_ext is None:
                continue
            n_total += 1

            tol = max(0.03, 0.20 * abs(u_ghia))
            if abs(u_ext - u_ghia) < tol:
                n_close += 1

        assert n_total >= 5, f"Only {n_total} extrapolated values present"
        assert n_close >= 3, (
            f"Only {n_close}/{n_total} extrapolated values are within "
            f"20% of the Ghia benchmark"
        )

    def test_observed_order_reasonable(self, report):
        """Observed convergence order should be in a physically plausible range."""
        for pt in report["sample_points"]:
            p = pt["observed_order"]
            if p is not None:
                assert 0.5 <= p <= 4.0, (
                    f"Observed order {p} at y={pt['y_normalized']} "
                    f"outside [0.5, 4.0]"
                )

    def test_gci_non_negative(self, report):
        """GCI values must be non-negative."""
        for pt in report["sample_points"]:
            gci = pt["gci_fine"]
            if gci is not None:
                assert gci >= 0, (
                    f"Negative GCI at y={pt['y_normalized']}: {gci}"
                )

    def test_monotone_convergence_majority(self, report):
        """At least some sample points should exhibit monotone convergence."""
        n_monotone = 0
        n_total = 0
        for pt in report["sample_points"]:
            u_c = pt["u_coarse"]
            u_m = pt["u_medium"]
            u_f = pt["u_fine"]

            eps_21 = u_m - u_c
            eps_32 = u_f - u_m

            if abs(eps_32) < 1e-12 or abs(eps_21) < 1e-12:
                n_monotone += 1
                n_total += 1
                continue

            n_total += 1
            if eps_21 / eps_32 > 0:
                n_monotone += 1

        assert n_monotone >= 2, (
            f"Only {n_monotone}/{n_total} points show monotone convergence"
        )

    def test_mesh_values_physically_plausible(self, report):
        """Velocity values at all mesh levels should be within physical bounds."""
        for pt in report["sample_points"]:
            for key in ("u_coarse", "u_medium", "u_fine"):
                v = pt[key]
                assert -1.5 < v < 1.5, (
                    f"{key}={v} at y={pt['y_normalized']} exceeds physical bounds"
                )
