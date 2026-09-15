
"""
Tests for DPW-8 grid convergence V&V assessment.
Verifies JSON outputs, SQLite database, convergence plots, and numerical correctness.
"""

import json
import math
import os
import sqlite3
import pytest


# ──────────────────────────────────────────────────────────────────
# Reference values computed independently from the raw data
# ──────────────────────────────────────────────────────────────────

GRID_SIZES = [2_000_000, 7_000_000, 24_500_000, 85_750_000]
R = 3.5 ** (1.0 / 3.0)  # refinement ratio ≈ 1.518294

RAW_GC = {
    "201.01": {"CL": [0.518, 0.5095, 0.5058, 0.5042],
               "CD": [0.0285, 0.0275, 0.0271, 0.02695],
               "CM": [-0.168, -0.172, -0.1738, -0.1746]},
    "202.01": {"CL": [0.525, 0.512, 0.5065, 0.5038],
               "CD": [0.029, 0.0278, 0.0272, 0.02698],
               "CM": [-0.165, -0.171, -0.1735, -0.1748]},
    "203.01": {"CL": [0.515, 0.5085, 0.5052, 0.5038],
               "CD": [0.0283, 0.0274, 0.02705, 0.02692],
               "CM": [-0.169, -0.1725, -0.174, -0.1747]},
    "204.01": {"CL": [0.53, 0.525, 0.522, 0.52],
               "CD": [0.032, 0.0315, 0.031, 0.0305],
               "CM": [-0.15, -0.152, -0.154, -0.156]},
    "205.01": {"CL": [0.51, 0.505, 0.508, 0.506],
               "CD": [0.028, 0.0273, 0.0276, 0.0274],
               "CM": [-0.17, -0.1735, -0.172, -0.173]},
    "206.01": {"CL": [0.517, 0.509, 0.505, 0.5032],
               "CD": [0.0284, 0.02745, 0.02708, 0.0269],
               "CM": [-0.1675, -0.1718, -0.1737, -0.1745]},
}

VALID_PARTICIPANTS = {"201.01", "202.01", "203.01", "206.01"}
ANOMALOUS_PARTICIPANTS = {"204.01", "205.01"}


def _richardson(vals):
    """Reference Richardson extrapolation from 3 finest grid values."""
    f2, f3, f4 = vals[1], vals[2], vals[3]
    e32 = f2 - f3
    e43 = f3 - f4
    if abs(e43) < 1e-15 or abs(e32) < 1e-15:
        return None
    if e32 * e43 <= 0:
        return None
    ratio = abs(e32 / e43)
    if abs(ratio - 1.0) < 1e-12:
        return None
    p = math.log(ratio) / math.log(R)
    if p < 0.5:
        return None
    rp = R ** p
    f_re = f4 + (f4 - f3) / (rp - 1)
    gci = 1.25 * abs(e43 / f4) / (rp - 1)
    return p, f_re, gci


REF_RESULTS = {}
for pid, data in RAW_GC.items():
    REF_RESULTS[pid] = {}
    for coeff in ["CL", "CD", "CM"]:
        REF_RESULTS[pid][coeff] = _richardson(data[coeff])


def _get(d, *keys):
    """Get value from dict trying keys in order."""
    for k in keys:
        if k in d:
            return d[k]
    return None


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def grid_convergence():
    path = "/app/results/grid_convergence.json"
    assert os.path.isfile(path), f"Missing output: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def anomalies():
    path = "/app/results/anomalies.json"
    assert os.path.isfile(path), f"Missing output: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def ensemble():
    path = "/app/results/ensemble.json"
    assert os.path.isfile(path), f"Missing output: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db():
    path = "/app/results/convergence.db"
    assert os.path.isfile(path), f"Missing output: {path}"
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


# ──────────────────────────────────────────────────────────────────
# Test: output files exist and have correct structure
# ──────────────────────────────────────────────────────────────────

class TestOutputStructure:
    def test_grid_convergence_has_participants(self, grid_convergence):
        assert "participants" in grid_convergence
        participants = grid_convergence["participants"]
        for pid in RAW_GC:
            assert pid in participants, f"Missing participant {pid}"

    def test_grid_convergence_has_coefficients(self, grid_convergence):
        for pid in VALID_PARTICIPANTS:
            p = grid_convergence["participants"][pid]
            for coeff in ["CL", "CD", "CM"]:
                assert coeff in p, f"Missing {coeff} for {pid}"
                entry = p[coeff]
                order = _get(entry, "convergence_order", "observed_order")
                assert order is not None, \
                    f"Missing convergence order for {pid}/{coeff}"
                asym = _get(entry, "asymptotic_value", "extrapolated")
                assert asym is not None, \
                    f"Missing asymptotic value for {pid}/{coeff}"

    def test_anomalies_has_flagged(self, anomalies):
        assert "flagged" in anomalies

    def test_ensemble_has_statistics(self, ensemble):
        assert _get(ensemble, "statistics", "stats") is not None
        assert "valid_participants" in ensemble


