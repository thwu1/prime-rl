
import json
import os
import sqlite3
import pytest


def rel_close(actual, expected, tol=0.01):
    """Check if actual is within tol relative error of expected."""
    if expected == 0:
        return abs(actual) < 1e-9
    return abs(actual - expected) / abs(expected) < tol


@pytest.fixture
def report():
    path = "/app/report.json"
    assert os.path.exists(path), "report.json not found at /app/report.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def schema():
    path = "/app/schema.json"
    assert os.path.exists(path), "schema.json not found at /app/schema.json"
    with open(path) as f:
        return json.load(f)


# -------------------------------------------------------------------------
# Schema compliance
# -------------------------------------------------------------------------

class TestSchemaCompliance:
    def test_report_validates_against_schema(self, report, schema):
        import jsonschema
        jsonschema.validate(instance=report, schema=schema)

    def test_has_required_top_level_keys(self, report):
        for key in ["system", "benchmarks", "scaling_analysis", "aggregate_score"]:
            assert key in report, f"Missing required top-level key: {key}"

    def test_has_required_benchmark_sections(self, report):
        for bench in ["lammps", "milc", "workflow"]:
            assert bench in report["benchmarks"], f"Missing benchmark section: {bench}"


# -------------------------------------------------------------------------
# LAMMPS
# -------------------------------------------------------------------------

class TestLAMMPS:
    def test_best_valid_fom(self, report):
        fom = report["benchmarks"]["lammps"]["best_valid_fom"]
        assert rel_close(fom, 111262126.14, 0.01), \
            f"LAMMPS best_valid_fom {fom} not within 1% of 111262126.14"

    def test_runs_count(self, report):
        runs = report["benchmarks"]["lammps"]["runs"]
        assert len(runs) >= 2, "Expected at least 2 LAMMPS runs"

    def test_nano_validation_passes(self, report):
        runs = report["benchmarks"]["lammps"]["runs"]
        nano = [r for r in runs if r["num_atoms"] < 100_000_000]
        assert len(nano) >= 1, "No nano-scale LAMMPS run found"
        assert any(r["validation_passed"] for r in nano), \
            "Nano LAMMPS run should pass PE/molecule validation"

    def test_tiny_validation_fails(self, report):
        runs = report["benchmarks"]["lammps"]["runs"]
        tiny = [r for r in runs if r["num_atoms"] > 100_000_000]
        assert len(tiny) >= 1, "No tiny-scale LAMMPS run found"
        assert all(not r["validation_passed"] for r in tiny), \
            "Tiny LAMMPS run should fail PE/molecule validation"

    def test_pe_per_molecule_values(self, report):
        runs = report["benchmarks"]["lammps"]["runs"]
        for r in runs:
            assert "pe_per_molecule" in r, f"Missing pe_per_molecule in {r['log_file']}"
            assert isinstance(r["pe_per_molecule"], (int, float))


# -------------------------------------------------------------------------
# MILC
# -------------------------------------------------------------------------

class TestMILC:
    def test_optimal_nodes(self, report):
        opt = report["benchmarks"]["milc"]["optimal_config"]
        assert opt["nodes_per_replica"] == 64, \
            f"Expected optimal nodes=64, got {opt['nodes_per_replica']}"

    def test_optimal_replicas(self, report):
        opt = report["benchmarks"]["milc"]["optimal_config"]
        assert opt["replicas"] == 148, \
            f"Expected optimal replicas=148, got {opt['replicas']}"

    def test_optimal_final_fom(self, report):
        opt = report["benchmarks"]["milc"]["optimal_config"]
        assert rel_close(opt["final_fom"], 29362.49, 0.01), \
            f"MILC optimal final_fom {opt['final_fom']} not within 1% of 29362.49"

    def test_32node_invalid(self, report):
        runs = report["benchmarks"]["milc"]["runs"]
        r32 = [r for r in runs if r["nodes"] == 32]
        assert len(r32) == 1, "Expected exactly one 32-node MILC run"
        assert not r32[0]["validation_passed"], \
            "MILC 32-node run should fail plaquette validation"

    def test_64node_valid(self, report):
        runs = report["benchmarks"]["milc"]["runs"]
        r64 = [r for r in runs if r["nodes"] == 64]
        assert len(r64) == 1, "Expected exactly one 64-node MILC run"
        assert r64[0]["validation_passed"], \
            "MILC 64-node run should pass plaquette validation"

    def test_runs_count(self, report):
        runs = report["benchmarks"]["milc"]["runs"]
        assert len(runs) == 4, f"Expected 4 MILC runs, got {len(runs)}"

    def test_best_valid_fom(self, report):
        fom = report["benchmarks"]["milc"]["best_valid_fom"]
        assert rel_close(fom, 29362.49, 0.01), \
            f"MILC best_valid_fom {fom} not within 1% of 29362.49"


