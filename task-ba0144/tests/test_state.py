
"""
OMOP CDM Data Quality and Era Derivation Verification Tests

Verifies that all DQD violations have been fixed and era tables correctly derived.
"""

import json
import os
from datetime import date

import psycopg2
import pytest


@pytest.fixture(scope="module")
def db():
    """Connect to the OMOP CDM database."""
    conn = psycopg2.connect(dbname="omop", user="omop", host="localhost")
    conn.autocommit = True
    yield conn
    conn.close()


def query(db, sql):
    """Execute a query and return all results."""
    cur = db.cursor()
    cur.execute(sql)
    return cur.fetchall()


def query_one(db, sql):
    """Execute a query and return a single scalar value."""
    cur = db.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    return row[0] if row else None


# ============================================================
# CONFORMANCE CHECKS
# ============================================================


class TestConformanceRelational:
    """Verify relational integrity constraints are satisfied."""

    def test_no_broken_fk_drug_concept_id(self, db):
        """drug_exposure.drug_concept_id must reference concept.concept_id (or be 0)."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM drug_exposure de
            LEFT JOIN concept c ON de.drug_concept_id = c.concept_id
            WHERE c.concept_id IS NULL AND de.drug_concept_id != 0
        """)
        assert count == 0, f"Found {count} drug_exposure rows with broken FK to concept table"

    def test_no_broken_fk_condition_concept_id(self, db):
        """condition_occurrence.condition_concept_id must reference concept.concept_id."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM condition_occurrence co
            LEFT JOIN concept c ON co.condition_concept_id = c.concept_id
            WHERE c.concept_id IS NULL AND co.condition_concept_id != 0
        """)
        assert count == 0, f"Found {count} condition_occurrence rows with broken FK"

    def test_no_null_observation_period_end_date(self, db):
        """observation_period.observation_period_end_date must not be NULL (CDM spec: NOT NULL)."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM observation_period
            WHERE observation_period_end_date IS NULL
        """)
        assert count == 0, f"Found {count} observation_period rows with NULL end_date"

    def test_no_duplicate_visit_occurrence_id(self, db):
        """visit_occurrence.visit_occurrence_id must be unique (primary key)."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM (
                SELECT visit_occurrence_id
                FROM visit_occurrence
                GROUP BY visit_occurrence_id
                HAVING COUNT(*) > 1
            ) dupes
        """)
        assert count == 0, f"Found {count} duplicate visit_occurrence_id values"


class TestConformanceValue:
    """Verify value conformance constraints."""

    def test_standard_condition_concepts(self, db):
        """condition_occurrence.condition_concept_id must use standard concepts (or 0)."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM condition_occurrence co
            JOIN concept c ON co.condition_concept_id = c.concept_id
            WHERE co.condition_concept_id != 0
              AND (c.standard_concept IS NULL OR c.standard_concept != 'S')
        """)
        assert count == 0, f"Found {count} condition rows with non-standard concept_id"


# ============================================================
# COMPLETENESS CHECKS
# ============================================================


class TestCompleteness:
    """Verify data completeness."""

    def test_all_persons_have_observation_period(self, db):
        """Every person must have at least one observation_period record."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM person p
            LEFT JOIN observation_period op ON p.person_id = op.person_id
            WHERE op.observation_period_id IS NULL
        """)
        assert count == 0, f"Found {count} persons without observation_period"


# ============================================================
# PLAUSIBILITY CHECKS
# ============================================================


class TestPlausibilityTemporal:
    """Verify temporal plausibility."""

    def test_no_conditions_before_birth(self, db):
        """No condition_occurrence should have a start_date before the person's birth."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM condition_occurrence co
            JOIN person p ON co.person_id = p.person_id
            WHERE co.condition_start_date < make_date(p.year_of_birth,
                COALESCE(p.month_of_birth, 1), COALESCE(p.day_of_birth, 1))
        """)
        assert count == 0, f"Found {count} conditions dated before birth"

    def test_no_measurements_after_death(self, db):
        """No measurement should have a date after the person's death_date."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM measurement m
            JOIN death d ON m.person_id = d.person_id
            WHERE m.measurement_date > d.death_date
        """)
        assert count == 0, f"Found {count} measurements dated after death"

    def test_no_drug_exposure_start_after_end(self, db):
        """drug_exposure_start_date must be <= drug_exposure_end_date."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM drug_exposure
            WHERE drug_exposure_start_date > drug_exposure_end_date
        """)
        assert count == 0, f"Found {count} drug_exposure rows with start > end"


