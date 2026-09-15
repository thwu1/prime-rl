
import json
import os
import shutil
import sqlite3
import subprocess

import pytest


# ================================================================
# Session-scoped fixtures — pipeline runs once for all tests
# ================================================================


@pytest.fixture(scope="session")
def pipeline_result():
    """Run the ETL pipeline once before all tests."""
    # Clean previous output so we test a fresh run
    for p in ["/app/analytics.db", "/app/output/report.json"]:
        if os.path.exists(p):
            os.remove(p)
    if os.path.exists("/app/intermediate"):
        shutil.rmtree("/app/intermediate", ignore_errors=True)

    result = subprocess.run(
        ["bash", "/app/run.sh"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result


@pytest.fixture(scope="session")
def report(pipeline_result):
    path = "/app/output/report.json"
    assert os.path.exists(path), (
        f"Report not generated at {path}.\n"
        f"Pipeline exit code: {pipeline_result.returncode}\n"
        f"stderr: {pipeline_result.stderr}"
    )
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db(pipeline_result):
    path = "/app/analytics.db"
    assert os.path.exists(path), (
        f"Database not generated at {path}.\n"
        f"Pipeline exit code: {pipeline_result.returncode}\n"
        f"stderr: {pipeline_result.stderr}"
    )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ================================================================
# 1. Pipeline execution
# ================================================================


class TestPipeline:
    def test_pipeline_succeeds(self, pipeline_result):
        assert pipeline_result.returncode == 0, (
            f"Pipeline failed:\n{pipeline_result.stderr}"
        )

    def test_report_file_created(self, pipeline_result):
        assert os.path.exists("/app/output/report.json")

    def test_database_file_created(self, pipeline_result):
        assert os.path.exists("/app/analytics.db")


# ================================================================
# 2. Intermediate NDJSON files produced by jq extraction
# ================================================================


class TestIntermediateFiles:
    @pytest.mark.parametrize(
        "table_name,expected_count",
        [
            ("patients", 3),
            ("organizations", 1),
            ("practitioners", 1),
            ("observations", 5),
            ("medication_requests", 2),
            ("conditions", 2),
        ],
    )
    def test_ndjson_exists_and_row_count(
        self, pipeline_result, table_name, expected_count
    ):
        path = f"/app/intermediate/{table_name}.ndjson"
        assert os.path.exists(path), f"Missing intermediate file: {path}"
        with open(path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == expected_count, (
            f"{table_name}.ndjson: got {len(lines)} rows, expected {expected_count}"
        )


# ================================================================
# 3. Database structure
# ================================================================


class TestDatabaseStructure:
    def test_all_tables_exist(self, db):
        tables = sorted(
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        )
        expected = [
            "conditions",
            "medication_requests",
            "observations",
            "organizations",
            "patients",
            "practitioners",
        ]
        assert tables == expected

    def test_row_counts(self, db):
        counts = {}
        for table in [
            "patients",
            "organizations",
            "practitioners",
            "observations",
            "medication_requests",
            "conditions",
        ]:
            counts[table] = db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        assert counts == {
            "patients": 3,
            "organizations": 1,
            "practitioners": 1,
            "observations": 5,
            "medication_requests": 2,
            "conditions": 2,
        }


# ================================================================
# 4. Data extraction accuracy (FHIR edge cases)
# ================================================================


class TestDataExtraction:
    def test_patient_name(self, db):
        row = db.execute(
            "SELECT family_name, given_name FROM patients WHERE id='pat-1'"
        ).fetchone()
        assert row["family_name"] == "Smith"
        assert row["given_name"] == "John"

    def test_patient_managing_org_present(self, db):
        """pat-1 has managingOrganization (fragment ref to contained org)."""
        row = db.execute(
            "SELECT managing_org_ref FROM patients WHERE id='pat-1'"
        ).fetchone()
        assert row["managing_org_ref"] is not None

    def test_patient_managing_org_absent(self, db):
        """pat-3 has no managingOrganization."""
        row = db.execute(
            "SELECT managing_org_ref FROM patients WHERE id='pat-3'"
        ).fetchone()
        assert row["managing_org_ref"] is None

    def test_observation_value_quantity(self, db):
        """valueQuantity choice-type correctly extracted."""
        row = db.execute(
            "SELECT value_number, value_unit FROM observations WHERE id='obs-hr-1'"
        ).fetchone()
        assert row["value_number"] == pytest.approx(72.0)
        assert row["value_unit"] == "beats/minute"

    def test_observation_date_normalization(self, db):
        """Dates with timestamps normalized to date-only YYYY-MM-DD."""
        dates = dict(
            db.execute("SELECT id, effective_date FROM observations").fetchall()
        )
        # Full datetime -> date only
        assert dates["obs-hr-1"] == "2024-01-15"
        # Already date-only
        assert dates["obs-temp-1"] == "2024-01-15"
        # DateTime with timezone offset -> date only
        assert dates["obs-hr-2"] == "2024-02-20"

    def test_medication_contained_reference(self, db):
        """Contained medication via fragment ref #med-inline resolved to display."""
        row = db.execute(
            "SELECT medication_display FROM medication_requests WHERE id='medreq-1'"
        ).fetchone()
        assert row["medication_display"] == "Lisinopril 10 MG Oral Tablet"

    def test_medication_codeable_concept(self, db):
        """medicationCodeableConcept choice-type correctly extracted."""
        row = db.execute(
            "SELECT medication_display FROM medication_requests WHERE id='medreq-2'"
        ).fetchone()
        assert row["medication_display"] == "Metformin 500 MG Oral Tablet"

    def test_condition_status(self, db):
        """CodeableConcept clinicalStatus/verificationStatus extracted."""
        row = db.execute(
            "SELECT clinical_status, verification_status FROM conditions WHERE id='cond-1'"
        ).fetchone()
        assert row["clinical_status"] == "active"
        assert row["verification_status"] == "confirmed"

    def test_practitioner_qualification(self, db):
        row = db.execute(
            "SELECT prefix, qualification_code FROM practitioners WHERE id='pract-1'"
        ).fetchone()
        assert row["prefix"] == "Dr."
        assert row["qualification_code"] == "MD"


# ================================================================
# 5. Analytics report values
# ================================================================


class TestAnalytics:
    def test_etl_total_resources(self, report):
        assert report["etl_summary"]["total_resources"] == 14

    def test_etl_tables_created(self, report):
        expected = [
            "conditions",
            "medication_requests",
            "observations",
            "organizations",
            "patients",
            "practitioners",
        ]
        assert sorted(report["etl_summary"]["tables_created"]) == expected

    def test_etl_row_counts(self, report):
        rc = report["etl_summary"]["row_counts"]
        assert rc["patients"] == 3
        assert rc["observations"] == 5
        assert rc["medication_requests"] == 2
        assert rc["conditions"] == 2
        assert rc["organizations"] == 1
        assert rc["practitioners"] == 1

    def test_observations_per_patient(self, report):
        opp = report["analytics"]["observations_per_patient"]
        by_id = {r["patient_id"]: r for r in opp}
        assert by_id["pat-1"]["obs_count"] == 2
        assert by_id["pat-1"]["family_name"] == "Smith"
        assert by_id["pat-2"]["obs_count"] == 2
        assert by_id["pat-3"]["obs_count"] == 1

    def test_active_condition_and_med(self, report):
        result = report["analytics"]["active_condition_and_med_patients"]
        assert result == ["pat-1"]

    def test_avg_value_by_loinc(self, report):
        avg = {
            r["loinc_code"]: r["avg_value"]
            for r in report["analytics"]["avg_value_by_loinc"]
        }
        assert avg["8867-4"] == pytest.approx(78.5)
        assert avg["8310-5"] == pytest.approx(37.2)
        assert avg["8480-6"] == pytest.approx(130.0)
        assert avg["1558-6"] == pytest.approx(95.0)

    def test_vital_signs_count(self, report):
        assert report["analytics"]["vital_signs_count"] == 4

    def test_med_status_summary(self, report):
        summary = {
            r["status"]: r["count"]
            for r in report["analytics"]["med_status_summary"]
        }
        assert summary["active"] == 1
        assert summary["completed"] == 1

    def test_patients_missing_managing_org(self, report):
        assert report["analytics"]["patients_missing_managing_org"] == ["pat-3"]

    def test_date_range(self, report):
        dr = report["analytics"]["date_range"]
        assert dr["earliest"] == "2024-01-15"
        assert dr["latest"] == "2024-03-01"

    def test_flagged_observations(self, report):
        flagged = sorted(
            report["analytics"]["flagged_observations"], key=lambda x: x["id"]
        )
        assert len(flagged) == 2
        assert flagged[0]["id"] == "obs-bp-1"
        assert flagged[0]["loinc_code"] == "8480-6"
        assert flagged[0]["value"] == pytest.approx(130.0)
        assert flagged[0]["threshold"] == 120
        assert flagged[0]["flag"] == "HIGH"
        assert flagged[1]["id"] == "obs-hr-2"
        assert flagged[1]["loinc_code"] == "8867-4"
        assert flagged[1]["value"] == pytest.approx(85.0)
        assert flagged[1]["threshold"] == 80
        assert flagged[1]["flag"] == "HIGH"


# ================================================================
# 6. Anti-hardcoding: cross-check database and report
# ================================================================


class TestAntiHardcoding:
    def test_db_report_consistency(self, db, report):
        """Database row counts must match report row counts."""
        for table in [
            "patients",
            "observations",
            "medication_requests",
            "conditions",
            "organizations",
            "practitioners",
        ]:
            db_count = db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            report_count = report["etl_summary"]["row_counts"][table]
            assert db_count == report_count, (
                f"{table}: db={db_count} vs report={report_count}"
            )

    def test_specific_db_values(self, db):
        """Verify specific values in database that would be hard to hardcode."""
        # Glucose observation value
        row = db.execute(
            "SELECT value_number, loinc_code FROM observations WHERE id='obs-glucose-1'"
        ).fetchone()
        assert row["value_number"] == pytest.approx(95.0)
        assert row["loinc_code"] == "1558-6"

        # Organization address
        row = db.execute(
            "SELECT city, state FROM organizations WHERE id='org-1'"
        ).fetchone()
        assert row["city"] == "Anytown"
        assert row["state"] == "CA"

        # All LOINC codes present
        codes = sorted(
            r[0]
            for r in db.execute(
                "SELECT DISTINCT loinc_code FROM observations ORDER BY loinc_code"
            ).fetchall()
        )
        assert codes == ["1558-6", "8310-5", "8480-6", "8867-4"]