# -------------------------------------------------------------------------
# Workflow
# -------------------------------------------------------------------------

class TestWorkflow:
    def test_fom(self, report):
        fom = report["benchmarks"]["workflow"]["best_valid_fom"]
        assert rel_close(fom, 1.493669, 0.01), \
            f"Workflow best_valid_fom {fom} not within 1% of 1.493669"

    def test_validation_passes(self, report):
        runs = report["benchmarks"]["workflow"]["runs"]
        assert len(runs) >= 1
        assert runs[0]["validation_passed"], \
            "Workflow run should pass validation (loss 0.0234 < 0.05)"

    def test_final_loss(self, report):
        runs = report["benchmarks"]["workflow"]["runs"]
        assert rel_close(runs[0]["final_loss"], 0.0234, 0.01)


# -------------------------------------------------------------------------
# Aggregate score
# -------------------------------------------------------------------------

class TestAggregate:
    def test_aggregate_score(self, report):
        score = report["aggregate_score"]
        assert rel_close(score, 1.213582, 0.02), \
            f"Aggregate score {score} not within 2% of 1.213582"

    def test_aggregate_above_one(self, report):
        assert report["aggregate_score"] > 1.0, \
            "Aggregate score should be > 1.0 (system exceeds reference)"


# -------------------------------------------------------------------------
# Scaling analysis
# -------------------------------------------------------------------------

class TestScaling:
    def test_scaling_benchmark(self, report):
        sa = report["scaling_analysis"]
        assert sa["benchmark"] == "milc"

    def test_scaling_reference_nodes(self, report):
        sa = report["scaling_analysis"]
        assert sa["reference_nodes"] == 64, \
            f"Expected reference_nodes=64, got {sa['reference_nodes']}"

    def test_scaling_data_point_count(self, report):
        points = report["scaling_analysis"]["data_points"]
        assert len(points) == 3, \
            f"Expected 3 scaling data points (64,128,256 valid), got {len(points)}"

    def test_reference_efficiency(self, report):
        points = report["scaling_analysis"]["data_points"]
        ref = [p for p in points if p["nodes"] == 64]
        assert len(ref) == 1, "Missing 64-node scaling data point"
        assert rel_close(ref[0]["parallel_efficiency"], 1.0, 0.001)
        assert rel_close(ref[0]["speedup"], 1.0, 0.001)

    def test_128node_efficiency(self, report):
        points = report["scaling_analysis"]["data_points"]
        p128 = [p for p in points if p["nodes"] == 128]
        assert len(p128) == 1, "Missing 128-node scaling data point"
        assert rel_close(p128[0]["parallel_efficiency"], 0.9109, 0.02), \
            f"128-node efficiency {p128[0]['parallel_efficiency']} not within 2% of 0.9109"

    def test_256node_efficiency(self, report):
        points = report["scaling_analysis"]["data_points"]
        p256 = [p for p in points if p["nodes"] == 256]
        assert len(p256) == 1, "Missing 256-node scaling data point"
        assert rel_close(p256[0]["parallel_efficiency"], 0.7653, 0.02), \
            f"256-node efficiency {p256[0]['parallel_efficiency']} not within 2% of 0.7653"

    def test_speedup_monotonic(self, report):
        points = sorted(report["scaling_analysis"]["data_points"],
                        key=lambda p: p["nodes"])
        for i in range(1, len(points)):
            assert points[i]["speedup"] > points[i - 1]["speedup"], \
                "Speedup should increase with node count"

    def test_efficiency_decreasing(self, report):
        points = sorted(report["scaling_analysis"]["data_points"],
                        key=lambda p: p["nodes"])
        for i in range(1, len(points)):
            assert points[i]["parallel_efficiency"] < points[i - 1]["parallel_efficiency"], \
                "Parallel efficiency should decrease with more nodes (strong scaling)"


