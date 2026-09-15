
import json
import os
import sqlite3
import pytest

REPORT = "/app/audit_report.json"
DB = "/app/warehouse.db"


def load_report():
    with open(REPORT) as f:
        return json.load(f)


def query_db(sql, params=()):
    conn = sqlite3.connect(DB)
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Audit Report Structure ──────────────────────────────────────────────

class TestAuditReportStructure:
    def test_report_file_exists(self):
        assert os.path.isfile(REPORT), "audit_report.json not found"

    def test_report_is_valid_json(self):
        with open(REPORT) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_report_has_summary(self):
        report = load_report()
        assert "summary" in report, "Report must include a 'summary' object"

    def test_summary_total_at_least_8(self):
        report = load_report()
        summary = report.get("summary", {})
        total = summary.get("total_discrepancies", summary.get("total", 0))
        assert total >= 8, (
            f"Expected at least 8 discrepancies (8 distinct bug categories), "
            f"found {total}"
        )

    def test_report_has_discrepancy_list(self):
        report = load_report()
        discs = report.get("discrepancies", report.get("issues", []))
        assert isinstance(discs, list), "Report must contain a list of discrepancies"
        assert len(discs) >= 8


# ── Discrepancy Discovery ───────────────────────────────────────────────

class TestDiscrepancyDiscovery:
    """Verify the audit report identifies each planted ETL bug."""

    def test_finds_patient_name_discrepancy(self):
        flat = json.dumps(load_report())
        assert "patient-003" in flat, (
            "Audit should identify patient-003 name swap discrepancy"
        )

    def test_finds_missing_observation(self):
        flat = json.dumps(load_report())
        assert "obs-024" in flat, (
            "Audit should identify obs-024 as missing from warehouse"
        )

    def test_finds_phantom_observation(self):
        flat = json.dumps(load_report())
        assert "obs-phantom" in flat, (
            "Audit should identify obs-phantom as a fabricated record"
        )

    def test_finds_wrong_patient_foreign_key(self):
        flat = json.dumps(load_report())
        assert "medreq-004" in flat, (
            "Audit should identify medreq-004 wrong patient link"
        )

    def test_finds_icd_code_corruption(self):
        flat = json.dumps(load_report())
        assert "cond-003" in flat or "cond-007" in flat, (
            "Audit should identify ICD code format corruption"
        )

    def test_finds_unresolved_medication_reference(self):
        flat = json.dumps(load_report())
        assert "medreq-008" in flat, (
            "Audit should identify medreq-008 unresolved medication name"
        )

    def test_finds_encounter_date_truncation(self):
        flat = json.dumps(load_report()).lower()
        has_enc_ref = any(f"enc-{n:03d}" in flat for n in range(1, 9))
        assert has_enc_ref, (
            "Audit should identify encounter date truncation issues"
        )

    def test_finds_component_data_loss(self):
        flat = json.dumps(load_report()).lower()
        assert any(w in flat for w in [
            "component", "blood pressure", "diastolic", "systolic",
            "obs-bp-001", "obs-bp-002", "flattened",
        ]), "Audit should identify component observation data loss"


# ── Warehouse Repairs ────────────────────────────────────────────────────