# ──────────────────────────────────────────────────────────────────
# Test: convergence analysis numerical results
# ──────────────────────────────────────────────────────────────────

class TestConvergenceAnalysis:
    """Verify convergence order and asymptotic values for valid participants."""

    @pytest.mark.parametrize("pid", sorted(VALID_PARTICIPANTS))
    def test_cl_convergence_order(self, grid_convergence, pid):
        ref = REF_RESULTS[pid]["CL"]
        assert ref is not None, f"Reference CL for {pid} should be computable"
        ref_order = ref[0]
        p = grid_convergence["participants"][pid]["CL"]
        order = _get(p, "convergence_order", "observed_order")
        assert order is not None, f"CL convergence order for {pid} should not be null"
        assert abs(order - ref_order) < 0.15, \
            f"CL order for {pid}: expected ~{ref_order:.3f}, got {order:.3f}"

    @pytest.mark.parametrize("pid", sorted(VALID_PARTICIPANTS))
    def test_cl_asymptotic_value(self, grid_convergence, pid):
        ref = REF_RESULTS[pid]["CL"]
        ref_val = ref[1]
        p = grid_convergence["participants"][pid]["CL"]
        computed = _get(p, "asymptotic_value", "extrapolated")
        assert computed is not None, f"CL asymptotic for {pid} should not be null"
        rel_err = abs(computed - ref_val) / abs(ref_val)
        assert rel_err < 0.005, \
            f"CL asymptotic for {pid}: expected ~{ref_val:.6f}, got {computed:.6f} (rel_err={rel_err:.4f})"

    @pytest.mark.parametrize("pid", sorted(VALID_PARTICIPANTS))
    def test_cd_asymptotic_value(self, grid_convergence, pid):
        ref = REF_RESULTS[pid]["CD"]
        assert ref is not None, f"Reference CD for {pid} should be computable"
        ref_val = ref[1]
        p = grid_convergence["participants"][pid]["CD"]
        computed = _get(p, "asymptotic_value", "extrapolated")
        assert computed is not None, f"CD asymptotic for {pid} should not be null"
        rel_err = abs(computed - ref_val) / abs(ref_val)
        assert rel_err < 0.01, \
            f"CD asymptotic for {pid}: expected ~{ref_val:.6f}, got {computed:.6f} (rel_err={rel_err:.4f})"

    @pytest.mark.parametrize("pid", sorted(VALID_PARTICIPANTS))
    def test_cm_asymptotic_value(self, grid_convergence, pid):
        ref = REF_RESULTS[pid]["CM"]
        assert ref is not None, f"Reference CM for {pid} should be computable"
        ref_val = ref[1]
        p = grid_convergence["participants"][pid]["CM"]
        computed = _get(p, "asymptotic_value", "extrapolated")
        assert computed is not None, f"CM asymptotic for {pid} should not be null"
        rel_err = abs(computed - ref_val) / abs(ref_val)
        assert rel_err < 0.01, \
            f"CM asymptotic for {pid}: expected ~{ref_val:.6f}, got {computed:.6f} (rel_err={rel_err:.4f})"

    @pytest.mark.parametrize("pid", sorted(VALID_PARTICIPANTS))
    def test_uncertainty_positive_and_reasonable(self, grid_convergence, pid):
        """Numerical uncertainty should be positive and below 5% for well-resolved solutions."""
        for coeff in ["CL", "CD", "CM"]:
            p = grid_convergence["participants"][pid][coeff]
            unc = _get(p, "numerical_uncertainty", "gci_fine", "gci")
            if unc is not None:
                assert unc > 0, f"Uncertainty for {pid}/{coeff} should be positive"
                assert unc < 0.05, f"Uncertainty for {pid}/{coeff} unexpectedly large: {unc}"


# ──────────────────────────────────────────────────────────────────
# Test: anomaly detection
# ──────────────────────────────────────────────────────────────────

