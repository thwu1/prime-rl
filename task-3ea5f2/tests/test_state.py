"""Tests for SPARTA ATS-5 benchmark forensics task.

Independently parses SPARTA log files, computes reference FOM values,
fits scaling models, and verifies the agent's /app/report.json, SQLite
database, and gnuplot output against expected results.
"""


import json
import math
import os
import sqlite3 as sqlite3_mod

import pytest

RANKS_PER_NODE = 112
LOG_DIR = "/app/data/logs"
RESULTS_FILE = "/app/report.json"
DB_PATH = "/app/benchmark.db"
PLOT_PATH = "/app/scaling_plot.png"

SCALING_RUNS = ["scaling_1", "scaling_4", "scaling_16", "scaling_64"]
NODE_COUNTS = {"scaling_1": 1, "scaling_4": 4, "scaling_16": 16, "scaling_64": 64}
ALL_RUNS = SCALING_RUNS + ["validation"]


# ---------------------------------------------------------------------------
# Reference implementation — SPARTA log parsing with restart handling
# ---------------------------------------------------------------------------

def parse_sparta_log(filepath):
    """Parse a SPARTA log file, handling multiple stats blocks (restarts).

    Returns info dict and rows from the LAST valid block.
    """
    info = {}
    all_blocks = []
    current_block = []
    in_block = False

    with open(filepath) as f:
        for raw_line in f:
            line = raw_line.strip()

            if "Running on" in line and "MPI task(s)" in line:
                parts = line.split()
                info["num_ranks"] = int(parts[2])

            if ("Step" in line and "CPU" in line and "Np" in line
                    and "Natt" in line and "Ncoll" in line
                    and "Maxlevel" in line):
                in_block = True
                current_block = []
                continue

            if "Loop time of" in line and "steps with" in line:
                in_block = False
                parts = line.split()
                block_info = {
                    "wall_time": float(parts[3]),
                    "total_steps": int(parts[8]),
                    "rows": current_block[:],
                }
                all_blocks.append(block_info)
                current_block = []
                continue

            if in_block:
                parts = line.split()
                if len(parts) == 6:
                    try:
                        current_block.append({
                            "step": int(parts[0]),
                            "cpu": float(parts[1]),
                            "np": int(parts[2]),
                            "natt": int(parts[3]),
                            "ncoll": int(parts[4]),
                            "maxlevel": int(parts[5]),
                        })
                    except (ValueError, IndexError):
                        pass

    info["num_nodes"] = round(info["num_ranks"] / RANKS_PER_NODE)
    info["num_blocks"] = len(all_blocks)

    # Use the LAST block with wall_time >= 600
    valid_blocks = [b for b in all_blocks if b["wall_time"] >= 600.0]
    if valid_blocks:
        best = valid_blocks[-1]
        info["wall_time"] = best["wall_time"]
        return info, best["rows"]

    # Fallback to last block regardless
    if all_blocks:
        info["wall_time"] = all_blocks[-1]["wall_time"]
        return info, all_blocks[-1]["rows"]

    return info, []


def compute_fom(info, rows):
    """Compute ATS-5 SPARTA FOM (Mega particle-steps/sec/node).

    Uses strict inequality: 300 < cpu < 600.
    """
    reciprocals = []
    for row in rows:
        if row["cpu"] >= 600.0:
            break
        if row["cpu"] > 300.0:
            qoi = row["step"] * row["np"] / row["cpu"] / 1e6
            if qoi > 0:
                reciprocals.append(1.0 / qoi)

    if not reciprocals:
        return None

    hmean = len(reciprocals) / sum(reciprocals)
    return hmean / info["num_nodes"]


def fit_power_law(nodes, foms):
    """Fit power-law model: FOM(p) = a * p^(-b) via log-log regression."""
    x = [math.log(n) for n in nodes]
    y = [math.log(f) for f in foms]
    n = len(x)

    x_mean = sum(x) / n
    y_mean = sum(y) / n

    sxx = sum((xi - x_mean) ** 2 for xi in x)
    sxy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))

    beta = sxy / sxx
    alpha = y_mean - beta * x_mean

    coefficient = math.exp(alpha)
    exponent = -beta

    return coefficient, exponent


