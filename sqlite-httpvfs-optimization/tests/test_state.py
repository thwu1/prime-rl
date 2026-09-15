
import sqlite3
import os
import pytest

BACKUP_DB = '/app/.original.db'
OPTIMIZED_DB = '/tmp/test_optimized.db'
OPTIMIZE_SQL = '/app/optimize.sql'

QUERIES = {
    'Q1': """SELECT country_code, COUNT(*) as cnt
FROM events
WHERE event_type = 'purchase'
  AND ts >= 1704067200 AND ts < 1706745600
GROUP BY country_code
ORDER BY cnt DESC""",

    'Q2': """SELECT user_id, SUM(value) as total_value
FROM events
WHERE category = 'electronics' AND value IS NOT NULL
GROUP BY user_id
ORDER BY total_value DESC
LIMIT 20""",

    'Q3': """SELECT ts, event_type
FROM events
WHERE user_id = 'U00042'
ORDER BY ts DESC
LIMIT 10""",

    'Q4': """SELECT device, COUNT(DISTINCT user_id) as unique_users
FROM events
WHERE event_type = 'pageview'
GROUP BY device""",

    'Q5': """SELECT category, AVG(value) as avg_value, COUNT(*) as cnt
FROM events
WHERE event_type = 'purchase' AND value > 0
GROUP BY category
ORDER BY avg_value DESC""",

    'Q6': """SELECT SUM(value) as total_revenue,
       COUNT(*) as num_transactions,
       COUNT(DISTINCT user_id) as unique_buyers
FROM events
WHERE event_type = 'purchase'
  AND country_code = 'US'
  AND ts >= 1719792000 AND ts < 1722470400""",

    'Q7': """SELECT event_type, ts, value
FROM events
WHERE user_id = 'U00042' AND event_type = 'purchase'
ORDER BY ts DESC""",
}