class TestAnomalyDetection:
    def test_participant_205_flagged(self, anomalies):
        """205.01 has non-monotonic convergence and must be flagged."""
        flagged = anomalies["flagged"]
        assert "205.01" in flagged, \
            "Participant 205.01 (non-monotonic convergence) must be flagged"

    def test_participant_204_flagged(self, anomalies):
        """204.01 has degenerate convergence behavior and must be flagged."""
        flagged = anomalies["flagged"]
        assert "204.01" in flagged, \
            "Participant 204.01 (degenerate convergence) must be flagged"

    def test_valid_participants_not_flagged(self, anomalies):
        """Valid participants should not be flagged."""
        flagged = anomalies["flagged"]
        for pid in VALID_PARTICIPANTS:
            assert pid not in flagged, \
                f"Participant {pid} should NOT be flagged as anomalous"

    def test_flagged_has_reasons(self, anomalies):
        """Each flagged participant should have at least one reason."""
        for pid, info in anomalies["flagged"].items():
            reasons = _get(info, "reasons", "reason")
            assert reasons is not None, \
                f"Flagged participant {pid} must have reasons"
            if isinstance(reasons, str):
                reasons = [reasons]
            assert len(reasons) > 0, \
                f"Flagged participant {pid} must have at least one reason"


# ──────────────────────────────────────────────────────────────────
# Test: ensemble statistics
# ──────────────────────────────────────────────────────────────────

class TestEnsembleStatistics:
    def test_valid_participant_count(self, ensemble):
        vp = ensemble["valid_participants"]
        assert len(vp) == 4, f"Expected 4 valid participants, got {len(vp)}"

    def test_valid_participant_ids(self, ensemble):
        vp = set(ensemble["valid_participants"])
        assert vp == VALID_PARTICIPANTS, \
            f"Valid participants should be {VALID_PARTICIPANTS}, got {vp}"

    def test_cl_ensemble_mean(self, ensemble):
        stats = _get(ensemble, "statistics", "stats")
        cl_stats = stats["CL"]
        mean_val = _get(cl_stats, "mean", "mean_extrapolated", "mean_asymptotic")
        ref_mean = sum(REF_RESULTS[p]["CL"][1] for p in VALID_PARTICIPANTS) / 4
        rel_err = abs(mean_val - ref_mean) / abs(ref_mean)
        assert rel_err < 0.005, \
            f"CL ensemble mean: expected ~{ref_mean:.6f}, got {mean_val:.6f}"

    def test_cd_ensemble_mean(self, ensemble):
        stats = _get(ensemble, "statistics", "stats")
        cd_stats = stats["CD"]
        mean_val = _get(cd_stats, "mean", "mean_extrapolated", "mean_asymptotic")
        ref_mean = sum(REF_RESULTS[p]["CD"][1] for p in VALID_PARTICIPANTS) / 4
        rel_err = abs(mean_val - ref_mean) / abs(ref_mean)
        assert rel_err < 0.01, \
            f"CD ensemble mean: expected ~{ref_mean:.6f}, got {mean_val:.6f}"

    def test_cm_ensemble_mean(self, ensemble):
        stats = _get(ensemble, "statistics", "stats")
        cm_stats = stats["CM"]
        mean_val = _get(cm_stats, "mean", "mean_extrapolated", "mean_asymptotic")
        ref_mean = sum(REF_RESULTS[p]["CM"][1] for p in VALID_PARTICIPANTS) / 4
        rel_err = abs(mean_val - ref_mean) / abs(ref_mean)
        assert rel_err < 0.01, \
            f"CM ensemble mean: expected ~{ref_mean:.6f}, got {mean_val:.6f}"

    def test_ensemble_std_positive(self, ensemble):
        stats = _get(ensemble, "statistics", "stats")
        for coeff in ["CL", "CD", "CM"]:
            c_stats = stats[coeff]
            std_val = _get(c_stats, "std", "std_extrapolated", "std_asymptotic")
            assert std_val > 0, f"{coeff} ensemble std should be positive"

    def test_experimental_reference(self, ensemble):
        exp = _get(ensemble, "experimental_reference", "experimental")
        assert exp is not None, "Ensemble should include experimental reference"
        assert abs(exp["CL"] - 0.5) < 0.01, f"Exp CL should be ~0.5, got {exp['CL']}"
        assert abs(exp["CD"] - 0.0268) < 0.001, f"Exp CD should be ~0.0268, got {exp['CD']}"
        assert abs(exp["CM"] - (-0.175)) < 0.01, f"Exp CM should be ~-0.175, got {exp['CM']}"


# ──────────────────────────────────────────────────────────────────
# Test: CRMWBNP trap zones excluded
# ──────────────────────────────────────────────────────────────────

