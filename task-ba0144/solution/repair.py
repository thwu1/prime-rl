#!/usr/bin/env python3

"""
OMOP CDM Data Quality Repair Pipeline

Identifies and fixes DQD violations in clinical tables, then derives
drug_era and condition_era tables following OMOP conventions.
"""

import json
from datetime import date

import psycopg2

DB_PARAMS = dict(dbname="omop", user="omop", host="localhost")
REPORT_PATH = "/app/dqd_report.json"


def get_conn():
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    return conn


def run(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def fetch(conn, sql, params=None):
    cur = run(conn, sql, params)
    return cur.fetchall()


def fetch_one(conn, sql, params=None):
    rows = fetch(conn, sql, params)
    return rows[0][0] if rows else None


# ============================================================
# Bug detection and repair functions
# ============================================================

def fix_broken_fk_drug_concept(conn):
    """Bug 1: drug_exposure references drug_concept_id not in concept table."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM drug_exposure de
        LEFT JOIN concept c ON de.drug_concept_id = c.concept_id
        WHERE c.concept_id IS NULL AND de.drug_concept_id != 0
    """)
    if count and count > 0:
        run(conn, """
            UPDATE drug_exposure
            SET drug_concept_id = 0
            WHERE drug_concept_id NOT IN (SELECT concept_id FROM concept)
              AND drug_concept_id != 0
        """)
    return {
        "check_name": "isForeignKey",
        "category": "Conformance",
        "table_name": "drug_exposure",
        "field_name": "drug_concept_id",
        "num_violated_rows": count or 0,
        "description": "drug_concept_id references concept_id not present in concept table",
        "fix_applied": "Set invalid drug_concept_id to 0 (No matching concept)"
    }


def fix_null_observation_period_end(conn):
    """Bug 2: observation_period.observation_period_end_date is NULL."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM observation_period
        WHERE observation_period_end_date IS NULL
    """)
    if count and count > 0:
        # Set end_date to the latest clinical event date for that person,
        # or the start_date if no events found
        run(conn, """
            UPDATE observation_period op
            SET observation_period_end_date = COALESCE(
                (SELECT MAX(event_date) FROM (
                    SELECT condition_start_date AS event_date FROM condition_occurrence WHERE person_id = op.person_id
                    UNION ALL
                    SELECT drug_exposure_end_date FROM drug_exposure WHERE person_id = op.person_id AND drug_exposure_end_date IS NOT NULL
                    UNION ALL
                    SELECT measurement_date FROM measurement WHERE person_id = op.person_id
                    UNION ALL
                    SELECT visit_end_date FROM visit_occurrence WHERE person_id = op.person_id
                ) events),
                op.observation_period_start_date
            )
            WHERE op.observation_period_end_date IS NULL
        """)
    return {
        "check_name": "isRequired",
        "category": "Conformance",
        "table_name": "observation_period",
        "field_name": "observation_period_end_date",
        "num_violated_rows": count or 0,
        "description": "observation_period_end_date is NULL (CDM spec requires NOT NULL)",
        "fix_applied": "Set to latest clinical event date for the person"
    }


def fix_non_standard_condition_concept(conn):
    """Bug 3: condition_occurrence uses non-standard concept_id."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM condition_occurrence co
        JOIN concept c ON co.condition_concept_id = c.concept_id
        WHERE co.condition_concept_id != 0
          AND (c.standard_concept IS NULL OR c.standard_concept != 'S')
    """)
    if count and count > 0:
        # Map non-standard concepts to standard via concept_relationship 'Maps to'
        run(conn, """
            UPDATE condition_occurrence co
            SET condition_source_concept_id = co.condition_concept_id,
                condition_concept_id = cr.concept_id_2
            FROM concept c
            JOIN concept_relationship cr ON c.concept_id = cr.concept_id_1
                AND cr.relationship_id = 'Maps to'
                AND cr.invalid_reason IS NULL
            WHERE co.condition_concept_id = c.concept_id
              AND co.condition_concept_id != 0
              AND (c.standard_concept IS NULL OR c.standard_concept != 'S')
        """)
    return {
        "check_name": "isStandardValidConcept",
        "category": "Conformance",
        "table_name": "condition_occurrence",
        "field_name": "condition_concept_id",
        "num_violated_rows": count or 0,
        "description": "Non-standard concept used in condition_concept_id (ICD10CM instead of SNOMED)",
        "fix_applied": "Mapped to standard concept via concept_relationship 'Maps to'; original stored in condition_source_concept_id"
    }


