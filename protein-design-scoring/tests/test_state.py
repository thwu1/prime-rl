"""Verification tests for the protein binder design triage pipeline.

"""
import json
import os
import shutil
import sqlite3
import subprocess

import pytest


@pytest.fixture(scope="session")
def expected():
    with open("/app/expected_results.json") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found — did run_pipeline.sh complete?"
    with open(path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists("/app/results.json"), "results.json missing"


def test_results_structure(results):
    assert "designs" in results, "Missing 'designs' key"
    assert "ranking" in results, "Missing 'ranking' key"
    assert len(results["designs"]) == 5, \
        f"Expected 5 designs, got {len(results['designs'])}"
    assert len(results["ranking"]) == 5, \
        f"Expected 5 in ranking, got {len(results['ranking'])}"
    for i in range(1, 6):
        name = f"design_{i}"
        assert name in results["designs"], f"Missing {name}"
        d = results["designs"][name]
        for key in ["rmsd", "lddt", "tm_score", "gdt_ts",
                     "interface_contacts", "hotspot_coverage",
                     "interface_pae", "mean_plddt", "composite_score"]:
            assert key in d, f"Missing key '{key}' in {name}"


# ---------------------------------------------------------------------------
# Metric-value tests
# ---------------------------------------------------------------------------

def test_rmsd_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["rmsd"]
        exp = expected["designs"][name]["rmsd"]
        assert abs(actual - exp) < 0.15, \
            f"RMSD {name}: got {actual:.4f}, expected {exp:.4f}"


def test_lddt_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["lddt"]
        exp = expected["designs"][name]["lddt"]
        assert abs(actual - exp) < 0.03, \
            f"lDDT {name}: got {actual:.4f}, expected {exp:.4f}"


def test_tm_score_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["tm_score"]
        exp = expected["designs"][name]["tm_score"]
        assert abs(actual - exp) < 0.05, \
            f"TM-score {name}: got {actual:.4f}, expected {exp:.4f}"


def test_gdt_ts_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["gdt_ts"]
        exp = expected["designs"][name]["gdt_ts"]
        assert abs(actual - exp) < 0.05, \
            f"GDT-TS {name}: got {actual:.4f}, expected {exp:.4f}"


def test_interface_contacts_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["interface_contacts"]
        exp = expected["designs"][name]["interface_contacts"]
        assert abs(actual - exp) <= 2, \
            f"Contacts {name}: got {actual}, expected {exp}"


def test_hotspot_coverage_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["hotspot_coverage"]
        exp = expected["designs"][name]["hotspot_coverage"]
        assert abs(actual - exp) < 0.02, \
            f"Hotspot coverage {name}: got {actual:.4f}, expected {exp:.4f}"


def test_interface_pae_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["interface_pae"]
        exp = expected["designs"][name]["interface_pae"]
        assert abs(actual - exp) < 0.5, \
            f"Interface PAE {name}: got {actual:.4f}, expected {exp:.4f}"


def test_mean_plddt_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["mean_plddt"]
        exp = expected["designs"][name]["mean_plddt"]
        assert abs(actual - exp) < 0.5, \
            f"Mean pLDDT {name}: got {actual:.4f}, expected {exp:.4f}"


def test_composite_score_values(results, expected):
    for name in expected["designs"]:
        actual = results["designs"][name]["composite_score"]
        exp = expected["designs"][name]["composite_score"]
        assert abs(actual - exp) < 0.05, \
            f"Composite {name}: got {actual:.4f}, expected {exp:.4f}"


def test_ranking_order(results, expected):
    assert results["ranking"] == expected["ranking"], \
        f"Ranking mismatch:\n  got:      {results['ranking']}\n  expected: {expected['ranking']}"


# ---------------------------------------------------------------------------
# Metric range / sanity tests
# ---------------------------------------------------------------------------

def test_metric_ranges(results):
    for name, d in results["designs"].items():
        assert d["rmsd"] >= 0, f"RMSD must be >= 0 ({name})"
        assert 0 <= d["lddt"] <= 1, f"lDDT must be in [0,1] ({name})"
        assert 0 <= d["tm_score"] <= 1, f"TM-score must be in [0,1] ({name})"
        assert 0 <= d["gdt_ts"] <= 1, f"GDT-TS must be in [0,1] ({name})"
        assert d["interface_contacts"] >= 0, f"Contacts must be >= 0 ({name})"
        assert 0 <= d["hotspot_coverage"] <= 1, \
            f"Coverage must be in [0,1] ({name})"
        assert d["interface_pae"] >= 0, f"PAE must be >= 0 ({name})"
        assert 0 <= d["mean_plddt"] <= 100, f"pLDDT must be in [0,100] ({name})"


# ---------------------------------------------------------------------------
# PAE normalization tests
# ---------------------------------------------------------------------------

def test_pae_normalized_files_exist():
    """All PAE files should have been normalized to uniform JSON format."""
    for i in range(1, 6):
        path = f"/app/pae_normalized/design_{i}.json"
        assert os.path.exists(path), f"Normalized PAE missing: {path}"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list), \
            f"Normalized PAE should be a 2D JSON array: {path}"
        assert len(data) == 100, \
            f"PAE matrix should be 100x100, got {len(data)} rows: {path}"
        assert len(data[0]) == 100, \
            f"PAE matrix row should have 100 cols, got {len(data[0])}: {path}"


