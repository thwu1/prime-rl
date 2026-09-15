"""
Tests for Polyomino Field Inference Pipeline.
Verifies PostgreSQL database, answer correctness, cost budget,
gnuplot visualizations, and report.json.

"""

import os
import sys
import json
import pytest

sys.path.insert(0, "/tests")
from ground_truth import compute_active_cells, NUM_CASES


def get_conn():
    import psycopg2
    return psycopg2.connect(dbname="polyfield", user="postgres")


# ---------------------------------------------------------------
# PostgreSQL database existence and schema
# ---------------------------------------------------------------

def test_pg_database_exists():
    """Database 'polyfield' must exist and be connectable."""
    conn = get_conn()
    conn.close()


def test_sessions_table_schema():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'sessions'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    for expected in ("session_id", "case_id", "n", "m", "epsilon"):
        assert expected in cols, f"sessions table missing column '{expected}'"


def test_queries_table_schema():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'queries'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    for expected in ("session_id", "query_type", "params_json",
                     "result_value", "query_cost", "cumulative_cost"):
        assert expected in cols, f"queries table missing column '{expected}'"


def test_submissions_table_schema():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'submissions'
        ORDER BY ordinal_position
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    for expected in ("session_id", "case_id", "num_cells", "total_cost",
                     "correct", "precision_score", "recall_score", "cells_json"):
        assert expected in cols, f"submissions table missing column '{expected}'"


# ---------------------------------------------------------------
# Sessions logged
# ---------------------------------------------------------------

def test_all_sessions_logged():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT case_id, n, m, epsilon FROM sessions ORDER BY case_id")
    rows = cur.fetchall()
    conn.close()

    case_ids = sorted(r[0] for r in rows)
    assert case_ids == [0, 1, 2, 3, 4], (
        f"Expected sessions for cases 0-4, got {case_ids}"
    )
    for case_id, n, m, eps in rows:
        assert n == 20, f"Case {case_id}: expected N=20, got {n}"
        assert m > 0, f"Case {case_id}: M should be > 0"
        assert 0 < eps < 1, f"Case {case_id}: epsilon out of range"


# ---------------------------------------------------------------
# Queries logged
# ---------------------------------------------------------------

def test_queries_logged_for_all_cases():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.case_id, COUNT(q.id)
        FROM sessions s
        LEFT JOIN queries q ON s.session_id = q.session_id
        GROUP BY s.case_id
        ORDER BY s.case_id
    """)
    rows = cur.fetchall()
    conn.close()
    for case_id, qcount in rows:
        assert qcount > 0, f"No queries logged for case {case_id}"


def test_query_types_valid():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT query_type FROM queries")
    types = {r[0] for r in cur.fetchall()}
    conn.close()
    assert types <= {"drill", "divine"}, f"Invalid query types: {types}"


# ---------------------------------------------------------------
# Submissions — correctness
# ---------------------------------------------------------------

def test_all_cases_submitted_correct():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT case_id, correct FROM submissions ORDER BY case_id")
    rows = cur.fetchall()
    conn.close()

    case_ids = sorted(r[0] for r in rows)
    assert case_ids == [0, 1, 2, 3, 4], (
        f"Expected submissions for cases 0-4, got {case_ids}"
    )
    for case_id, correct in rows:
        assert correct == 1, f"Case {case_id} submission was incorrect"


def test_answers_match_ground_truth():
    """Cross-check submitted cells against independently computed ground truth."""
    conn = get_conn()
    cur = conn.cursor()

    for case_id in range(NUM_CASES):
        truth = compute_active_cells(case_id)

        cur.execute(
            "SELECT cells_json FROM submissions WHERE case_id = %s", (case_id,)
        )
        row = cur.fetchone()
        assert row is not None, f"No submission for case {case_id}"

        cells = json.loads(row[0])
        answer = {(c[0], c[1]) for c in cells}

        missing = truth - answer
        extra = answer - truth
        assert not missing, (
            f"Case {case_id}: missed active cells: {sorted(missing)}"
        )
        assert not extra, (
            f"Case {case_id}: false-positive cells: {sorted(extra)}"
        )

    conn.close()


# ---------------------------------------------------------------
# Cost budget
# ---------------------------------------------------------------

def test_cost_under_budget():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT SUM(total_cost) FROM submissions")
    total = cur.fetchone()[0]
    conn.close()

    assert total is not None, "No submissions found"
    assert total < 1200, f"Total cost {total:.1f} exceeds limit of 1200"


# ---------------------------------------------------------------
# Gnuplot SVG visualizations
# ---------------------------------------------------------------

def test_visualizations_exist():
    for i in range(NUM_CASES):
        path = f"/app/vis/heatmap_{i}.svg"
        assert os.path.isfile(path), f"Missing visualization: {path}"
        with open(path) as f:
            content = f.read()
        assert "<svg" in content.lower(), f"{path} is not valid SVG"
        assert len(content) > 500, (
            f"{path} too small ({len(content)} bytes), appears empty"
        )


# ---------------------------------------------------------------
# report.json
# ---------------------------------------------------------------

def test_report_json_exists():
    assert os.path.isfile("/app/report.json"), "/app/report.json not found"


def test_report_json_structure():
    with open("/app/report.json") as f:
        report = json.load(f)

    assert "cases" in report, "report.json must have 'cases' key"
    assert "total_cost" in report, "report.json must have 'total_cost' key"

    cases = report["cases"]
    assert len(cases) == 5, f"Expected 5 case entries, got {len(cases)}"

    required = {
        "case_id", "session_id", "total_cost",
        "num_queries", "num_active_cells", "correct",
    }
    for c in cases:
        missing = required - set(c.keys())
        assert not missing, f"Case entry missing fields: {missing}"
        assert c["correct"] is True, (
            f"Case {c['case_id']} not correct in report"
        )


def test_report_json_matches_database():
    with open("/app/report.json") as f:
        report = json.load(f)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT SUM(total_cost) FROM submissions")
    db_total = cur.fetchone()[0]
    conn.close()

    assert abs(report["total_cost"] - db_total) < 0.5, (
        f"report.json total_cost ({report['total_cost']:.2f}) "
        f"doesn't match database ({db_total:.2f})"
    )
    assert report["total_cost"] < 1200, (
        f"Report total_cost {report['total_cost']:.1f} >= 1200"
    )
