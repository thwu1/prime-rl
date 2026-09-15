#!/usr/bin/env python3
"""Verify SQLite database optimization for HTTP Range-request serving.

Tests check:
  1. Page size is 1024
  2. Pragmas configured for static HTTP serving (journal_mode, auto_vacuum)
  3. Index budget: max 7 user-created indexes on events, >= 1 partial index
  4. All 8 analytical queries use COVERING INDEX access
  5. Q6 uses covering indexes on BOTH events and pages tables
  6. No bare table scans on events
  7. FTS5 virtual table works with MATCH, bm25(), snippet()
  8. Query results are correct
"""

import re
import sqlite3

import pytest

DB_PATH = "/app/analytics.db"

# ---------------------------------------------------------------------------
# The eight analytical queries (must match /app/queries.sql)
# ---------------------------------------------------------------------------

Q1 = """
SELECT country, COUNT(DISTINCT user_id) AS unique_visitors
FROM events
WHERE event_type = 'pageview'
  AND timestamp BETWEEN 1696200000 AND 1696500000
GROUP BY country
ORDER BY unique_visitors DESC
"""

Q2 = """
SELECT page_url, COUNT(DISTINCT session_id) AS sessions
FROM events
WHERE device_type = 'mobile'
  AND event_type = 'pageview'
GROUP BY page_url
ORDER BY sessions DESC
LIMIT 20
"""

Q3 = """
SELECT u.plan_type,
       SUM(e.revenue_cents) AS total_revenue,
       COUNT(*) AS num_purchases
FROM events e
JOIN users u ON e.user_id = u.id
WHERE e.event_type = 'purchase'
GROUP BY u.plan_type
ORDER BY total_revenue DESC
"""

Q4 = """
SELECT device_type,
       COUNT(*) AS total_sessions,
       SUM(CASE WHEN pv_count = 1 THEN 1 ELSE 0 END) AS bounced_sessions,
       ROUND(100.0 * SUM(CASE WHEN pv_count = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS bounce_rate
FROM (
    SELECT session_id, device_type, COUNT(*) AS pv_count
    FROM events
    WHERE event_type = 'pageview'
    GROUP BY session_id
)
GROUP BY device_type
"""

Q5 = """
SELECT e1.referrer,
       COUNT(DISTINCT e1.session_id) AS total_sessions,
       COUNT(DISTINCT e2.session_id) AS purchase_sessions
FROM events e1
LEFT JOIN events e2
  ON e1.session_id = e2.session_id
  AND e2.event_type = 'purchase'
WHERE e1.event_type = 'pageview'
  AND e1.referrer IS NOT NULL
GROUP BY e1.referrer
ORDER BY purchase_sessions DESC
"""

Q6 = """
SELECT p.category,
       COUNT(*) AS pageviews,
       AVG(e.duration_ms) AS avg_duration_ms,
       COUNT(DISTINCT e.user_id) AS unique_users
FROM events e
JOIN pages p ON e.page_url = p.url
WHERE e.event_type = 'pageview'
  AND e.duration_ms IS NOT NULL
GROUP BY p.category
ORDER BY avg_duration_ms DESC
"""

Q7 = """
SELECT country,
       COUNT(*) AS num_purchases,
       SUM(revenue_cents) AS total_revenue,
       AVG(revenue_cents) AS avg_revenue,
       MAX(revenue_cents) AS max_revenue
FROM events
WHERE event_type = 'purchase'
  AND revenue_cents > 10000
GROUP BY country
HAVING COUNT(*) >= 3
ORDER BY total_revenue DESC
"""

Q8 = """
SELECT date(timestamp, 'unixepoch') AS day,
       COUNT(*) AS pageviews,
       COUNT(DISTINCT user_id) AS unique_users
FROM events
WHERE event_type = 'pageview'
  AND timestamp >= 1696118400
  AND timestamp < 1696723200
GROUP BY date(timestamp, 'unixepoch')
ORDER BY day
"""