def fix_duplicate_visit_occurrence_id(conn):
    """Bug 4: duplicate visit_occurrence_id values."""
    dupes = fetch(conn, """
        SELECT visit_occurrence_id, COUNT(*)
        FROM visit_occurrence
        GROUP BY visit_occurrence_id
        HAVING COUNT(*) > 1
    """)
    total_dupes = len(dupes)
    if total_dupes > 0:
        max_id = fetch_one(conn, "SELECT MAX(visit_occurrence_id) FROM visit_occurrence")
        new_id = max_id + 1
        for dup_id, cnt in dupes:
            # Get CTIDs of duplicate rows
            ctids = fetch(conn, """
                SELECT ctid FROM visit_occurrence
                WHERE visit_occurrence_id = %s
                ORDER BY ctid
            """, (dup_id,))
            # Reassign all but the first occurrence
            for i, (ctid,) in enumerate(ctids[1:], start=1):
                run(conn, """
                    UPDATE visit_occurrence
                    SET visit_occurrence_id = %s
                    WHERE ctid = %s
                """, (new_id, ctid))
                new_id += 1
    return {
        "check_name": "isPrimaryKey",
        "category": "Conformance",
        "table_name": "visit_occurrence",
        "field_name": "visit_occurrence_id",
        "num_violated_rows": total_dupes,
        "description": "Duplicate visit_occurrence_id values violate primary key uniqueness",
        "fix_applied": "Assigned new unique visit_occurrence_id to duplicate rows"
    }


def fix_missing_observation_period(conn):
    """Bug 5: person without observation_period."""
    missing = fetch(conn, """
        SELECT p.person_id
        FROM person p
        LEFT JOIN observation_period op ON p.person_id = op.person_id
        WHERE op.observation_period_id IS NULL
    """)
    count = len(missing)
    if count > 0:
        max_op_id = fetch_one(conn, "SELECT COALESCE(MAX(observation_period_id), 0) FROM observation_period")
        next_id = max_op_id + 1
        for (pid,) in missing:
            # Derive observation period from clinical events
            dates = fetch(conn, """
                SELECT MIN(event_date), MAX(event_date) FROM (
                    SELECT condition_start_date AS event_date FROM condition_occurrence WHERE person_id = %s
                    UNION ALL
                    SELECT drug_exposure_start_date FROM drug_exposure WHERE person_id = %s
                    UNION ALL
                    SELECT drug_exposure_end_date FROM drug_exposure WHERE person_id = %s AND drug_exposure_end_date IS NOT NULL
                    UNION ALL
                    SELECT measurement_date FROM measurement WHERE person_id = %s
                    UNION ALL
                    SELECT visit_start_date FROM visit_occurrence WHERE person_id = %s
                    UNION ALL
                    SELECT visit_end_date FROM visit_occurrence WHERE person_id = %s
                ) events
            """, (pid, pid, pid, pid, pid, pid))
            if dates and dates[0][0]:
                min_date, max_date = dates[0]
                run(conn, """
                    INSERT INTO observation_period
                    (observation_period_id, person_id, observation_period_start_date,
                     observation_period_end_date, period_type_concept_id)
                    VALUES (%s, %s, %s, %s, 32817)
                """, (next_id, pid, min_date, max_date))
                next_id += 1
    return {
        "check_name": "measurePersonCompleteness",
        "category": "Completeness",
        "table_name": "observation_period",
        "field_name": "person_id",
        "num_violated_rows": count,
        "description": "Person(s) exist without any observation_period record",
        "fix_applied": "Created observation_period from min/max clinical event dates"
    }


def fix_events_before_birth(conn):
    """Bug 6: clinical events dated before person's birth."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM condition_occurrence co
        JOIN person p ON co.person_id = p.person_id
        WHERE co.condition_start_date < make_date(p.year_of_birth,
            COALESCE(p.month_of_birth, 1), COALESCE(p.day_of_birth, 1))
    """)
    if count and count > 0:
        run(conn, """
            DELETE FROM condition_occurrence
            WHERE condition_occurrence_id IN (
                SELECT co.condition_occurrence_id
                FROM condition_occurrence co
                JOIN person p ON co.person_id = p.person_id
                WHERE co.condition_start_date < make_date(p.year_of_birth,
                    COALESCE(p.month_of_birth, 1), COALESCE(p.day_of_birth, 1))
            )
        """)
    return {
        "check_name": "plausibleAfterBirth",
        "category": "Plausibility",
        "table_name": "condition_occurrence",
        "field_name": "condition_start_date",
        "num_violated_rows": count or 0,
        "description": "Condition start_date is before the person's date of birth",
        "fix_applied": "Deleted implausible records with dates before birth"
    }