def fit_amdahl(nodes, foms):
    """Fit Amdahl's weak-scaling model: FOM(p) = FOM1 / (1 + f*(p-1)).

    Uses linear regression on (1/FOM) vs (p-1).
    """
    x = [n - 1 for n in nodes]
    y = [1.0 / f for f in foms]
    n = len(x)

    x_mean = sum(x) / n
    y_mean = sum(y) / n

    sxx = sum((xi - x_mean) ** 2 for xi in x)
    sxy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))

    beta = sxy / sxx
    alpha = y_mean - beta * x_mean

    fom1 = 1.0 / alpha
    serial_fraction = beta * fom1

    return fom1, serial_fraction


def predict_power_law(p, coefficient, exponent):
    """Predict FOM at node count p using power-law model."""
    return coefficient * p ** (-exponent)


def predict_amdahl(p, fom1, serial_fraction):
    """Predict FOM at node count p using Amdahl model."""
    return fom1 / (1.0 + serial_fraction * (p - 1))


def r_squared_fom_space(nodes, actual_foms, predict_fn, *params):
    """Compute R-squared in original FOM space."""
    predicted = [predict_fn(n, *params) for n in nodes]
    mean_fom = sum(actual_foms) / len(actual_foms)

    ss_res = sum((a - p) ** 2 for a, p in zip(actual_foms, predicted))
    ss_tot = sum((a - mean_fom) ** 2 for a in actual_foms)

    if ss_tot == 0:
        return 1.0
    return 1.0 - ss_res / ss_tot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def agent_results():
    """Load the agent's report.json."""
    assert os.path.exists(RESULTS_FILE), (
        "Results file not found at {}".format(RESULTS_FILE)
    )
    with open(RESULTS_FILE) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected_foms():
    """Independently compute expected FOM for all runs."""
    foms = {}
    for name in ALL_RUNS:
        path = os.path.join(LOG_DIR, "{}.log".format(name))
        info, rows = parse_sparta_log(path)
        fom = compute_fom(info, rows)
        foms[name] = fom
    return foms


@pytest.fixture(scope="module")
def expected_models(expected_foms):
    """Fit both scaling models independently."""
    nodes = [NODE_COUNTS[n] for n in SCALING_RUNS]
    foms = [expected_foms[n] for n in SCALING_RUNS]

    # Power-law
    pl_coeff, pl_exp = fit_power_law(nodes, foms)
    pl_r2 = r_squared_fom_space(
        nodes, foms, predict_power_law, pl_coeff, pl_exp
    )
    pl_pred_256 = predict_power_law(256, pl_coeff, pl_exp)

    # Amdahl
    am_fom1, am_f = fit_amdahl(nodes, foms)
    am_r2 = r_squared_fom_space(
        nodes, foms, predict_amdahl, am_fom1, am_f
    )
    am_pred_256 = predict_amdahl(256, am_fom1, am_f)

    best = "power_law" if pl_r2 > am_r2 else "amdahl"

    return {
        "power_law": {
            "coefficient": pl_coeff,
            "exponent": pl_exp,
            "r_squared": pl_r2,
            "predicted_fom_256": pl_pred_256,
        },
        "amdahl": {
            "fom1": am_fom1,
            "serial_fraction": am_f,
            "r_squared": am_r2,
            "predicted_fom_256": am_pred_256,
        },
        "best_model": best,
    }


# ---------------------------------------------------------------------------
# Tests — structure and presence
# ---------------------------------------------------------------------------

class TestStructure:
    """Verify report.json has the required structure."""

    def test_has_audit(self, agent_results):
        assert "audit" in agent_results

    def test_has_fom(self, agent_results):
        assert "fom" in agent_results

    def test_has_scaling_models(self, agent_results):
        assert "scaling_models" in agent_results

    def test_has_cross_validation(self, agent_results):
        assert "cross_validation" in agent_results

    def test_fom_keys(self, agent_results):
        fom = agent_results["fom"]
        for name in ALL_RUNS:
            assert name in fom, "Missing FOM for '{}'".format(name)
            assert isinstance(fom[name], (int, float)), (
                "FOM for '{}' must be numeric".format(name)
            )

    def test_scaling_model_keys(self, agent_results):
        sm = agent_results["scaling_models"]
        assert "amdahl" in sm
        assert "power_law" in sm
        assert "best_model" in sm
        assert sm["best_model"] in ("amdahl", "power_law")

    def test_amdahl_keys(self, agent_results):
        am = agent_results["scaling_models"]["amdahl"]
        for key in ("serial_fraction", "r_squared", "predicted_fom_256"):
            assert key in am, "Missing '{}' in amdahl".format(key)

    def test_power_law_keys(self, agent_results):
        pl = agent_results["scaling_models"]["power_law"]
        for key in ("exponent", "coefficient", "r_squared", "predicted_fom_256"):
            assert key in pl, "Missing '{}' in power_law".format(key)

    def test_cross_validation_keys(self, agent_results):
        cv = agent_results["cross_validation"]
        for key in ("actual_node_count", "predicted_fom",
                     "actual_fom", "prediction_error_pct"):
            assert key in cv, "Missing '{}' in cross_validation".format(key)