ALL_QUERIES = {
    "Q1": Q1, "Q2": Q2, "Q3": Q3, "Q4": Q4,
    "Q5": Q5, "Q6": Q6, "Q7": Q7, "Q8": Q8,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    return sqlite3.connect(DB_PATH)


def _plan_lines(conn, query):
    """Return EXPLAIN QUERY PLAN detail strings."""
    rows = conn.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
    return [row[3] for row in rows]


def _plan_text(conn, query):
    """Return full plan as a single string."""
    return "\n".join(_plan_lines(conn, query))


# ---------------------------------------------------------------------------
# 1. Page-size check
# ---------------------------------------------------------------------------

class TestPageSize:
    def test_page_size_is_1024(self):
        conn = _conn()
        ps = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.close()
        assert ps == 1024, f"Expected page_size=1024, got {ps}"


# ---------------------------------------------------------------------------
# 2. Pragma checks for HTTP serving
# ---------------------------------------------------------------------------

class TestPragmas:
    def test_journal_mode_delete(self):
        conn = _conn()
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert jm == "delete", (
            f"Journal mode must be 'delete' for static HTTP serving, got '{jm}'"
        )

    def test_auto_vacuum_disabled(self):
        conn = _conn()
        av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        conn.close()
        assert av == 0, (
            f"auto_vacuum must be 0 (none) for stable page offsets, got {av}"
        )


# ---------------------------------------------------------------------------
# 3. Index constraint checks
# ---------------------------------------------------------------------------

class TestIndexConstraints:
    def test_max_7_events_indexes(self):
        """No more than 7 user-created indexes on the events table."""
        conn = _conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='events' AND sql IS NOT NULL"
        ).fetchall()
        conn.close()
        names = [r[0] for r in rows]
        assert len(names) <= 7, (
            f"At most 7 user-created indexes allowed on events, "
            f"found {len(names)}: {names}"
        )

    def test_at_least_one_partial_index_on_events(self):
        """At least one index on events must be a partial index (with WHERE)."""
        conn = _conn()
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='events' AND sql IS NOT NULL"
        ).fetchall()
        conn.close()
        partial = [r[0] for r in rows if r[1] and "WHERE" in r[1].upper()]
        assert len(partial) >= 1, (
            f"At least one partial index (with WHERE clause) must exist on events. "
            f"Found indexes: {[r[0] for r in rows]}, none have WHERE clauses."
        )


# ---------------------------------------------------------------------------
# 4. Covering-index checks
# ---------------------------------------------------------------------------

class TestCoveringIndex:
    """Every analytical query must achieve COVERING INDEX access."""

    def _assert_covering(self, label, query):
        conn = _conn()
        plan = _plan_text(conn, query)
        conn.close()
        assert "COVERING INDEX" in plan, (
            f"{label} must use COVERING INDEX.\nPlan:\n{plan}"
        )

    def test_q1_covering(self):
        self._assert_covering("Q1", Q1)

    def test_q2_covering(self):
        self._assert_covering("Q2", Q2)

    def test_q3_covering(self):
        self._assert_covering("Q3", Q3)

    def test_q4_covering(self):
        self._assert_covering("Q4", Q4)

    def test_q5_covering(self):
        self._assert_covering("Q5", Q5)

    def test_q6_covering(self):
        self._assert_covering("Q6", Q6)

    def test_q7_covering(self):
        self._assert_covering("Q7", Q7)

    def test_q8_covering(self):
        self._assert_covering("Q8", Q8)

    def test_q6_both_tables_covering(self):
        """Q6 must use COVERING INDEX on both events AND pages table access.

        In the HTTP VFS cost model, even a 50-row pages table scan means
        20+ network round trips. Both sides of the join must be covered.
        """
        conn = _conn()
        plan_lines = _plan_lines(conn, Q6)
        conn.close()
        covering_count = sum(
            1 for line in plan_lines if "COVERING INDEX" in line
        )
        assert covering_count >= 2, (
            f"Q6 must use COVERING INDEX on both events and pages accesses "
            f"(expected >= 2, found {covering_count}).\n"
            f"Plan:\n" + "\n".join(plan_lines)
        )


# ---------------------------------------------------------------------------
# 5. No bare table scans on events
# ---------------------------------------------------------------------------

class TestNoBareScan:
    """No query should do a bare SCAN on events without an index."""

    _BARE_SCAN_RE = re.compile(
        r"SCAN\s+(?:TABLE\s+)?events\b(?!.*\bINDEX\b)",
        re.IGNORECASE,
    )

    def test_no_bare_event_scan(self):
        conn = _conn()
        for label, query in ALL_QUERIES.items():
            for line in _plan_lines(conn, query):
                assert not self._BARE_SCAN_RE.search(line), (
                    f"{label} has bare SCAN on events without index: {line}"
                )
        conn.close()


# ---------------------------------------------------------------------------
# 6. FTS5 checks
# ---------------------------------------------------------------------------

