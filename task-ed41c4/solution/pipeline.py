#!/usr/bin/env python3
"""FHIR R4 ETL analytics pipeline — loads NDJSON into SQLite, runs analytics,
generates report."""

import json
import os
import sqlite3

DB_PATH = "/app/analytics.db"
INTERMEDIATE_DIR = "/app/intermediate"
SCHEMAS_FILE = "/app/table_schemas.sql"
THRESHOLDS_FILE = "/app/thresholds.json"
OUTPUT_PATH = "/app/output/report.json"

TABLES = [
    "patients",
    "organizations",
    "practitioners",
    "observations",
    "medication_requests",
    "conditions",
]


def load_ndjson(filepath):
    rows = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    with open(SCHEMAS_FILE) as f:
        conn.executescript(f.read())
    return conn


def insert_rows(conn, table, rows):
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(columns)
    for row in rows:
        values = [row.get(c) for c in columns]
        conn.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values
        )
    conn.commit()


def run_analytics(conn):
    analytics = {}

    # 1. Observations per patient
    rows = conn.execute(
        """
        SELECT p.id AS patient_id, p.family_name, COUNT(o.id) AS obs_count
        FROM patients p
        LEFT JOIN observations o ON o.subject_ref = 'Patient/' || p.id
        GROUP BY p.id
        ORDER BY obs_count DESC, p.id ASC
        """
    ).fetchall()
    analytics["observations_per_patient"] = [
        {"patient_id": r["patient_id"], "family_name": r["family_name"],
         "obs_count": r["obs_count"]}
        for r in rows
    ]

    # 2. Patients with both active condition and active medication
    rows = conn.execute(
        """
        SELECT DISTINCT p.id
        FROM patients p
        JOIN conditions c
          ON c.subject_ref = 'Patient/' || p.id
          AND c.clinical_status = 'active'
        JOIN medication_requests m
          ON m.subject_ref = 'Patient/' || p.id
          AND m.status = 'active'
        ORDER BY p.id
        """
    ).fetchall()
    analytics["active_condition_and_med_patients"] = [r["id"] for r in rows]

    # 3. Average observation value by LOINC code
    rows = conn.execute(
        """
        SELECT loinc_code, ROUND(AVG(value_number), 1) AS avg_value
        FROM observations
        WHERE value_number IS NOT NULL
        GROUP BY loinc_code
        ORDER BY loinc_code
        """
    ).fetchall()
    analytics["avg_value_by_loinc"] = [
        {"loinc_code": r["loinc_code"], "avg_value": r["avg_value"]}
        for r in rows
    ]

    # 4. Vital signs count
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM observations WHERE category_code = 'vital-signs'"
    ).fetchone()
    analytics["vital_signs_count"] = row["cnt"]

    # 5. Medication status summary
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM medication_requests
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()
    analytics["med_status_summary"] = [
        {"status": r["status"], "count": r["count"]} for r in rows
    ]

    # 6. Patients missing managing organization
    rows = conn.execute(
        """
        SELECT id FROM patients
        WHERE managing_org_ref IS NULL
        ORDER BY id
        """
    ).fetchall()
    analytics["patients_missing_managing_org"] = [r["id"] for r in rows]

    # 7. Observation date range
    row = conn.execute(
        "SELECT MIN(effective_date) AS earliest, MAX(effective_date) AS latest FROM observations"
    ).fetchone()
    analytics["date_range"] = {
        "earliest": row["earliest"],
        "latest": row["latest"],
    }

    # 8. Flagged observations exceeding clinical thresholds
    with open(THRESHOLDS_FILE) as f:
        thresholds = json.load(f)

    rows = conn.execute(
        """
        SELECT id, loinc_code, value_number
        FROM observations
        WHERE value_number IS NOT NULL
        ORDER BY id
        """
    ).fetchall()

    flagged = []
    for r in rows:
        loinc = r["loinc_code"]
        value = r["value_number"]
        if loinc in thresholds and value > thresholds[loinc]["high"]:
            flagged.append({
                "id": r["id"],
                "loinc_code": loinc,
                "value": value,
                "threshold": thresholds[loinc]["high"],
                "flag": "HIGH",
            })
    analytics["flagged_observations"] = sorted(flagged, key=lambda x: x["id"])

    return analytics


def main():
    conn = create_db()

    row_counts = {}
    for table in TABLES:
        filepath = os.path.join(INTERMEDIATE_DIR, f"{table}.ndjson")
        rows = load_ndjson(filepath)
        insert_rows(conn, table, rows)
        row_counts[table] = len(rows)

    analytics = run_analytics(conn)
    conn.close()

    report = {
        "etl_summary": {
            "total_resources": sum(row_counts.values()),
            "tables_created": sorted(TABLES),
            "row_counts": row_counts,
        },
        "analytics": analytics,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2, sort_keys=False)

    print(f"Report written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