class TestWarehouseRepair:
    """Verify the warehouse is correctly repaired after reconciliation."""

    def test_patient_003_given_name_fixed(self):
        rows = query_db(
            "SELECT given_name FROM patients WHERE id=?", ("patient-003",)
        )
        assert len(rows) == 1
        assert rows[0][0] == "Robert", (
            f"patient-003 given_name should be 'Robert', got '{rows[0][0]}'"
        )

    def test_patient_003_family_name_fixed(self):
        rows = query_db(
            "SELECT family_name FROM patients WHERE id=?", ("patient-003",)
        )
        assert len(rows) == 1
        assert rows[0][0] == "Johnson", (
            f"patient-003 family_name should be 'Johnson', got '{rows[0][0]}'"
        )

    def test_obs_024_restored(self):
        rows = query_db(
            "SELECT id, loinc_code FROM observations WHERE id=?", ("obs-024",)
        )
        assert len(rows) == 1, "obs-024 should be present after repair"
        assert rows[0][1] == "33914-3", (
            f"obs-024 loinc_code should be '33914-3', got '{rows[0][1]}'"
        )

    def test_obs_phantom_removed(self):
        rows = query_db(
            "SELECT id FROM observations WHERE id=?", ("obs-phantom",)
        )
        assert len(rows) == 0, "obs-phantom should be removed after repair"

    def test_medreq_004_patient_corrected(self):
        rows = query_db(
            "SELECT patient_id FROM medication_requests WHERE id=?",
            ("medreq-004",)
        )
        assert len(rows) == 1
        assert rows[0][0] == "patient-002", (
            f"medreq-004 should reference patient-002, got '{rows[0][0]}'"
        )

    def test_cond_003_icd_code_restored(self):
        rows = query_db(
            "SELECT icd_code FROM conditions WHERE id=?", ("cond-003",)
        )
        assert len(rows) == 1
        assert rows[0][0] == "K35.80", (
            f"cond-003 ICD should be 'K35.80', got '{rows[0][0]}'"
        )

    def test_cond_007_icd_code_restored(self):
        rows = query_db(
            "SELECT icd_code FROM conditions WHERE id=?", ("cond-007",)
        )
        assert len(rows) == 1
        assert rows[0][0] == "N18.6", (
            f"cond-007 ICD should be 'N18.6', got '{rows[0][0]}'"
        )

    def test_medreq_008_medication_name_resolved(self):
        rows = query_db(
            "SELECT medication_name FROM medication_requests WHERE id=?",
            ("medreq-008",)
        )
        assert len(rows) == 1
        assert rows[0][0] == "Heparin Sodium", (
            f"medreq-008 medication_name should be 'Heparin Sodium', "
            f"got '{rows[0][0]}'"
        )

    def test_encounter_dates_have_time_component(self):
        """All encounter period dates must have full ISO datetime after repair."""
        rows = query_db("SELECT id, period_start, period_end FROM encounters")
        for row in rows:
            eid, start, end = row
            assert "T" in start, (
                f"Encounter {eid} period_start still truncated: {start}"
            )
            assert "T" in end, (
                f"Encounter {eid} period_end still truncated: {end}"
            )


# ── Edge Cases & Integrity ──────────────────────────────────────────────

class TestEdgeCases:
    """Verify expert-level judgment: source data issues vs ETL bugs."""

    def test_dangling_ref_observation_preserved(self):
        """obs-dangling references non-existent patient-999 in FHIR source.
        This is a source data characteristic, NOT an ETL bug — must be
        preserved in the warehouse exactly as-is."""
        rows = query_db(
            "SELECT patient_id FROM observations WHERE id=?",
            ("obs-dangling",)
        )
        assert len(rows) == 1, (
            "obs-dangling must be preserved (it exists in FHIR source)"
        )
        assert rows[0][0] == "patient-999", (
            f"obs-dangling patient_id must remain 'patient-999', "
            f"got '{rows[0][0]}'"
        )

    def test_observation_count_matches_fhir_source(self):
        """After repair, warehouse observation count must match FHIR source
        exactly (27 observations including obs-dangling)."""
        rows = query_db("SELECT COUNT(*) FROM observations")
        assert rows[0][0] == 27, (
            f"Warehouse should have 27 observations (matching source), "
            f"got {rows[0][0]}"
        )

    def test_patient_count_unchanged(self):
        rows = query_db("SELECT COUNT(*) FROM patients")
        assert rows[0][0] == 5, (
            f"Should have 5 patients unchanged, got {rows[0][0]}"
        )

    def test_medreq_dangling_medication_stays_null(self):
        """medreq-dangling references non-existent med-999 in source.
        Its medication_name should correctly be NULL (not an ETL bug)."""
        rows = query_db(
            "SELECT medication_name FROM medication_requests WHERE id=?",
            ("medreq-dangling",)
        )
        assert len(rows) == 1
        assert rows[0][0] is None, (
            f"medreq-dangling medication_name should be NULL "
            f"(dangling source ref), got '{rows[0][0]}'"
        )