# ---------------------------------------------------------------------------
# Tests — audit (data forensics)
# ---------------------------------------------------------------------------

class TestAudit:
    """Verify the agent discovered the embedded data quality issues."""

    def test_has_data_issues(self, agent_results):
        issues = agent_results["audit"]["data_issues"]
        assert len(issues) >= 2, (
            "Should find at least 2 data issues (restart + manifest mismatch)"
        )

    def test_found_scaling_16_issue(self, agent_results):
        issues = agent_results["audit"]["data_issues"]
        runs_flagged = [i.get("run", "") for i in issues]
        assert "scaling_16" in runs_flagged, (
            "Should flag scaling_16 as having a data issue (restart)"
        )

    def test_found_validation_issue(self, agent_results):
        issues = agent_results["audit"]["data_issues"]
        runs_flagged = [i.get("run", "") for i in issues]
        assert "validation" in runs_flagged, (
            "Should flag validation run (manifest says 32 nodes, log has 24)"
        )

    def test_has_script_issues(self, agent_results):
        issues = agent_results["audit"]["script_issues"]
        assert len(issues) >= 1, (
            "Should find at least 1 script issue "
            "(first-block-only or boundary condition)"
        )


# ---------------------------------------------------------------------------
# Tests — FOM values
# ---------------------------------------------------------------------------

class TestFOM:
    """Verify FOM computations against independent reference."""

    @pytest.mark.parametrize("name", ALL_RUNS)
    def test_fom_value(self, agent_results, expected_foms, name):
        actual = agent_results["fom"][name]
        expected = expected_foms[name]
        assert expected is not None, "Reference FOM is None for {}".format(name)
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.005, (
            "FOM mismatch for {}: got {:.4f}, expected {:.4f} "
            "(rel err {:.4f})".format(name, actual, expected, rel_err)
        )

    @pytest.mark.parametrize("name", ALL_RUNS)
    def test_fom_positive(self, agent_results, name):
        assert agent_results["fom"][name] > 0

    def test_fom_decreases_with_nodes(self, agent_results):
        """Per-node FOM should decrease as node count grows."""
        fom = agent_results["fom"]
        ordered = [fom[n] for n in SCALING_RUNS]
        for i in range(len(ordered) - 1):
            assert ordered[i] > ordered[i + 1], (
                "FOM should decrease: {} ({:.2f}) > {} ({:.2f})".format(
                    SCALING_RUNS[i], ordered[i],
                    SCALING_RUNS[i + 1], ordered[i + 1],
                )
            )


# ---------------------------------------------------------------------------
# Tests — scaling models
# ---------------------------------------------------------------------------