class TestPlausibilityAtemporal:
    """Verify atemporal plausibility."""

    def test_no_negative_bmi(self, db):
        """BMI measurements (concept_id=3038553) must not have negative values."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM measurement
            WHERE measurement_concept_id = 3038553
              AND value_as_number IS NOT NULL
              AND value_as_number < 0
        """)
        assert count == 0, f"Found {count} BMI measurements with negative values"


# ============================================================
# DRUG ERA DERIVATION CHECKS
# ============================================================


class TestDrugEra:
    """Verify drug_era table is correctly derived."""

    def test_drug_era_table_not_empty(self, db):
        """drug_era table must contain records."""
        count = query_one(db, "SELECT COUNT(*) FROM drug_era")
        assert count is not None and count > 0, "drug_era table is empty"

    def test_drug_era_total_count(self, db):
        """drug_era should have exactly 9 records after correct derivation."""
        count = query_one(db, "SELECT COUNT(*) FROM drug_era")
        assert count == 9, f"Expected 9 drug_era records, found {count}"

    def test_drug_era_uses_ingredient_concepts(self, db):
        """All drug_concept_id values in drug_era must be Ingredient concepts."""
        non_ingredient = query_one(db, """
            SELECT COUNT(*)
            FROM drug_era de
            JOIN concept c ON de.drug_concept_id = c.concept_id
            WHERE c.concept_class_id != 'Ingredient'
        """)
        assert non_ingredient == 0, \
            f"Found {non_ingredient} drug_era rows with non-Ingredient concept"

    def test_drug_era_person1_lisinopril_era1(self, db):
        """Person 1 should have a lisinopril era from 2022-03-15 to 2022-12-31
        (two exposures merged with 15 gap days)."""
        rows = query(db, """
            SELECT drug_era_start_date, drug_era_end_date,
                   drug_exposure_count, gap_days
            FROM drug_era
            WHERE person_id = 1 AND drug_concept_id = 1335471
            ORDER BY drug_era_start_date
        """)
        assert len(rows) == 2, \
            f"Expected 2 lisinopril eras for person 1, found {len(rows)}"

        era1 = rows[0]
        assert era1[0] == date(2022, 3, 15), \
            f"Era 1 start: expected 2022-03-15, got {era1[0]}"
        assert era1[1] == date(2022, 12, 31), \
            f"Era 1 end: expected 2022-12-31, got {era1[1]}"
        assert era1[2] == 2, \
            f"Era 1 exposure count: expected 2, got {era1[2]}"
        assert era1[3] == 15, \
            f"Era 1 gap_days: expected 15, got {era1[3]}"

    def test_drug_era_person1_lisinopril_era2(self, db):
        """Person 1 should have a second lisinopril era from 2023-02-01 to 2023-08-01
        (single exposure, gap from previous era > 30 days)."""
        rows = query(db, """
            SELECT drug_era_start_date, drug_era_end_date,
                   drug_exposure_count, gap_days
            FROM drug_era
            WHERE person_id = 1 AND drug_concept_id = 1335471
            ORDER BY drug_era_start_date
        """)
        assert len(rows) >= 2, "Expected at least 2 lisinopril eras for person 1"
        era2 = rows[1]
        assert era2[0] == date(2023, 2, 1), \
            f"Era 2 start: expected 2023-02-01, got {era2[0]}"
        assert era2[1] == date(2023, 8, 1), \
            f"Era 2 end: expected 2023-08-01, got {era2[1]}"
        assert era2[2] == 1, \
            f"Era 2 exposure count: expected 1, got {era2[2]}"
        assert era2[3] == 0, \
            f"Era 2 gap_days: expected 0, got {era2[3]}"

    def test_drug_era_person1_metformin(self, db):
        """Person 1 should have one metformin era (two exposures merged)."""
        rows = query(db, """
            SELECT drug_era_start_date, drug_era_end_date,
                   drug_exposure_count, gap_days
            FROM drug_era
            WHERE person_id = 1 AND drug_concept_id = 1503297
        """)
        assert len(rows) == 1, \
            f"Expected 1 metformin era for person 1, found {len(rows)}"
        era = rows[0]
        assert era[0] == date(2022, 3, 15), \
            f"Start: expected 2022-03-15, got {era[0]}"
        assert era[1] == date(2023, 3, 31), \
            f"End: expected 2023-03-31, got {era[1]}"
        assert era[2] == 2, f"Exposure count: expected 2, got {era[2]}"
        assert era[3] == 15, f"Gap days: expected 15, got {era[3]}"

    def test_drug_era_person9_lisinopril_corrected_dates(self, db):
        """Person 9's lisinopril era should reflect corrected (swapped) dates."""
        rows = query(db, """
            SELECT drug_era_start_date, drug_era_end_date
            FROM drug_era
            WHERE person_id = 9 AND drug_concept_id = 1335471
        """)
        assert len(rows) == 1, \
            f"Expected 1 lisinopril era for person 9, found {len(rows)}"
        assert rows[0][0] == date(2022, 6, 1), \
            f"Start: expected 2022-06-01, got {rows[0][0]}"
        assert rows[0][1] == date(2022, 10, 1), \
            f"End: expected 2022-10-01, got {rows[0][1]}"

    def test_no_drug_era_for_unmapped_drugs(self, db):
        """Drug exposures with drug_concept_id=0 should NOT produce drug_era records
        (no ingredient ancestor for concept 0)."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM drug_era
            WHERE drug_concept_id = 0
        """)
        assert count == 0, f"Found {count} drug_era rows with concept_id=0"