def fix_events_after_death(conn):
    """Bug 7: measurements dated after person's death."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM measurement m
        JOIN death d ON m.person_id = d.person_id
        WHERE m.measurement_date > d.death_date
    """)
    if count and count > 0:
        run(conn, """
            DELETE FROM measurement
            WHERE measurement_id IN (
                SELECT m.measurement_id
                FROM measurement m
                JOIN death d ON m.person_id = d.person_id
                WHERE m.measurement_date > d.death_date
            )
        """)
    return {
        "check_name": "plausibleDuringLife",
        "category": "Plausibility",
        "table_name": "measurement",
        "field_name": "measurement_date",
        "num_violated_rows": count or 0,
        "description": "Measurement date occurs after the person's death date",
        "fix_applied": "Deleted implausible records with dates after death"
    }


def fix_drug_start_after_end(conn):
    """Bug 8: drug_exposure with start_date > end_date."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM drug_exposure
        WHERE drug_exposure_start_date > drug_exposure_end_date
    """)
    if count and count > 0:
        run(conn, """
            UPDATE drug_exposure
            SET drug_exposure_start_date = drug_exposure_end_date,
                drug_exposure_end_date = drug_exposure_start_date
            WHERE drug_exposure_start_date > drug_exposure_end_date
        """)
    return {
        "check_name": "plausibleStartBeforeEnd",
        "category": "Plausibility",
        "table_name": "drug_exposure",
        "field_name": "drug_exposure_start_date",
        "num_violated_rows": count or 0,
        "description": "drug_exposure_start_date is after drug_exposure_end_date",
        "fix_applied": "Swapped start_date and end_date"
    }


def fix_implausible_measurement_values(conn):
    """Bug 9: physically impossible measurement values (e.g., negative BMI)."""
    count = fetch_one(conn, """
        SELECT COUNT(*) FROM measurement
        WHERE measurement_concept_id = 3038553
          AND value_as_number IS NOT NULL AND value_as_number < 0
    """)
    if count and count > 0:
        run(conn, """
            UPDATE measurement
            SET value_as_number = ABS(value_as_number)
            WHERE measurement_concept_id = 3038553
              AND value_as_number IS NOT NULL AND value_as_number < 0
        """)
    return {
        "check_name": "plausibleValueLow",
        "category": "Plausibility",
        "table_name": "measurement",
        "field_name": "value_as_number",
        "num_violated_rows": count or 0,
        "description": "BMI measurement has negative value (physically impossible)",
        "fix_applied": "Corrected to absolute value (assumed sign error)"
    }


# ============================================================
# Era derivation
# ============================================================

def build_drug_era(conn):
    """Derive drug_era table from drug_exposure using OMOP conventions.

    Algorithm:
    1. Map each drug_exposure to its ingredient(s) via concept_ancestor
    2. For each (person_id, ingredient_concept_id), sort exposures by start_date
    3. Merge exposures with gap <= 30 uncovered days
    4. Compute drug_era_start_date, drug_era_end_date, drug_exposure_count, gap_days
    """
    # Clear existing data
    run(conn, "DELETE FROM drug_era")

    # Get all valid drug exposures mapped to ingredients
    exposures = fetch(conn, """
        SELECT de.person_id,
               ca.ancestor_concept_id AS ingredient_concept_id,
               de.drug_exposure_start_date,
               de.drug_exposure_end_date
        FROM drug_exposure de
        JOIN concept_ancestor ca ON de.drug_concept_id = ca.descendant_concept_id
        JOIN concept c ON ca.ancestor_concept_id = c.concept_id
        WHERE c.concept_class_id = 'Ingredient'
          AND de.drug_concept_id != 0
          AND de.drug_exposure_start_date IS NOT NULL
          AND de.drug_exposure_end_date IS NOT NULL
        ORDER BY de.person_id, ca.ancestor_concept_id, de.drug_exposure_start_date
    """)

    # Group by (person_id, ingredient)
    groups = {}
    for person_id, ingredient_id, start_dt, end_dt in exposures:
        key = (person_id, ingredient_id)
        groups.setdefault(key, []).append((start_dt, end_dt))

    era_id = 1
    for (person_id, ingredient_id), exps in sorted(groups.items()):
        exps.sort(key=lambda x: x[0])

        # Build eras using 30-day persistence window
        eras = []
        era_start = exps[0][0]
        era_end = exps[0][1]
        exp_count = 1
        gap_days_total = 0

        for i in range(1, len(exps)):
            curr_start, curr_end = exps[i]
            # Gap = uncovered days between previous era_end and current start
            gap = (curr_start - era_end).days - 1
            if gap <= 30:
                # Merge into current era
                if gap > 0:
                    gap_days_total += gap
                era_end = max(era_end, curr_end)
                exp_count += 1
            else:
                # Save current era and start new one
                eras.append((era_start, era_end, exp_count, gap_days_total))
                era_start = curr_start
                era_end = curr_end
                exp_count = 1
                gap_days_total = 0

        # Save last era
        eras.append((era_start, era_end, exp_count, gap_days_total))

        # Insert eras
        for era_start_dt, era_end_dt, count, gaps in eras:
            run(conn, """
                INSERT INTO drug_era
                (drug_era_id, person_id, drug_concept_id,
                 drug_era_start_date, drug_era_end_date,
                 drug_exposure_count, gap_days)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (era_id, person_id, ingredient_id,
                  era_start_dt, era_end_dt, count, gaps))
            era_id += 1


def build_condition_era(conn):
    """Derive condition_era table from condition_occurrence using OMOP conventions.

    Algorithm:
    1. For each (person_id, condition_concept_id), sort occurrences by start_date
    2. Use COALESCE(condition_end_date, condition_start_date) as effective end date
    3. Merge occurrences with gap <= 30 days
    4. Compute condition_era_start_date, condition_era_end_date, condition_occurrence_count
    """
    run(conn, "DELETE FROM condition_era")

    occurrences = fetch(conn, """
        SELECT person_id,
               condition_concept_id,
               condition_start_date,
               COALESCE(condition_end_date, condition_start_date) AS condition_end_date
        FROM condition_occurrence
        WHERE condition_concept_id != 0
        ORDER BY person_id, condition_concept_id, condition_start_date
    """)

    groups = {}
    for person_id, concept_id, start_dt, end_dt in occurrences:
        key = (person_id, concept_id)
        groups.setdefault(key, []).append((start_dt, end_dt))

    era_id = 1
    for (person_id, concept_id), occs in sorted(groups.items()):
        occs.sort(key=lambda x: x[0])

        eras = []
        era_start = occs[0][0]
        era_end = occs[0][1]
        occ_count = 1

        for i in range(1, len(occs)):
            curr_start, curr_end = occs[i]
            gap = (curr_start - era_end).days - 1
            if gap <= 30:
                era_end = max(era_end, curr_end)
                occ_count += 1
            else:
                eras.append((era_start, era_end, occ_count))
                era_start = curr_start
                era_end = curr_end
                occ_count = 1

        eras.append((era_start, era_end, occ_count))

        for era_start_dt, era_end_dt, count in eras:
            run(conn, """
                INSERT INTO condition_era
                (condition_era_id, person_id, condition_concept_id,
                 condition_era_start_date, condition_era_end_date,
                 condition_occurrence_count)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (era_id, person_id, concept_id,
                  era_start_dt, era_end_dt, count))
            era_id += 1


