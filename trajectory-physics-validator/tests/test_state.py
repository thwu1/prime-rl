
import json
import os
import sqlite3

import pytest

REPORTS_DIR = "/app/reports"
PLOTS_DIR = "/app/plots"
DB_PATH = "/app/results.db"


def load_report(name: str) -> dict:
    path = os.path.join(REPORTS_DIR, f"{name}_report.json")
    assert os.path.exists(path), f"Report file not found: {path}"
    with open(path) as fh:
        return json.load(fh)


# ── scenario list ─────────────────────────────────────────────────────────

SCENARIO_NAMES = [
    "correct_bounce",
    "correct_collision",
    "correct_tumble",
    "energy_gain",
    "interpenetration",
    "jittery_motion",
    "momentum_violation",
    "kinematic_mismatch",
    "euler_drift",
]


# ── report structure ──────────────────────────────────────────────────────

class TestReportStructure:
    """Every report must contain required keys with correct types."""

    @pytest.fixture(params=SCENARIO_NAMES)
    def report(self, request):
        return load_report(request.param)

    def test_has_plausibility_score(self, report):
        assert "plausibility_score" in report
        s = report["plausibility_score"]
        assert isinstance(s, (int, float))
        assert 0.0 <= s <= 100.0

    def test_has_anomalies_energy(self, report):
        a = report.get("anomalies", {})
        assert "energy_violations" in a
        assert isinstance(a["energy_violations"], list)

    def test_has_anomalies_momentum(self, report):
        a = report.get("anomalies", {})
        assert "momentum_violations" in a
        assert isinstance(a["momentum_violations"], list)

    def test_has_anomalies_interpenetrations(self, report):
        a = report.get("anomalies", {})
        assert "interpenetrations" in a
        assert isinstance(a["interpenetrations"], list)

    def test_has_anomalies_jitter(self, report):
        a = report.get("anomalies", {})
        assert "jitter_detected" in a
        assert isinstance(a["jitter_detected"], bool)

    def test_has_anomalies_kinematic(self, report):
        a = report.get("anomalies", {})
        assert "kinematic_violations" in a
        assert isinstance(a["kinematic_violations"], list)

    def test_has_anomalies_angular_momentum(self, report):
        a = report.get("anomalies", {})
        assert "angular_momentum_violations" in a
        assert isinstance(a["angular_momentum_violations"], list)


# ── correct bounce (single sphere with spin, no defects) ──────────────────

class TestCorrectBounce:
    def test_high_score(self):
        r = load_report("correct_bounce")
        assert r["plausibility_score"] >= 85.0

    def test_no_energy_violations(self):
        r = load_report("correct_bounce")
        assert len(r["anomalies"]["energy_violations"]) == 0

    def test_no_interpenetrations(self):
        r = load_report("correct_bounce")
        assert len(r["anomalies"]["interpenetrations"]) == 0

    def test_no_jitter(self):
        r = load_report("correct_bounce")
        assert r["anomalies"]["jitter_detected"] is False

    def test_no_kinematic_violations(self):
        r = load_report("correct_bounce")
        assert len(r["anomalies"]["kinematic_violations"]) == 0

    def test_no_angular_momentum_violations(self):
        r = load_report("correct_bounce")
        assert len(r["anomalies"]["angular_momentum_violations"]) == 0


# ── correct two-body collision ────────────────────────────────────────────

class TestCorrectCollision:
    def test_high_score(self):
        r = load_report("correct_collision")
        assert r["plausibility_score"] >= 85.0

    def test_no_momentum_violations(self):
        r = load_report("correct_collision")
        assert len(r["anomalies"]["momentum_violations"]) == 0

    def test_no_energy_violations(self):
        r = load_report("correct_collision")
        assert len(r["anomalies"]["energy_violations"]) == 0

    def test_no_kinematic_violations(self):
        r = load_report("correct_collision")
        assert len(r["anomalies"]["kinematic_violations"]) == 0

    def test_no_angular_momentum_violations(self):
        r = load_report("correct_collision")
        assert len(r["anomalies"]["angular_momentum_violations"]) == 0


# ── correct tumble (torque-free ellipsoid — requires quaternion inertia) ──

class TestCorrectTumble:
    """Critical test: passes only when inertia tensor is rotated to world frame."""

    def test_high_score(self):
        r = load_report("correct_tumble")
        assert r["plausibility_score"] >= 85.0

    def test_no_energy_violations(self):
        r = load_report("correct_tumble")
        assert len(r["anomalies"]["energy_violations"]) == 0

    def test_no_angular_momentum_violations(self):
        r = load_report("correct_tumble")
        assert len(r["anomalies"]["angular_momentum_violations"]) == 0

    def test_no_jitter(self):
        r = load_report("correct_tumble")
        assert r["anomalies"]["jitter_detected"] is False


# ── energy gain at first bounce ───────────────────────────────────────────

class TestEnergyGain:
    def test_energy_violations_detected(self):
        r = load_report("energy_gain")
        assert len(r["anomalies"]["energy_violations"]) > 0

    def test_low_score(self):
        r = load_report("energy_gain")
        assert r["plausibility_score"] < 60.0


# ── interpenetration ──────────────────────────────────────────────────────

