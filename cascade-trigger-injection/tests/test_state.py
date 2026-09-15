import pytest
import os
import subprocess
import time


import psycopg2


@pytest.fixture(scope="session")
def db():
    """Return a connection to the appdb database."""
    pg_ver = sorted(os.listdir("/etc/postgresql"))[-1]
    subprocess.run(["pg_ctlcluster", pg_ver, "main", "start"],
                   capture_output=True, timeout=30)
    time.sleep(2)
    conn = None
    for attempt in range(10):
        try:
            conn = psycopg2.connect(dbname="appdb", user="postgres",
                                    host="localhost")
            conn.autocommit = True
            break
        except psycopg2.OperationalError:
            time.sleep(1)
    if conn is None:
        raise RuntimeError("Could not connect to PostgreSQL after 10 attempts")
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def reset_data(db):
    """Reset all tables to known state before each test."""
    cur = db.cursor()
    cur.execute("SET session_replication_role = 'replica'")
    cur.execute("DELETE FROM _cascade_log")
    cur.execute("DELETE FROM tasks")
    cur.execute("DELETE FROM projects")
    cur.execute("DELETE FROM departments")
    cur.execute("SET session_replication_role = 'origin'")

    cur.execute("""INSERT INTO departments (id, name, region, division) VALUES
        (1, 'Engineering', 'US-West', 'Technology'),
        (2, 'Marketing', 'US-East', 'Business'),
        (3, 'Executive', NULL, 'Leadership')""")
    cur.execute("SELECT setval('departments_id_seq', 3)")

    cur.execute("""INSERT INTO projects (id, dept_name, dept_region, title, budget) VALUES
        (1, 'Engineering', 'US-West', 'Cloud Platform', 500000.00),
        (2, 'Engineering', 'US-West', 'Mobile App', 200000.00),
        (3, 'Marketing', 'US-East', 'Brand Campaign', 150000.00),
        (4, 'Executive', NULL, 'Strategy Review', 50000.00)""")
    cur.execute("SELECT setval('projects_id_seq', 4)")

    cur.execute("""INSERT INTO tasks (id, project_title, assignee, status, metadata) VALUES
        (1, 'Cloud Platform', 'Alice', 'active', '{"priority": 1}'),
        (2, 'Cloud Platform', 'Bob', 'active', '{"priority": 2}'),
        (3, 'Mobile App', 'Charlie', 'pending', '{"priority": 1}'),
        (4, 'Brand Campaign', 'Diana', 'active', NULL),
        (5, 'Strategy Review', 'Eve', 'active', '{"priority": 3}')""")
    cur.execute("SELECT setval('tasks_id_seq', 5)")


# ============================================================
# Basic cascade operation tests
# ============================================================

def test_basic_cascade_update_single_key(db):
    """Updating project title cascades to tasks.project_title."""
    cur = db.cursor()
    cur.execute("UPDATE projects SET title = 'Cloud System' WHERE id = 1")
    cur.execute("SELECT project_title FROM tasks WHERE id = 1")
    assert cur.fetchone()[0] == "Cloud System"
    cur.execute("SELECT project_title FROM tasks WHERE id = 2")
    assert cur.fetchone()[0] == "Cloud System"


def test_basic_cascade_update_composite_key(db):
    """Updating department name cascades to projects via composite key."""
    cur = db.cursor()
    cur.execute("UPDATE departments SET name = 'Eng Team' WHERE id = 1")
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == "Eng Team"
    cur.execute("SELECT dept_name FROM projects WHERE id = 2")
    assert cur.fetchone()[0] == "Eng Team"
    cur.execute("SELECT dept_name FROM projects WHERE id = 3")
    assert cur.fetchone()[0] == "Marketing"


def test_cascade_update_both_composite_columns(db):
    """Updating both name and region cascades correctly."""
    cur = db.cursor()
    cur.execute(
        "UPDATE departments SET name = 'DevOps', region = 'EU-Central' WHERE id = 1")
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 1")
    row = cur.fetchone()
    assert row[0] == "DevOps"
    assert row[1] == "EU-Central"
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 2")
    row = cur.fetchone()
    assert row[0] == "DevOps"
    assert row[1] == "EU-Central"


