#!/usr/bin/env python3
"""Behavioral tests for the TQL (Text Query Language) implementation."""

import subprocess
import pytest


def run_tql(query):
    """Execute a TQL query and return (headers, rows)."""
    result = subprocess.run(
        ["/app/tql", query],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Query failed (exit {result.returncode}): {result.stderr}\nQuery: {query}"
    )
    output = result.stdout.strip()
    if not output:
        return [], []
    lines = output.split("\n")
    headers = lines[0].split("\t")
    rows = [line.split("\t") for line in lines[1:] if line]
    return headers, rows


# ---------------------------------------------------------------------------
# Basic queries
# ---------------------------------------------------------------------------

def test_basic_select_all():
    """SELECT * returns all rows and columns with correct types."""
    headers, rows = run_tql("SELECT * FROM employees ORDER BY id")
    assert headers == ["id", "name", "department_id", "salary", "manager_id"]
    assert len(rows) == 7
    assert rows[0] == ["1", "Alice", "10", "75000", "NULL"]
    assert rows[3] == ["4", "Diana", "20", "70000", "3"]
    assert rows[6] == ["7", "Grace", "NULL", "55000", "2"]


def test_select_where_filter():
    """WHERE clause filters rows correctly."""
    headers, rows = run_tql(
        "SELECT name, salary FROM employees WHERE salary > 70000 ORDER BY name"
    )
    assert headers == ["name", "salary"]
    assert len(rows) == 3
    assert rows[0] == ["Alice", "75000"]
    assert rows[1] == ["Charlie", "80000"]
    assert rows[2] == ["Eve", "90000"]


def test_order_by_desc_with_limit():
    """ORDER BY DESC combined with LIMIT."""
    _, rows = run_tql("SELECT name FROM employees ORDER BY salary DESC LIMIT 3")
    assert [r[0] for r in rows] == ["Eve", "Charlie", "Alice"]


def test_limit_offset():
    """LIMIT with OFFSET for pagination."""
    _, rows = run_tql("SELECT name FROM employees ORDER BY name LIMIT 3 OFFSET 2")
    assert [r[0] for r in rows] == ["Charlie", "Diana", "Eve"]


# ---------------------------------------------------------------------------
# JOINs
# ---------------------------------------------------------------------------

def test_inner_join():
    """INNER JOIN excludes rows without a match."""
    _, rows = run_tql(
        "SELECT e.name, d.name AS dept_name FROM employees e "
        "INNER JOIN departments d ON e.department_id = d.id ORDER BY e.name"
    )
    assert len(rows) == 6
    names = [r[0] for r in rows]
    assert "Grace" not in names
    assert rows[0] == ["Alice", "Engineering"]
    assert rows[5] == ["Frank", "Engineering"]


def test_left_join():
    """LEFT JOIN includes all left rows, filling NULLs for non-matches."""
    _, rows = run_tql(
        "SELECT e.name, d.name AS dept_name FROM employees e "
        "LEFT JOIN departments d ON e.department_id = d.id ORDER BY e.name"
    )
    assert len(rows) == 7
    grace_row = [r for r in rows if r[0] == "Grace"][0]
    assert grace_row[1] == "NULL"


def test_self_join():
    """Self-join to resolve employee-manager relationships."""
    _, rows = run_tql(
        "SELECT e.name AS employee, m.name AS manager "
        "FROM employees e LEFT JOIN employees m ON e.manager_id = m.id "
        "ORDER BY e.name"
    )
    assert len(rows) == 7
    data = {r[0]: r[1] for r in rows}
    assert data["Alice"] == "NULL"
    assert data["Bob"] == "Alice"
    assert data["Diana"] == "Charlie"
    assert data["Grace"] == "Bob"


def test_multi_table_join_aggregate():
    """Multi-table LEFT JOIN with GROUP BY and COUNT."""
    _, rows = run_tql(
        "SELECT d.name AS dept, COUNT(o.id) AS order_count "
        "FROM departments d "
        "LEFT JOIN employees e ON d.id = e.department_id "
        "LEFT JOIN orders o ON e.id = o.employee_id "
        "GROUP BY d.name ORDER BY order_count DESC, d.name ASC"
    )
    assert len(rows) == 4
    assert rows[0] == ["Engineering", "4"]
    assert rows[1] == ["Marketing", "2"]
    assert rows[2] == ["Sales", "1"]
    assert rows[3] == ["HR", "0"]