class TestScalingModels:
    """Verify scaling model fits and selection."""

    def test_best_model_selection(self, agent_results, expected_models):
        assert agent_results["scaling_models"]["best_model"] == (
            expected_models["best_model"]
        ), "Best model mismatch: got '{}', expected '{}'".format(
            agent_results["scaling_models"]["best_model"],
            expected_models["best_model"],
        )

    def test_power_law_exponent(self, agent_results, expected_models):
        actual = agent_results["scaling_models"]["power_law"]["exponent"]
        expected = expected_models["power_law"]["exponent"]
        rel_err = abs(actual - expected) / max(abs(expected), 1e-9)
        assert rel_err < 0.10, (
            "Power-law exponent: got {:.6f}, expected {:.6f}".format(
                actual, expected
            )
        )

    def test_power_law_coefficient(self, agent_results, expected_models):
        actual = agent_results["scaling_models"]["power_law"]["coefficient"]
        expected = expected_models["power_law"]["coefficient"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.05, (
            "Power-law coefficient: got {:.4f}, expected {:.4f}".format(
                actual, expected
            )
        )

    def test_power_law_r_squared(self, agent_results, expected_models):
        actual = agent_results["scaling_models"]["power_law"]["r_squared"]
        expected = expected_models["power_law"]["r_squared"]
        assert abs(actual - expected) < 0.05, (
            "Power-law R-squared: got {:.6f}, expected {:.6f}".format(
                actual, expected
            )
        )

    def test_amdahl_serial_fraction(self, agent_results, expected_models):
        actual = agent_results["scaling_models"]["amdahl"]["serial_fraction"]
        expected = expected_models["amdahl"]["serial_fraction"]
        rel_err = abs(actual - expected) / max(abs(expected), 1e-9)
        assert rel_err < 0.15, (
            "Amdahl serial fraction: got {:.6f}, expected {:.6f}".format(
                actual, expected
            )
        )

    def test_amdahl_r_squared(self, agent_results, expected_models):
        actual = agent_results["scaling_models"]["amdahl"]["r_squared"]
        expected = expected_models["amdahl"]["r_squared"]
        assert abs(actual - expected) < 0.10, (
            "Amdahl R-squared: got {:.6f}, expected {:.6f}".format(
                actual, expected
            )
        )

    def test_predicted_fom_256_reasonable(self, agent_results, expected_foms):
        """Predicted FOM at 256 nodes should be below FOM at 1 node."""
        best = agent_results["scaling_models"]["best_model"]
        predicted = agent_results["scaling_models"][best]["predicted_fom_256"]
        fom_1 = expected_foms["scaling_1"]
        fom_64 = expected_foms["scaling_64"]
        assert predicted < fom_64, (
            "Predicted FOM at 256 ({:.2f}) should be below FOM at 64 "
            "({:.2f})".format(predicted, fom_64)
        )
        assert predicted > 0.3 * fom_1, (
            "Predicted FOM at 256 ({:.2f}) unreasonably low".format(predicted)
        )

    def test_predicted_fom_256_near_reference(self, agent_results, expected_models):
        """Predicted FOM should be within 10% of reference."""
        best = expected_models["best_model"]
        actual = agent_results["scaling_models"][best]["predicted_fom_256"]
        expected = expected_models[best]["predicted_fom_256"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.10, (
            "Predicted FOM 256: got {:.4f}, expected {:.4f} "
            "(rel err {:.4f})".format(actual, expected, rel_err)
        )


# ---------------------------------------------------------------------------
# Tests — cross-validation
# ---------------------------------------------------------------------------

class TestCrossValidation:
    """Verify cross-validation against the validation run."""

    def test_actual_node_count(self, agent_results):
        """Must determine actual node count from log (24, not manifest's 32)."""
        assert agent_results["cross_validation"]["actual_node_count"] == 24, (
            "Validation log has 2688 ranks = 24 nodes, not manifest's 32"
        )

    def test_actual_fom_matches(self, agent_results, expected_foms):
        actual = agent_results["cross_validation"]["actual_fom"]
        expected = expected_foms["validation"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.005, (
            "Validation actual FOM: got {:.4f}, expected {:.4f}".format(
                actual, expected
            )
        )

    def test_predicted_fom_reasonable(self, agent_results, expected_foms):
        """Predicted FOM should be in plausible range."""
        predicted = agent_results["cross_validation"]["predicted_fom"]
        fom_1 = expected_foms["scaling_1"]
        fom_64 = expected_foms["scaling_64"]
        assert fom_64 < predicted < fom_1, (
            "Predicted FOM {:.2f} should be between FOM_64 ({:.2f}) "
            "and FOM_1 ({:.2f})".format(predicted, fom_64, fom_1)
        )

    def test_prediction_error_consistent(self, agent_results):
        """prediction_error_pct should be consistent with predicted vs actual."""
        predicted = agent_results["cross_validation"]["predicted_fom"]
        actual = agent_results["cross_validation"]["actual_fom"]
        expected_error = abs(predicted - actual) / actual * 100
        reported_error = agent_results["cross_validation"]["prediction_error_pct"]
        assert abs(reported_error - expected_error) < 2.0, (
            "Error pct {:.2f} inconsistent with values "
            "(predicted {:.4f}, actual {:.4f} -> {:.2f}%)".format(
                reported_error, predicted, actual, expected_error
            )
        )

    def test_prediction_error_small(self, agent_results):
        """Cross-validation error should be reasonably small for a good model."""
        error = agent_results["cross_validation"]["prediction_error_pct"]
        assert error < 15.0, (
            "Prediction error {:.2f}% seems too large".format(error)
        )


# ---------------------------------------------------------------------------
# Tests — SQLite database
# ---------------------------------------------------------------------------

class TestDatabase:
    """Verify SQLite benchmark database at /app/benchmark.db."""

    def test_db_exists(self):
        assert os.path.exists(DB_PATH), (
            "SQLite database not found at {}".format(DB_PATH)
        )

    def test_runs_table_exists(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='runs'"
        )
        assert cursor.fetchone() is not None, "Table 'runs' not found"
        conn.close()

    def test_scaling_models_table_exists(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='scaling_models'"
        )
        assert cursor.fetchone() is not None, "Table 'scaling_models' not found"
        conn.close()

    def test_audit_issues_table_exists(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='audit_issues'"
        )
        assert cursor.fetchone() is not None, "Table 'audit_issues' not found"
        conn.close()

    def test_all_runs_present(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute("SELECT run_name FROM runs ORDER BY run_name")
        run_names = sorted([row[0] for row in cursor.fetchall()])
        conn.close()
        expected = sorted(ALL_RUNS)
        assert run_names == expected, (
            "Expected runs {} but got {}".format(expected, run_names)
        )

    def test_run_foms_match_report(self, agent_results):
        conn = sqlite3_mod.connect(DB_PATH)
        for name in ALL_RUNS:
            cursor = conn.execute(
                "SELECT fom FROM runs WHERE run_name=?", (name,)
            )
            row = cursor.fetchone()
            assert row is not None, (
                "Run {} not found in database".format(name)
            )
            db_fom = row[0]
            report_fom = agent_results["fom"][name]
            rel_err = abs(db_fom - report_fom) / max(abs(report_fom), 1e-9)
            assert rel_err < 0.001, (
                "FOM mismatch for {} between DB ({:.6f}) and report "
                "({:.6f})".format(name, db_fom, report_fom)
            )
        conn.close()

    def test_validation_actual_nodes_in_db(self):
        """DB should store actual node count (24), not manifest's 32."""
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT num_nodes FROM runs WHERE run_name='validation'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "Validation run not in database"
        assert row[0] == 24, (
            "Validation should have 24 actual nodes, got {}".format(row[0])
        )

    def test_both_models_in_db(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT model_name FROM scaling_models ORDER BY model_name"
        )
        models = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "amdahl" in models, "Amdahl model not in scaling_models table"
        assert "power_law" in models, (
            "Power-law model not in scaling_models table"
        )

    def test_audit_issues_populated(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM audit_issues")
        count = cursor.fetchone()[0]
        conn.close()
        assert count >= 3, (
            "Expected at least 3 audit issues, got {}".format(count)
        )

    def test_audit_has_data_and_script_categories(self):
        conn = sqlite3_mod.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT DISTINCT category FROM audit_issues ORDER BY category"
        )
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "data" in categories, "No 'data' category audit issues in DB"
        assert "script" in categories, "No 'script' category audit issues in DB"


# ---------------------------------------------------------------------------
# Tests — gnuplot scaling visualization
# ---------------------------------------------------------------------------

class TestPlot:
    """Verify gnuplot scaling visualization at /app/scaling_plot.png."""

    def test_plot_exists(self):
        assert os.path.exists(PLOT_PATH), (
            "Scaling plot not found at {}".format(PLOT_PATH)
        )

    def test_plot_is_valid_png(self):
        with open(PLOT_PATH, "rb") as f:
            header = f.read(8)
        assert header[:4] == b"\x89PNG", (
            "File at {} is not a valid PNG (bad magic bytes)".format(PLOT_PATH)
        )

    def test_plot_has_substance(self):
        """Plot should be large enough to contain actual data visualization."""
        size = os.path.getsize(PLOT_PATH)
        assert size > 2000, (
            "Plot file only {} bytes — likely empty or trivial".format(size)
        )
