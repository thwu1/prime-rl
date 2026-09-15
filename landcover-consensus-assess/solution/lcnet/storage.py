"""Result persistence in SQLite."""

import sqlite3
import json
import datetime


def init_db(db_path):
    """Initialize the results database with assessment and score tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS assessments (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            level INTEGER NOT NULL,
            overall_accuracy REAL,
            cohens_kappa REAL,
            per_class_json TEXT,
            confusion_matrix_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            valid INTEGER,
            score REAL,
            errors_json TEXT
        )
    """)
    conn.commit()
    conn.close()


def store_assessment(result, level, db_path):
    """Store an assessment result in the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO assessments (timestamp, level, overall_accuracy, cohens_kappa, "
        "per_class_json, confusion_matrix_json) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.datetime.now().isoformat(), level,
         result["overall_accuracy"], result["cohens_kappa"],
         json.dumps(result["per_class"]),
         json.dumps(result["confusion_matrix"]))
    )
    conn.commit()
    conn.close()


def store_score(result, db_path):
    """Store a scoring result in the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scores (timestamp, valid, score, errors_json) VALUES (?, ?, ?, ?)",
        (datetime.datetime.now().isoformat(),
         1 if result.get("valid") else 0,
         result.get("score", 0.0),
         json.dumps(result.get("errors", [])))
    )
    conn.commit()
    conn.close()


def get_summary(db_path):
    """Get a summary of all results in the database."""
    conn = sqlite3.connect(db_path)

    cursor = conn.execute("""
        SELECT level, COUNT(*) as cnt, AVG(overall_accuracy) as avg_oa,
               AVG(cohens_kappa) as avg_kappa
        FROM assessments
        GROUP BY level
        ORDER BY level
    """)
    rows = cursor.fetchall()

    summary = {"assessment_runs": 0, "by_level": {}}
    for row in rows:
        lvl = str(row[0])
        summary["by_level"][lvl] = {
            "count": row[1],
            "mean_accuracy": row[2],
            "mean_kappa": row[3]
        }
        summary["assessment_runs"] += row[1]

    cursor = conn.execute("SELECT COUNT(*), AVG(score) FROM scores WHERE valid = 1")
    score_row = cursor.fetchone()
    summary["score_runs"] = score_row[0]
    summary["mean_score"] = score_row[1] if score_row[1] is not None else 0.0

    conn.close()
    return summary