# ---------------------------------------------------------------------------
# GROUP BY / HAVING / Aggregation
# ---------------------------------------------------------------------------

def test_group_by_count():
    """GROUP BY with COUNT(*) and explicit NULLS LAST ordering."""
    _, rows = run_tql(
        "SELECT department_id, COUNT(*) AS cnt FROM employees "
        "GROUP BY department_id ORDER BY department_id NULLS LAST"
    )
    assert len(rows) == 4
    assert rows[0] == ["10", "3"]
    assert rows[1] == ["20", "2"]
    assert rows[2] == ["30", "1"]
    assert rows[3] == ["NULL", "1"]


def test_group_by_having():
    """HAVING filters groups after aggregation."""
    _, rows = run_tql(
        "SELECT department_id, SUM(salary) AS total FROM employees "
        "GROUP BY department_id HAVING SUM(salary) > 100000 ORDER BY total DESC"
    )
    assert len(rows) == 2
    assert rows[0] == ["10", "200000"]
    assert rows[1] == ["20", "150000"]


def test_having_with_round_avg():
    """HAVING combined with AVG and ROUND for float output."""
    _, rows = run_tql(
        "SELECT department_id, ROUND(AVG(salary), 2) AS avg_sal "
        "FROM employees GROUP BY department_id "
        "HAVING COUNT(*) > 1 ORDER BY department_id"
    )
    assert len(rows) == 2
    assert rows[0][0] == "10"
    assert rows[0][1] == "66666.67"
    assert rows[1][0] == "20"
    assert rows[1][1] == "75000"


# ---------------------------------------------------------------------------
# MEDIAN aggregate
# ---------------------------------------------------------------------------

def test_median_odd_count():
    """MEDIAN with odd number of values returns the middle value."""
    _, rows = run_tql("SELECT MEDIAN(salary) AS median_sal FROM employees")
    assert rows[0][0] == "70000"


def test_median_even_count():
    """MEDIAN with even count returns average of two middle values."""
    _, rows = run_tql(
        "SELECT MEDIAN(salary) AS med FROM employees WHERE id IN (1, 2, 3, 4)"
    )
    # sorted: 65000, 70000, 75000, 80000 -> (70000+75000)/2 = 72500
    assert rows[0][0] == "72500"


def test_median_fractional_result():
    """MEDIAN producing a non-integer fractional result."""
    _, rows = run_tql(
        "SELECT MEDIAN(amount) AS med FROM orders WHERE id IN (1, 4)"
    )
    # sorted: 150.5, 300.0 -> (150.5+300.0)/2 = 225.25
    assert rows[0][0] == "225.25"


# ---------------------------------------------------------------------------
# NULL semantics (three-valued logic)
# ---------------------------------------------------------------------------

def test_is_null():
    """IS NULL identifies NULL values."""
    _, rows = run_tql("SELECT name FROM employees WHERE department_id IS NULL")
    assert len(rows) == 1
    assert rows[0][0] == "Grace"


def test_null_equals_null():
    """NULL = NULL yields UNKNOWN, returning zero rows."""
    _, rows = run_tql("SELECT name FROM employees WHERE manager_id = NULL")
    assert len(rows) == 0


def test_not_with_null_propagation():
    """NOT propagates UNKNOWN: NOT (NULL = x) is UNKNOWN, row excluded."""
    _, rows = run_tql(
        "SELECT name FROM employees WHERE NOT (department_id = 10) ORDER BY name"
    )
    names = [r[0] for r in rows]
    assert names == ["Charlie", "Diana", "Eve"]


def test_not_in_null_propagation():
    """NOT IN with NULL column value yields UNKNOWN, row excluded."""
    _, rows = run_tql(
        "SELECT name FROM employees "
        "WHERE department_id NOT IN (10, 20) ORDER BY name"
    )
    names = [r[0] for r in rows]
    assert names == ["Eve"]


# ---------------------------------------------------------------------------
# Expressions: CASE, LIKE, BETWEEN
# ---------------------------------------------------------------------------

def test_case_when_expression():
    """CASE WHEN with multiple branches and ELSE."""
    _, rows = run_tql(
        "SELECT name, CASE WHEN salary >= 80000 THEN 'high' "
        "WHEN salary >= 65000 THEN 'medium' ELSE 'low' END AS level "
        "FROM employees ORDER BY name"
    )
    data = {r[0]: r[1] for r in rows}
    assert data["Eve"] == "high"
    assert data["Charlie"] == "high"
    assert data["Alice"] == "medium"
    assert data["Bob"] == "medium"
    assert data["Frank"] == "low"
    assert data["Grace"] == "low"