# ---------------------------------------------------------------------------
# SQLite database tests
# ---------------------------------------------------------------------------

def test_database_exists():
    assert os.path.exists("/app/designs.db"), "SQLite database /app/designs.db missing"


def test_database_metrics_table():
    """The database must have a 'metrics' table with 5 rows of data."""
    db = sqlite3.connect("/app/designs.db")
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "metrics" in tables, f"'metrics' table missing; found tables: {tables}"
    count = db.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    assert count == 5, f"Expected 5 rows in metrics, got {count}"
    db.close()


def test_database_ranked_view():
    """The database must have a 'ranked_designs' view with composite scores."""
    db = sqlite3.connect("/app/designs.db")
    views = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='view'"
    ).fetchall()]
    assert "ranked_designs" in views, \
        f"'ranked_designs' view missing; found views: {views}"

    rows = db.execute(
        "SELECT design, composite_score FROM ranked_designs ORDER BY composite_score DESC"
    ).fetchall()
    assert len(rows) == 5, f"Expected 5 rows in ranked_designs, got {len(rows)}"

    # Verify scores are in descending order
    scores = [r[1] for r in rows]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], \
            f"ranked_designs not sorted descending: {scores}"

    db.close()


# ---------------------------------------------------------------------------
# Anti-hardcoding: perturbation test
# ---------------------------------------------------------------------------

def test_pipeline_responds_to_perturbation():
    """Verify pipeline computes from input data, not hardcoded values."""
    shutil.copy("/app/results.json", "/app/results_backup.json")
    shutil.copy("/app/structures/design_1.pdb",
                "/app/structures/design_1.pdb.bak")

    try:
        # Shift first 5 binder (chain B) atoms by +10 A in X
        lines = []
        modified = 0
        with open("/app/structures/design_1.pdb") as f:
            for line in f:
                if (line.startswith("ATOM") and len(line) > 54
                        and line[21] == "B" and modified < 5):
                    x = float(line[30:38]) + 10.0
                    line = line[:30] + "%8.3f" % x + line[38:]
                    modified += 1
                lines.append(line)
        with open("/app/structures/design_1.pdb", "w") as f:
            f.writelines(lines)

        # Re-run pipeline
        result = subprocess.run(
            ["bash", "/app/run_pipeline.sh"],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"Pipeline failed: {result.stderr}"

        with open("/app/results.json") as f:
            perturbed = json.load(f)
        with open("/app/results_backup.json") as f:
            original = json.load(f)

        rmsd_diff = abs(
            perturbed["designs"]["design_1"]["rmsd"]
            - original["designs"]["design_1"]["rmsd"]
        )
        assert rmsd_diff > 0.1, \
            "RMSD unchanged after coordinate perturbation — values may be hardcoded"
    finally:
        shutil.copy("/app/structures/design_1.pdb.bak",
                     "/app/structures/design_1.pdb")
        if os.path.exists("/app/structures/design_1.pdb.bak"):
            os.remove("/app/structures/design_1.pdb.bak")
        shutil.copy("/app/results_backup.json", "/app/results.json")
        if os.path.exists("/app/results_backup.json"):
            os.remove("/app/results_backup.json")