def test_cascade_delete_single_key(db):
    """Deleting a project cascade-deletes its tasks."""
    cur = db.cursor()
    cur.execute("DELETE FROM projects WHERE id = 1")
    cur.execute(
        "SELECT count(*) FROM tasks WHERE project_title = 'Cloud Platform'")
    assert cur.fetchone()[0] == 0, "Tasks not cascade-deleted"
    cur.execute(
        "SELECT count(*) FROM tasks WHERE project_title = 'Brand Campaign'")
    assert cur.fetchone()[0] == 1


def test_set_null_cascade_composite_key(db):
    """Deleting department sets projects FK columns to NULL."""
    cur = db.cursor()
    cur.execute("DELETE FROM departments WHERE id = 1")
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 1")
    row = cur.fetchone()
    assert row is not None, "Project should still exist after set_null"
    assert row[0] is None, f"dept_name should be NULL, got {row[0]}"
    assert row[1] is None, f"dept_region should be NULL, got {row[1]}"
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 3")
    row = cur.fetchone()
    assert row[0] == "Marketing"
    assert row[1] == "US-East"


# ============================================================
# SQL injection neutralization tests
# ============================================================

def test_injection_via_where_clause(db):
    """WHERE clause injection via crafted OLD value must be neutralized."""
    cur = db.cursor()
    payload = "injected' OR '1'='1"
    cur.execute(
        "INSERT INTO departments (id, name, region, division) "
        "VALUES (100, %s, 'US-West', 'Test')", (payload,))
    cur.execute(
        "INSERT INTO projects (id, dept_name, dept_region, title, budget) "
        "VALUES (100, %s, 'US-West', 'ExploitProject', 1.00)", (payload,))
    cur.execute("UPDATE departments SET name = 'clean' WHERE id = 100")
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    result = cur.fetchone()
    assert result is not None and result[0] == "Engineering", \
        f"WHERE clause injection corrupted unrelated rows: {result}"
    cur.execute("SELECT dept_name FROM projects WHERE id = 2")
    result = cur.fetchone()
    assert result is not None and result[0] == "Engineering", \
        f"WHERE clause injection corrupted second row: {result}"


def test_injection_via_set_clause(db):
    """SET clause injection via crafted NEW value must be neutralized."""
    cur = db.cursor()
    cur.execute(
        "INSERT INTO departments (id, name, region, division) "
        "VALUES (101, 'target_safe', 'US-West', 'Test')")
    cur.execute(
        "INSERT INTO projects (id, dept_name, dept_region, title, budget) "
        "VALUES (101, 'target_safe', 'US-West', 'SafeProject', 10000.00)")
    payload = "x', budget = 0 --"
    cur.execute(
        "UPDATE departments SET name = %s WHERE id = 101", (payload,))
    cur.execute("SELECT budget FROM projects WHERE id = 1")
    result = cur.fetchone()
    assert result is not None and float(result[0]) == 500000.00, \
        f"SET clause injection corrupted unrelated rows: budget = {result}"
    cur.execute("SELECT dept_name, budget FROM projects WHERE id = 101")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == payload, \
        f"Expected payload as literal value, got {row[0]}"
    assert float(row[1]) == 10000.00, \
        f"Target budget was modified by injection: {row[1]}"


# ============================================================
# Special character handling tests
# ============================================================

def test_single_quotes_cascade(db):
    """Values with single quotes must cascade correctly."""
    cur = db.cursor()
    cur.execute(
        "UPDATE departments SET name = %s WHERE id = 1",
        ("O'Reilly Engineering",))
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == "O'Reilly Engineering"
    cur.execute("SELECT dept_name FROM projects WHERE id = 2")
    assert cur.fetchone()[0] == "O'Reilly Engineering"


def test_double_quotes_cascade(db):
    """Values with double quotes must cascade correctly."""
    cur = db.cursor()
    name = 'Acme "Premium" Division'
    cur.execute("UPDATE departments SET name = %s WHERE id = 1", (name,))
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == name