def test_like_percent_wildcard():
    """LIKE with % wildcard (case-sensitive matching)."""
    _, rows = run_tql(
        "SELECT name FROM employees WHERE name LIKE 'A%' ORDER BY name"
    )
    assert len(rows) == 1
    assert rows[0][0] == "Alice"


def test_like_underscore_wildcard():
    """LIKE with _ single-character wildcard."""
    _, rows = run_tql(
        "SELECT name FROM employees WHERE name LIKE '_o%' ORDER BY name"
    )
    assert len(rows) == 1
    assert rows[0][0] == "Bob"


def test_between_predicate():
    """BETWEEN is inclusive on both ends."""
    _, rows = run_tql(
        "SELECT name FROM employees "
        "WHERE salary BETWEEN 65000 AND 80000 ORDER BY name"
    )
    assert [r[0] for r in rows] == ["Alice", "Bob", "Charlie", "Diana"]


# ---------------------------------------------------------------------------
# Subqueries
# ---------------------------------------------------------------------------

def test_in_subquery():
    """IN with a subquery for set membership."""
    _, rows = run_tql(
        "SELECT name FROM employees WHERE department_id IN "
        "(SELECT id FROM departments WHERE budget > 350000) ORDER BY name"
    )
    assert [r[0] for r in rows] == ["Alice", "Bob", "Eve", "Frank"]


def test_exists_correlated_subquery():
    """EXISTS with a correlated subquery."""
    _, rows = run_tql(
        "SELECT e.name FROM employees e WHERE EXISTS "
        "(SELECT 1 FROM orders o WHERE o.employee_id = e.id) ORDER BY e.name"
    )
    assert [r[0] for r in rows] == ["Alice", "Bob", "Charlie", "Diana", "Eve"]


def test_scalar_subquery_comparison():
    """Scalar subquery used in a comparison (salary > average)."""
    _, rows = run_tql(
        "SELECT name, salary FROM employees "
        "WHERE salary > (SELECT AVG(salary) FROM employees) ORDER BY name"
    )
    assert [r[0] for r in rows] == ["Alice", "Charlie", "Eve"]


# ---------------------------------------------------------------------------
# String operations, arithmetic, functions
# ---------------------------------------------------------------------------

def test_string_concat_and_coalesce():
    """String concatenation (||) and COALESCE for NULL substitution."""
    _, rows = run_tql(
        "SELECT name || ' - ' || COALESCE(department_id, 'none') AS label "
        "FROM employees WHERE id IN (1, 7) ORDER BY id"
    )
    assert len(rows) == 2
    assert rows[0][0] == "Alice - 10"
    assert rows[1][0] == "Grace - none"


def test_arithmetic_and_scalar_functions():
    """Arithmetic expressions combined with UPPER and LENGTH."""
    _, rows = run_tql(
        "SELECT UPPER(name) AS uname, LENGTH(name) AS nlen, "
        "salary * 12 AS annual "
        "FROM employees WHERE id <= 3 ORDER BY id"
    )
    assert rows[0] == ["ALICE", "5", "900000"]
    assert rows[1] == ["BOB", "3", "780000"]
    assert rows[2] == ["CHARLIE", "7", "960000"]


# ---------------------------------------------------------------------------
# DISTINCT, COUNT DISTINCT, edge cases
# ---------------------------------------------------------------------------

def test_distinct_values():
    """DISTINCT removes duplicate rows."""
    _, rows = run_tql(
        "SELECT DISTINCT department_id FROM employees "
        "ORDER BY department_id NULLS LAST"
    )
    assert [r[0] for r in rows] == ["10", "20", "30", "NULL"]


def test_count_distinct():
    """COUNT(DISTINCT expr) counts unique non-NULL values."""
    _, rows = run_tql(
        "SELECT COUNT(DISTINCT department_id) AS unique_depts FROM employees"
    )
    assert rows[0][0] == "3"


def test_empty_result_has_headers():
    """A query with no matching rows still outputs the header line."""
    headers, rows = run_tql(
        "SELECT name, salary FROM employees WHERE salary > 1000000"
    )
    assert headers == ["name", "salary"]
    assert len(rows) == 0


def test_error_on_invalid_query():
    """An invalid query returns a non-zero exit code."""
    result = subprocess.run(
        ["/app/tql", "COMPLETELY INVALID GIBBERISH QUERY"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