# ============================================================
# Main pipeline
# ============================================================

def main():
    conn = get_conn()
    violations = []

    print("=== OMOP CDM Data Quality Repair Pipeline ===\n")

    # Phase 1: Identify and fix all violations
    print("Phase 1: Identifying and fixing data quality violations...\n")

    fixes = [
        ("Bug 1: Broken FK in drug_exposure", fix_broken_fk_drug_concept),
        ("Bug 2: NULL observation_period end_date", fix_null_observation_period_end),
        ("Bug 3: Non-standard condition concept", fix_non_standard_condition_concept),
        ("Bug 4: Duplicate visit_occurrence_id", fix_duplicate_visit_occurrence_id),
        ("Bug 5: Missing observation_period", fix_missing_observation_period),
        ("Bug 6: Condition before birth", fix_events_before_birth),
        ("Bug 7: Measurement after death", fix_events_after_death),
        ("Bug 8: Drug exposure start > end", fix_drug_start_after_end),
        ("Bug 9: Implausible measurement value", fix_implausible_measurement_values),
    ]

    for name, fix_fn in fixes:
        print(f"  Checking: {name}")
        result = fix_fn(conn)
        violations.append(result)
        n = result["num_violated_rows"]
        if n > 0:
            print(f"    FOUND {n} violation(s) -> {result['fix_applied']}")
        else:
            print(f"    OK (no violations)")

    # Phase 2: Derive era tables
    print("\nPhase 2: Deriving era tables...\n")

    print("  Building drug_era table...")
    build_drug_era(conn)
    drug_era_count = fetch_one(conn, "SELECT COUNT(*) FROM drug_era")
    print(f"    Created {drug_era_count} drug_era records")

    print("  Building condition_era table...")
    build_condition_era(conn)
    cond_era_count = fetch_one(conn, "SELECT COUNT(*) FROM condition_era")
    print(f"    Created {cond_era_count} condition_era records")

    # Phase 3: Write DQD report
    print("\nPhase 3: Writing DQD report...\n")

    report = {
        "checks": violations,
        "total_violations_found": sum(1 for v in violations if v["num_violated_rows"] > 0),
        "total_violations_fixed": sum(1 for v in violations if v["num_violated_rows"] > 0),
        "drug_era_count": drug_era_count,
        "condition_era_count": cond_era_count,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"  Report written to {REPORT_PATH}")
    print(f"  Total violations found and fixed: {report['total_violations_found']}")
    print("\n=== Pipeline complete ===")

    conn.close()


if __name__ == "__main__":
    main()