def test_backslash_cascade(db):
    """Values with backslashes must cascade correctly."""
    cur = db.cursor()
    name = r"Eng\US\West"
    cur.execute("UPDATE departments SET name = %s WHERE id = 1", (name,))
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == name


# ============================================================
# NULL handling in composite keys
# ============================================================

def test_null_region_cascade_update(db):
    """Cascade must work when composite key contains NULL (dept with no region)."""
    cur = db.cursor()
    cur.execute("UPDATE departments SET name = 'Exec Board' WHERE id = 3")
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 4")
    row = cur.fetchone()
    assert row[0] == "Exec Board", \
        f"NULL region cascade failed: dept_name = {row[0]} (expected 'Exec Board')"
    assert row[1] is None, \
        f"dept_region should remain NULL, got {row[1]}"
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == "Engineering"


def test_null_region_set_null_cascade(db):
    """SET NULL cascade must work when composite key contains NULL."""
    cur = db.cursor()
    cur.execute("DELETE FROM departments WHERE id = 3")
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 4")
    row = cur.fetchone()
    assert row is not None, "Project should still exist after set_null"
    assert row[0] is None, \
        f"dept_name should be NULL after cascade, got {row[0]}"
    assert row[1] is None, \
        f"dept_region should be NULL after cascade, got {row[1]}"
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == "Engineering"


# ============================================================
# Source code quality tests
# ============================================================

def test_no_raw_value_interpolation(db):
    """Fixed functions must not use ''%s'' for value interpolation."""
    cur = db.cursor()
    for func_name in ("cascade_fk_update", "cascade_fk_delete"):
        cur.execute(
            "SELECT prosrc FROM pg_proc WHERE proname = %s", (func_name,))
        body = cur.fetchone()[0]
        assert "''%s''" not in body, \
            f"{func_name} still uses ''%s'' for value interpolation"


def test_no_type_based_quoting(db):
    """Fixed functions must not use type-based quoting decisions."""
    cur = db.cursor()
    for func_name in ("cascade_fk_update", "cascade_fk_delete"):
        cur.execute(
            "SELECT prosrc FROM pg_proc WHERE proname = %s", (func_name,))
        body = cur.fetchone()[0].lower()
        assert "needs_quoting" not in body, \
            f"{func_name} still calls needs_quoting()"
        assert "information_schema" not in body, \
            f"{func_name} still queries information_schema for type detection"
        assert "data_type" not in body, \
            f"{func_name} still references data_type for quoting decisions"


def test_safe_value_and_identifier_handling(db):
    """Fixed functions must use safe patterns for values and identifiers."""
    cur = db.cursor()
    for func_name in ("cascade_fk_update", "cascade_fk_delete"):
        cur.execute(
            "SELECT prosrc FROM pg_proc WHERE proname = %s", (func_name,))
        body = cur.fetchone()[0].lower()
        uses_safe_values = (
            "using" in body
            or "%l" in body
            or "quote_literal" in body
            or "quote_nullable" in body
        )
        assert uses_safe_values, \
            f"{func_name} doesn't use safe value handling (%L/USING/quote_literal)"
        uses_safe_idents = "%i" in body or "quote_ident" in body
        assert uses_safe_idents, \
            f"{func_name} doesn't use safe identifier handling (%I/quote_ident)"


def test_security_definer_with_search_path(db):
    """Cascade functions must be SECURITY DEFINER with search_path set and persisting."""
    cur = db.cursor()
    for func_name in ("cascade_fk_update", "cascade_fk_delete"):
        cur.execute("""
            SELECT prosecdef, proconfig
            FROM pg_proc WHERE proname = %s
        """, (func_name,))
        row = cur.fetchone()
        assert row is not None, f"{func_name} not found"
        is_secdef = row[0]
        config = row[1] or []
        assert is_secdef, \
            f"{func_name} must be SECURITY DEFINER"
        has_search_path = any("search_path" in str(c) for c in config)
        assert has_search_path, \
            f"{func_name} is SECURITY DEFINER but search_path not set — " \
            "may have been silently stripped by an event trigger"


# ============================================================
# Environmental cleanup tests
# ============================================================