class TestInterpenetration:
    def test_interpenetrations_detected(self):
        r = load_report("interpenetration")
        assert len(r["anomalies"]["interpenetrations"]) > 0

    def test_low_score(self):
        r = load_report("interpenetration")
        assert r["plausibility_score"] < 50.0

    def test_body_pair_identified(self):
        r = load_report("interpenetration")
        interps = r["anomalies"]["interpenetrations"]
        found = any(
            isinstance(x, dict)
            and "bodies" in x
            and set(x["bodies"]) == {"sphere_a", "sphere_b"}
            for x in interps
        )
        assert found, "Should identify the interpenetrating body pair"


# ── jittery motion ────────────────────────────────────────────────────────

class TestJitteryMotion:
    def test_jitter_detected(self):
        r = load_report("jittery_motion")
        assert r["anomalies"]["jitter_detected"] is True

    def test_moderate_score(self):
        r = load_report("jittery_motion")
        assert r["plausibility_score"] < 70.0


# ── momentum violation ────────────────────────────────────────────────────

class TestMomentumViolation:
    def test_momentum_violations_detected(self):
        r = load_report("momentum_violation")
        assert len(r["anomalies"]["momentum_violations"]) > 0

    def test_low_score(self):
        r = load_report("momentum_violation")
        assert r["plausibility_score"] < 60.0


# ── kinematic mismatch ────────────────────────────────────────────────────

class TestKinematicMismatch:
    def test_kinematic_violations_detected(self):
        r = load_report("kinematic_mismatch")
        assert len(r["anomalies"]["kinematic_violations"]) > 0

    def test_low_score(self):
        r = load_report("kinematic_mismatch")
        assert r["plausibility_score"] < 50.0


# ── euler drift (ellipsoid with angular momentum loss) ────────────────────

class TestEulerDrift:
    """Torque-free ellipsoid whose angular velocity decays — L_world not conserved."""

    def test_angular_momentum_violations_detected(self):
        r = load_report("euler_drift")
        assert len(r["anomalies"]["angular_momentum_violations"]) > 0

    def test_energy_violations_detected(self):
        r = load_report("euler_drift")
        assert len(r["anomalies"]["energy_violations"]) > 0

    def test_low_score(self):
        r = load_report("euler_drift")
        assert r["plausibility_score"] < 30.0


# ── SQLite database ───────────────────────────────────────────────────────

class TestSQLiteDatabase:
    def test_database_exists(self):
        assert os.path.exists(DB_PATH), f"Database not found: {DB_PATH}"

    def test_scenarios_table_has_all_entries(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT name FROM scenarios ORDER BY name")
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        for sn in SCENARIO_NAMES:
            assert sn in names, f"Missing scenario in DB: {sn}"

    def test_scores_match_json_reports(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT name, plausibility_score FROM scenarios")
        db_scores = dict(cursor.fetchall())
        conn.close()
        for name in SCENARIO_NAMES:
            report = load_report(name)
            assert abs(db_scores[name] - report["plausibility_score"]) < 0.01, (
                f"Score mismatch for {name}: DB={db_scores[name]}, "
                f"JSON={report['plausibility_score']}"
            )

    def test_anomalies_table_has_entries(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM anomalies")
        count = cursor.fetchone()[0]
        conn.close()
        assert count > 0, "Anomalies table should not be empty"

    def test_anomalies_reference_valid_scenarios(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT DISTINCT scenario_name FROM anomalies")
        anomaly_scenarios = {row[0] for row in cursor.fetchall()}
        cursor2 = conn.execute("SELECT name FROM scenarios")
        valid_names = {row[0] for row in cursor2.fetchall()}
        conn.close()
        for sn in anomaly_scenarios:
            assert sn in valid_names, f"Anomaly references unknown scenario: {sn}"


# ── gnuplot phase-space plots ─────────────────────────────────────────────

class TestPhasePlots:
    EXPECTED_PLOTS = [
        "correct_bounce_sphere.png",
        "correct_collision_sphere_a.png",
        "correct_collision_sphere_b.png",
        "correct_tumble_ellipsoid.png",
        "energy_gain_sphere.png",
        "interpenetration_sphere_a.png",
        "interpenetration_sphere_b.png",
        "jittery_motion_sphere.png",
        "momentum_violation_sphere_a.png",
        "momentum_violation_sphere_b.png",
        "kinematic_mismatch_sphere.png",
        "euler_drift_ellipsoid.png",
    ]

    def test_plots_directory_exists(self):
        assert os.path.isdir(PLOTS_DIR), f"Plots directory not found: {PLOTS_DIR}"

    def test_expected_png_files_exist(self):
        for name in self.EXPECTED_PLOTS:
            path = os.path.join(PLOTS_DIR, name)
            assert os.path.exists(path), f"Plot not found: {path}"
            assert os.path.getsize(path) > 100, f"Plot file suspiciously small: {path}"

    def test_png_magic_bytes(self):
        """Verify files are actually PNGs."""
        for name in self.EXPECTED_PLOTS:
            path = os.path.join(PLOTS_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path, "rb") as fh:
                header = fh.read(8)
            assert header[:4] == b"\x89PNG", f"Not a valid PNG: {path}"