# -------------------------------------------------------------------------
# SQLite database
# -------------------------------------------------------------------------

class TestSQLiteDatabase:
    def test_database_exists(self):
        assert os.path.exists("/app/results.db"), \
            "SQLite database /app/results.db not found"

    def test_tables_exist(self):
        conn = sqlite3.connect("/app/results.db")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        for t in ["lammps_runs", "milc_runs", "workflow_runs", "milc_scaling"]:
            assert t in tables, f"Missing table: {t}"

    def test_lammps_row_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM lammps_runs").fetchone()[0]
        conn.close()
        assert count >= 2, f"Expected >= 2 LAMMPS rows, got {count}"

    def test_milc_row_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM milc_runs").fetchone()[0]
        conn.close()
        assert count == 4, f"Expected 4 MILC rows, got {count}"

    def test_workflow_row_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        conn.close()
        assert count >= 1, f"Expected >= 1 workflow row, got {count}"

    def test_milc_optimal_via_sql(self):
        conn = sqlite3.connect("/app/results.db")
        row = conn.execute(
            "SELECT nodes, final_fom FROM milc_runs "
            "WHERE validation_passed = 1 "
            "ORDER BY final_fom DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None, "No valid MILC runs in database"
        assert row[0] == 64, f"SQL optimal nodes should be 64, got {row[0]}"
        assert rel_close(row[1], 29362.49, 0.01), \
            f"SQL optimal final_fom {row[1]} not within 1% of 29362.49"

    def test_milc_32node_invalid_in_db(self):
        conn = sqlite3.connect("/app/results.db")
        row = conn.execute(
            "SELECT validation_passed FROM milc_runs WHERE nodes = 32"
        ).fetchone()
        conn.close()
        assert row is not None, "32-node MILC run missing from database"
        assert row[0] == 0, "32-node MILC run should be invalid in database"

    def test_scaling_data_in_db(self):
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT nodes, parallel_efficiency FROM milc_scaling ORDER BY nodes"
        ).fetchall()
        conn.close()
        assert len(rows) == 3, f"Expected 3 scaling rows, got {len(rows)}"
        nodes = [r[0] for r in rows]
        assert nodes == [64, 128, 256], f"Expected nodes [64,128,256], got {nodes}"
        assert rel_close(rows[0][1], 1.0, 0.001)


# -------------------------------------------------------------------------
# MILC AWK validation output files
# -------------------------------------------------------------------------

class TestMILCValidationFiles:
    def test_validation_directory_exists(self):
        assert os.path.isdir("/app/milc_validations"), \
            "Directory /app/milc_validations/ not found"

    def test_validation_files_exist(self):
        expected = [
            "milc_ref_32nodes.log.validation",
            "milc_ref_64nodes.log.validation",
            "milc_ref_128nodes.log.validation",
            "milc_ref_256nodes.log.validation",
        ]
        for f in expected:
            path = os.path.join("/app/milc_validations", f)
            assert os.path.exists(path), f"Missing validation file: {f}"

    def test_32node_fails_validation(self):
        path = "/app/milc_validations/milc_ref_32nodes.log.validation"
        with open(path) as f:
            content = f.read()
        assert "validation=FAIL" in content, \
            "32-node AWK validation should output FAIL"

    def test_64node_passes_validation(self):
        path = "/app/milc_validations/milc_ref_64nodes.log.validation"
        with open(path) as f:
            content = f.read()
        assert "validation=PASS" in content, \
            "64-node AWK validation should output PASS"

    def test_validation_contains_metrics(self):
        path = "/app/milc_validations/milc_ref_64nodes.log.validation"
        with open(path) as f:
            content = f.read()
        for key in ["nodes=", "traj2_mean_gftime=", "olcf_fom=",
                     "final_plaquette=", "deviation_pct="]:
            assert key in content, f"AWK output missing key: {key}"