class TestFTS5:
    def test_fts5_table_exists(self):
        conn = _conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='pages_fts'"
        ).fetchone()
        conn.close()
        assert row is not None, "FTS5 table 'pages_fts' must exist"

    def test_fts5_match(self):
        conn = _conn()
        rows = conn.execute(
            "SELECT * FROM pages_fts WHERE pages_fts MATCH 'analytics' LIMIT 5"
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "FTS5 should return results for 'analytics'"

    def test_fts5_bm25_ranking(self):
        """FTS5 must support bm25() ranking function."""
        conn = _conn()
        rows = conn.execute(
            "SELECT bm25(pages_fts) AS score, title, category "
            "FROM pages_fts WHERE pages_fts MATCH 'analytics' "
            "ORDER BY bm25(pages_fts) LIMIT 5"
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "bm25() query should return results"
        # bm25() returns negative values (lower = more relevant)
        assert all(r[0] < 0 for r in rows), (
            f"bm25() should return negative values, got: {[r[0] for r in rows]}"
        )

    def test_fts5_snippet(self):
        """FTS5 must support snippet() extraction."""
        conn = _conn()
        rows = conn.execute(
            "SELECT snippet(pages_fts, 0, '<b>', '</b>', '...', 10) AS snip "
            "FROM pages_fts WHERE pages_fts MATCH 'analytics' LIMIT 5"
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "snippet() query should return results"
        assert any("<b>" in r[0] for r in rows), (
            f"snippet() should contain highlight markers, got: {[r[0] for r in rows]}"
        )

    def test_fts5_phrase_search(self):
        conn = _conn()
        rows = conn.execute(
            "SELECT * FROM pages_fts "
            "WHERE pages_fts MATCH '\"getting started\"' LIMIT 5"
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "FTS5 should find 'getting started' pages"


# ---------------------------------------------------------------------------
# 7. Query-correctness checks
# ---------------------------------------------------------------------------

class TestQueryCorrectness:
    def test_q1_returns_countries(self):
        conn = _conn()
        rows = conn.execute(Q1).fetchall()
        conn.close()
        assert len(rows) > 0, "Q1 should return rows"
        assert all(
            len(r[0]) == 2 for r in rows
        ), "Countries should be 2-letter codes"

    def test_q2_returns_pages(self):
        conn = _conn()
        rows = conn.execute(Q2).fetchall()
        conn.close()
        assert 0 < len(rows) <= 20, "Q2 should return 1-20 rows"
        sessions = [r[1] for r in rows]
        assert sessions == sorted(sessions, reverse=True), (
            "Q2 must be ordered DESC by sessions"
        )

    def test_q3_has_all_plan_types(self):
        conn = _conn()
        rows = conn.execute(Q3).fetchall()
        conn.close()
        plan_types = {r[0] for r in rows}
        for pt in ("free", "basic", "pro", "enterprise"):
            assert pt in plan_types, f"Q3 missing plan_type '{pt}'"

    def test_q4_has_all_devices(self):
        conn = _conn()
        rows = conn.execute(Q4).fetchall()
        conn.close()
        devices = {r[0] for r in rows}
        for d in ("desktop", "mobile", "tablet"):
            assert d in devices, f"Q4 missing device '{d}'"
        for r in rows:
            assert 0 <= r[3] <= 100, f"Bounce rate out of range: {r[3]}"

    def test_q5_returns_referrers(self):
        conn = _conn()
        rows = conn.execute(Q5).fetchall()
        conn.close()
        assert len(rows) > 0, "Q5 should return rows"
        assert all(r[0] is not None for r in rows), (
            "Q5 referrers must be non-null"
        )

    def test_q6_has_page_categories(self):
        conn = _conn()
        rows = conn.execute(Q6).fetchall()
        conn.close()
        categories = {r[0] for r in rows}
        for c in ("blog", "docs", "product", "marketing"):
            assert c in categories, f"Q6 missing category '{c}'"

    def test_q7_purchase_analysis(self):
        conn = _conn()
        rows = conn.execute(Q7).fetchall()
        conn.close()
        assert len(rows) >= 10, (
            f"Q7 should return at least 10 countries, got {len(rows)}"
        )
        for r in rows:
            country, count, total, avg, mx = r
            assert len(country) == 2, f"Country should be 2-letter code: {country}"
            assert count >= 3, f"HAVING COUNT >= 3 violated: {count}"
            assert total > 0, "Total revenue must be positive"
            assert avg > 10000, "Avg revenue must be > 10000 (filter)"
            assert mx >= avg, "Max must be >= avg"

    def test_q8_daily_pageviews(self):
        conn = _conn()
        rows = conn.execute(Q8).fetchall()
        conn.close()
        assert len(rows) >= 5, (
            f"Q8 should return at least 5 days of data, got {len(rows)}"
        )
        days = [r[0] for r in rows]
        assert all(
            d.startswith("2023-10-0") for d in days
        ), f"Q8 days should be in Oct 2023 first week: {days}"
        assert days == sorted(days), "Q8 days must be in ascending order"
        for r in rows:
            assert r[1] > 0, f"Pageviews must be positive: {r}"
            assert r[2] > 0, f"Unique users must be positive: {r}"