def test_no_interfering_event_triggers(db):
    """No active ddl_command_end event triggers should exist."""
    cur = db.cursor()
    cur.execute("""
        SELECT evtname FROM pg_event_trigger
        WHERE evtevent = 'ddl_command_end' AND evtenabled != 'D'
    """)
    triggers = [r[0] for r in cur.fetchall()]
    assert len(triggers) == 0, \
        f"Active ddl_command_end event triggers found: {triggers} — " \
        "these silently alter function configurations after CREATE OR REPLACE"


def test_no_log_suppression_rules(db):
    """No rules should exist on _cascade_log that suppress logging."""
    cur = db.cursor()
    cur.execute("SELECT rulename FROM pg_rules WHERE tablename = '_cascade_log'")
    rules = [r[0] for r in cur.fetchall()]
    assert len(rules) == 0, \
        f"Rules found on _cascade_log: {rules} — may suppress cascade logging"


def test_cascade_log_records_updates(db):
    """Cascade log must actually record entries for UPDATE cascade operations."""
    cur = db.cursor()
    cur.execute("DELETE FROM _cascade_log")
    cur.execute("UPDATE departments SET name = 'LogVerify' WHERE id = 1")
    cur.execute("SELECT count(*) FROM _cascade_log WHERE action = 'update'")
    count = cur.fetchone()[0]
    assert count > 0, \
        "Cascade log contains no entries for UPDATE cascades — " \
        "check for suppression rules on _cascade_log"


# ============================================================
# Integration tests
# ============================================================

def test_combined_update_and_delete_cascade(db):
    """Update cascade followed by delete cascade maintains consistency."""
    cur = db.cursor()
    cur.execute("UPDATE departments SET name = 'NewEng' WHERE id = 1")
    cur.execute("SELECT dept_name FROM projects WHERE id = 1")
    assert cur.fetchone()[0] == "NewEng"
    cur.execute("SELECT dept_name FROM projects WHERE id = 2")
    assert cur.fetchone()[0] == "NewEng"
    cur.execute("DELETE FROM departments WHERE id = 1")
    cur.execute("SELECT dept_name, dept_region FROM projects WHERE id = 1")
    row = cur.fetchone()
    assert row[0] is None, f"dept_name should be NULL after set_null cascade, got {row[0]}"
    assert row[1] is None, f"dept_region should be NULL after set_null cascade, got {row[1]}"
    cur.execute("SELECT count(*) FROM tasks WHERE project_title = 'Cloud Platform'")
    assert cur.fetchone()[0] == 2, "Tasks under Cloud Platform should still exist"


# ============================================================
# File existence tests
# ============================================================

def test_vulnerability_analysis_exists():
    """vulnerability_analysis.sql must exist with exploit demonstrations."""
    path = "/app/vulnerability_analysis.sql"
    assert os.path.exists(path), f"{path} not found"
    with open(path) as f:
        content = f.read()
    assert len(content) > 100, "vulnerability_analysis.sql is too short"
    content_lower = content.lower()
    assert "insert" in content_lower or "update" in content_lower \
        or "delete" in content_lower, \
        "vulnerability_analysis.sql must contain SQL exploitation statements"
    vuln_keywords = ['injection', 'null', 'search_path', 'event trigger',
                     'rule', 'security definer', 'quoting', 'ddl']
    found_classes = sum(1 for kw in vuln_keywords if kw in content_lower)
    assert found_classes >= 3, \
        f"vulnerability_analysis.sql covers only {found_classes} vulnerability " \
        "classes, need at least 3 (injection, null handling, environmental interference)"


def test_fixed_functions_exists():
    """fixed_functions.sql must contain corrected function definitions."""
    path = "/app/fixed_functions.sql"
    assert os.path.exists(path), f"{path} not found"
    with open(path) as f:
        content = f.read()
    content_lower = content.lower()
    assert "create" in content_lower and "function" in content_lower, \
        "fixed_functions.sql must contain function definitions"
    assert "cascade_fk_update" in content, \
        "fixed_functions.sql must contain cascade_fk_update"
    assert "cascade_fk_delete" in content, \
        "fixed_functions.sql must contain cascade_fk_delete"