class TestConfigurationFiltering:
    def test_crmwbnp_not_in_results(self, grid_convergence):
        """CL values must come from CRMWB, not CRMWBNP.
        CRMWBNP has notably higher CL (>0.51 at finest grid)."""
        for pid in ["201.01", "202.01"]:
            p = grid_convergence["participants"][pid]["CL"]
            ext = _get(p, "asymptotic_value", "extrapolated")
            if ext is not None:
                assert ext < 0.510, \
                    f"CL asymptotic for {pid} is {ext:.4f}, suspiciously high — " \
                    f"check that CRMWBNP zones were filtered out"


# ──────────────────────────────────────────────────────────────────
# Test: refinement ratio
# ──────────────────────────────────────────────────────────────────

class TestRefinementRatio:
    def test_refinement_ratio_value(self, grid_convergence):
        """If refinement_ratio is reported, it should be ~1.518."""
        rr = grid_convergence.get("refinement_ratio")
        if rr is not None:
            assert abs(rr - R) < 0.05, \
                f"Refinement ratio should be ~{R:.4f}, got {rr:.4f}"


# ──────────────────────────────────────────────────────────────────
# Test: SQLite database
# ──────────────────────────────────────────────────────────────────

class TestSQLiteDatabase:
    def test_raw_data_table_exists(self, db):
        c = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_data'"
        )
        assert c.fetchone() is not None, "Table 'raw_data' missing from convergence.db"

    def test_raw_data_has_all_participants(self, db):
        c = db.execute("SELECT DISTINCT participant_id FROM raw_data")
        pids = set(row[0] for row in c.fetchall())
        assert len(pids) == 6, f"Expected 6 participants in raw_data, got {len(pids)}"

    def test_raw_data_row_count(self, db):
        """6 participants x 4 grid levels = 24 rows."""
        c = db.execute("SELECT COUNT(*) FROM raw_data")
        count = c.fetchone()[0]
        assert count == 24, f"Expected 24 rows in raw_data, got {count}"

    def test_raw_data_cl_range(self, db):
        """CL values should be in a reasonable range for transonic transport."""
        c = db.execute("SELECT MIN(cl), MAX(cl) FROM raw_data")
        lo, hi = c.fetchone()
        assert 0.4 < lo < 0.55, f"Min CL out of range: {lo}"
        assert 0.4 < hi < 0.55, f"Max CL out of range: {hi}"

    def test_convergence_assessment_table_exists(self, db):
        c = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='convergence_assessment'"
        )
        assert c.fetchone() is not None, \
            "Table 'convergence_assessment' missing from convergence.db"

    def test_convergence_assessment_row_count(self, db):
        """6 participants x 3 coefficients = 18 rows."""
        c = db.execute("SELECT COUNT(*) FROM convergence_assessment")
        count = c.fetchone()[0]
        assert count == 18, \
            f"Expected 18 rows in convergence_assessment, got {count}"

    def test_anomalous_participants_have_invalid_rows(self, db):
        c = db.execute(
            "SELECT DISTINCT participant_id FROM convergence_assessment "
            "WHERE is_valid = 0"
        )
        has_invalid = set(row[0] for row in c.fetchall())
        for pid in ANOMALOUS_PARTICIPANTS:
            assert pid in has_invalid, \
                f"Participant {pid} should have at least one is_valid=0 row"

    def test_valid_participants_all_valid(self, db):
        for pid in VALID_PARTICIPANTS:
            c = db.execute(
                "SELECT COUNT(*) FROM convergence_assessment "
                "WHERE participant_id = ? AND is_valid = 0",
                (pid,)
            )
            count = c.fetchone()[0]
            assert count == 0, \
                f"Valid participant {pid} should have no is_valid=0 rows"


# ──────────────────────────────────────────────────────────────────
# Test: convergence plots
# ──────────────────────────────────────────────────────────────────

class TestConvergencePlots:
    @pytest.mark.parametrize("coeff", ["cl", "cd", "cm"])
    def test_plot_file_exists(self, coeff):
        path = f"/app/results/plots/{coeff}_convergence.png"
        assert os.path.isfile(path), f"Missing convergence plot: {path}"

    @pytest.mark.parametrize("coeff", ["cl", "cd", "cm"])
    def test_plot_is_valid_png(self, coeff):
        path = f"/app/results/plots/{coeff}_convergence.png"
        with open(path, "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            f"File {path} is not a valid PNG image"

    @pytest.mark.parametrize("coeff", ["cl", "cd", "cm"])
    def test_plot_nontrivial_size(self, coeff):
        path = f"/app/results/plots/{coeff}_convergence.png"
        size = os.path.getsize(path)
        assert size > 500, \
            f"Plot {path} is only {size} bytes, likely empty or corrupt"