# ============================================================
# CONDITION ERA DERIVATION CHECKS
# ============================================================


class TestConditionEra:
    """Verify condition_era table is correctly derived."""

    def test_condition_era_table_not_empty(self, db):
        """condition_era table must contain records."""
        count = query_one(db, "SELECT COUNT(*) FROM condition_era")
        assert count is not None and count > 0, "condition_era table is empty"

    def test_condition_era_total_count(self, db):
        """condition_era should have exactly 11 records after correct derivation."""
        count = query_one(db, "SELECT COUNT(*) FROM condition_era")
        assert count == 11, f"Expected 11 condition_era records, found {count}"

    def test_condition_era_uses_standard_concepts(self, db):
        """All condition_concept_id in condition_era must be standard concepts."""
        non_standard = query_one(db, """
            SELECT COUNT(*)
            FROM condition_era ce
            JOIN concept c ON ce.condition_concept_id = c.concept_id
            WHERE c.standard_concept IS NULL OR c.standard_concept != 'S'
        """)
        assert non_standard == 0, \
            f"Found {non_standard} condition_era rows with non-standard concept"

    def test_condition_era_person3_mi(self, db):
        """Person 3 should have an MI era from 2022-05-01 to 2022-05-05."""
        rows = query(db, """
            SELECT condition_era_start_date, condition_era_end_date,
                   condition_occurrence_count
            FROM condition_era
            WHERE person_id = 3 AND condition_concept_id = 312327
        """)
        assert len(rows) == 1, f"Expected 1 MI era for person 3, found {len(rows)}"
        assert rows[0][0] == date(2022, 5, 1), \
            f"Start: expected 2022-05-01, got {rows[0][0]}"
        assert rows[0][1] == date(2022, 5, 5), \
            f"End: expected 2022-05-05, got {rows[0][1]}"

    def test_condition_era_no_implausible_before_birth(self, db):
        """No condition_era should have dates before the person's birth."""
        count = query_one(db, """
            SELECT COUNT(*)
            FROM condition_era ce
            JOIN person p ON ce.person_id = p.person_id
            WHERE ce.condition_era_start_date < make_date(p.year_of_birth,
                COALESCE(p.month_of_birth, 1), COALESCE(p.day_of_birth, 1))
        """)
        assert count == 0, f"Found {count} condition_era records before birth"

    def test_condition_era_person4_diabetes_fixed(self, db):
        """Person 4 should have a diabetes (201826) era after non-standard concept fix."""
        rows = query(db, """
            SELECT condition_concept_id
            FROM condition_era
            WHERE person_id = 4
        """)
        concept_ids = [r[0] for r in rows]
        assert 201826 in concept_ids, \
            "Person 4 should have condition_era with standard diabetes concept 201826"
        assert 44831230 not in concept_ids, \
            "Person 4 should NOT have condition_era with non-standard ICD10CM concept"


# ============================================================
# DQD REPORT CHECK
# ============================================================


class TestDQDReport:
    """Verify the DQD report file exists and has valid structure."""

    def test_report_file_exists(self, db):
        """DQD report must exist at /app/dqd_report.json."""
        assert os.path.isfile("/app/dqd_report.json"), \
            "DQD report not found at /app/dqd_report.json"

    def test_report_valid_json(self, db):
        """DQD report must be valid JSON."""
        with open("/app/dqd_report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "DQD report root must be a JSON object"

    def test_report_has_violations(self, db):
        """DQD report must list at least 8 violations found."""
        with open("/app/dqd_report.json") as f:
            data = json.load(f)
        # Accept either "checks" or "violations" as the key name
        items = data.get("checks") or data.get("violations") or []
        assert len(items) >= 8, \
            f"Expected at least 8 violations in DQD report, found {len(items)}"