def _get_plan_details(db_path, query):
    """Return list of detail strings from EXPLAIN QUERY PLAN."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
    conn.close()
    details = []
    for r in rows:
        try:
            details.append(str(r[3]))
        except (IndexError, TypeError):
            details.append(str(r))
    return details


# ---------- File existence ----------

def test_optimize_sql_exists():
    assert os.path.exists(OPTIMIZE_SQL), "/app/optimize.sql does not exist"
    assert os.path.getsize(OPTIMIZE_SQL) > 0, "/app/optimize.sql is empty"


# ---------- Page size ----------

def test_page_size_reduced():
    """Page size must be below default 4096 for HTTP range-request serving."""
    conn = sqlite3.connect(OPTIMIZED_DB)
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()
    assert page_size < 4096, (
        f"Page size is {page_size} (>= 4096 default). "
        f"Must be reduced for HTTP range-request serving."
    )
    assert page_size >= 512, f"Page size {page_size} is unreasonably small"


# ---------- Covering index for each query ----------

@pytest.mark.parametrize("qname", list(QUERIES.keys()))
def test_covering_index(qname):
    """Each query must use a COVERING INDEX (no table row lookup)."""
    details = _get_plan_details(OPTIMIZED_DB, QUERIES[qname])
    plan_text = ' '.join(details)
    assert 'COVERING INDEX' in plan_text, (
        f"{qname} does not use COVERING INDEX.\n"
        f"Query plan: {plan_text}"
    )


@pytest.mark.parametrize("qname", list(QUERIES.keys()))
def test_search_not_scan(qname):
    """Each query must use SEARCH (prefix-based), not SCAN (full index walk)."""
    details = _get_plan_details(OPTIMIZED_DB, QUERIES[qname])
    for d in details:
        if 'events' in d.lower():
            assert 'SEARCH' in d, (
                f"{qname} uses full SCAN instead of prefix SEARCH on events "
                f"table — index columns likely in wrong order.\n"
                f"Plan detail: {d}"
            )


# ---------- Index budget ----------

def test_index_count():
    """At most 6 user-created indexes across the database."""
    conn = sqlite3.connect(OPTIMIZED_DB)
    count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0]
    conn.close()
    assert count <= 6, (
        f"Found {count} user-created indexes, but maximum 6 allowed. "
        f"At least one index must serve multiple queries."
    )
    assert count >= 1, "No indexes found — indexes are required"


# ---------- Partial index ----------

def test_partial_index_exists():
    """At least one index must be a partial index (with WHERE clause)."""
    conn = sqlite3.connect(OPTIMIZED_DB)
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='index' AND sql IS NOT NULL AND sql LIKE '%WHERE %'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1, (
        "No partial index found. At least one index must use a WHERE clause "
        "to minimize index size for HTTP-VFS serving."
    )


# ---------- ANALYZE statistics ----------

def test_analyze_run():
    """sqlite_stat1 must exist and be populated (ANALYZE was run)."""
    conn = sqlite3.connect(OPTIMIZED_DB)
    tables = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='sqlite_stat1'"
    ).fetchall()
    assert len(tables) == 1, (
        "sqlite_stat1 table not found — ANALYZE has not been run. "
        "The query planner needs statistics for correct index selection."
    )
    count = conn.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0]
    conn.close()
    assert count > 0, "sqlite_stat1 is empty — ANALYZE did not collect statistics"


# ---------- Data integrity ----------

def test_row_count_preserved():
    """No data may be lost during optimization."""
    backup_conn = sqlite3.connect(BACKUP_DB)
    opt_conn = sqlite3.connect(OPTIMIZED_DB)
    backup_count = backup_conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    opt_count = opt_conn.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    backup_conn.close()
    opt_conn.close()
    assert backup_count == opt_count, (
        f"Row count mismatch: original={backup_count}, optimized={opt_count}"
    )


@pytest.mark.parametrize("qname", ['Q1', 'Q4'])
def test_results_match_no_limit(qname):
    """For queries without LIMIT, sorted results must match the original."""
    backup_conn = sqlite3.connect(BACKUP_DB)
    opt_conn = sqlite3.connect(OPTIMIZED_DB)
    backup_rows = sorted(backup_conn.execute(QUERIES[qname]).fetchall())
    opt_rows = sorted(opt_conn.execute(QUERIES[qname]).fetchall())
    backup_conn.close()
    opt_conn.close()
    assert backup_rows == opt_rows, f"{qname} results differ from original"


def test_q5_results_match():
    """Q5 has no LIMIT; category counts and averages must match."""
    query = QUERIES['Q5']
    backup_conn = sqlite3.connect(BACKUP_DB)
    opt_conn = sqlite3.connect(OPTIMIZED_DB)
    backup_rows = sorted(backup_conn.execute(query).fetchall())
    opt_rows = sorted(opt_conn.execute(query).fetchall())
    backup_conn.close()
    opt_conn.close()
    assert len(backup_rows) == len(opt_rows), "Q5 category count differs"
    for b, o in zip(backup_rows, opt_rows):
        assert b[0] == o[0], f"Q5 category mismatch: {b[0]} vs {o[0]}"
        assert abs(b[1] - o[1]) < 0.01, f"Q5 avg_value mismatch for {b[0]}"
        assert b[2] == o[2], f"Q5 count mismatch for {b[0]}"


def test_q6_results_match():
    """Q6 aggregate results must match the original."""
    query = QUERIES['Q6']
    backup_conn = sqlite3.connect(BACKUP_DB)
    opt_conn = sqlite3.connect(OPTIMIZED_DB)
    backup_row = backup_conn.execute(query).fetchone()
    opt_row = opt_conn.execute(query).fetchone()
    backup_conn.close()
    opt_conn.close()
    assert abs(backup_row[0] - opt_row[0]) < 0.01, (
        f"Q6 total_revenue mismatch: {backup_row[0]} vs {opt_row[0]}"
    )
    assert backup_row[1] == opt_row[1], (
        f"Q6 num_transactions mismatch: {backup_row[1]} vs {opt_row[1]}"
    )
    assert backup_row[2] == opt_row[2], (
        f"Q6 unique_buyers mismatch: {backup_row[2]} vs {opt_row[2]}"
    )


def test_q7_results_match():
    """Q7 results must match the original (sorted comparison)."""
    query = QUERIES['Q7']
    backup_conn = sqlite3.connect(BACKUP_DB)
    opt_conn = sqlite3.connect(OPTIMIZED_DB)
    backup_rows = sorted(backup_conn.execute(query).fetchall())
    opt_rows = sorted(opt_conn.execute(query).fetchall())
    backup_conn.close()
    opt_conn.close()
    assert len(backup_rows) == len(opt_rows), (
        f"Q7 row count mismatch: {len(backup_rows)} vs {len(opt_rows)}"
    )
    for b, o in zip(backup_rows, opt_rows):
        assert b[0] == o[0] and b[1] == o[1], (
            f"Q7 row mismatch: {b} vs {o}"
        )
        if b[2] is not None:
            assert abs(b[2] - o[2]) < 0.01, (
                f"Q7 value mismatch for ts={b[1]}"
            )
        else:
            assert o[2] is None, "Q7 null value mismatch"


# ---------- Database size ----------

def test_database_size():
    """Optimized database (with indexes) must stay under 200 MB."""
    size_mb = os.path.getsize(OPTIMIZED_DB) / (1024 * 1024)
    assert size_mb < 200, f"Database size {size_mb:.1f} MB exceeds 200 MB limit"
