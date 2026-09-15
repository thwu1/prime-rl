
import json
import psycopg2
import pytest

TENANT_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


def get_conn():
    return psycopg2.connect(dbname="eventdb", user="postgres")


def get_plan(query, analyze=False):
    conn = get_conn()
    cur = conn.cursor()
    prefix = "EXPLAIN (ANALYZE, FORMAT JSON)" if analyze else "EXPLAIN (FORMAT JSON)"
    cur.execute(f"{prefix} {query}")
    result = cur.fetchone()[0]
    conn.close()
    if isinstance(result, str):
        result = json.loads(result)
    return result[0]["Plan"]


def has_sort_node(plan):
    """Recursively check if any node in the plan tree is a Sort."""
    if plan.get("Node Type") == "Sort":
        return True
    for sub in plan.get("Plans", []):
        if has_sort_node(sub):
            return True
    return False


def find_scan_nodes(plan):
    """Find all scan-type nodes in the plan tree."""
    nodes = []
    nt = plan.get("Node Type", "")
    if "Scan" in nt:
        nodes.append(plan)
    for sub in plan.get("Plans", []):
        nodes.extend(find_scan_nodes(sub))
    return nodes


def total_rows_touched(plan):
    """Sum actual rows read (including filtered) across all scan nodes."""
    scans = find_scan_nodes(plan)
    return sum(
        n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0) for n in scans
    )


# =====================================================================
# Test: Index count constraint
# =====================================================================
def test_index_count_max_four():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM pg_indexes
        WHERE schemaname = 'app' AND tablename = 'events'
        AND indexname NOT LIKE '%pkey%'
    """
    )
    count = cur.fetchone()[0]
    conn.close()
    assert 1 <= count <= 4, f"Must have 1-4 secondary indexes, found {count}"


# =====================================================================
# Q1: Dashboard Pagination
# =====================================================================
Q1 = f"""
SELECT id, event_type, severity, created_at, status, source_system
FROM app.events
WHERE tenant_id = '{TENANT_ID}'
  AND status IN ('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS')
  AND event_type IN ('ALERT', 'INCIDENT', 'CHANGE')
ORDER BY created_at DESC
LIMIT 50
"""


def test_q1_no_sort():
    plan = get_plan(Q1)
    assert not has_sort_node(plan), "Q1: Plan must not contain a Sort node"


def test_q1_uses_index():
    plan = get_plan(Q1)
    scans = find_scan_nodes(plan)
    assert any("Index" in s.get("Node Type", "") for s in scans), (
        "Q1: Must use an Index Scan or Index Only Scan"
    )


def test_q1_efficient_scan():
    plan = get_plan(Q1, analyze=True)
    touched = total_rows_touched(plan)
    assert touched <= 600, (
        f"Q1: Touched {touched} rows for LIMIT 50, expected <=600"
    )


# =====================================================================
# Q2: Time-Range Severity Report
# =====================================================================
Q2 = f"""
SELECT id, event_type, severity, created_at, resolved_at
FROM app.events
WHERE tenant_id = '{TENANT_ID}'
  AND created_at >= '2024-03-01'::timestamptz
  AND created_at < '2024-04-01'::timestamptz
  AND severity >= 4
ORDER BY created_at ASC
"""


def test_q2_no_sort():
    plan = get_plan(Q2)
    assert not has_sort_node(plan), "Q2: Plan must not contain a Sort node"


def test_q2_created_at_in_index_cond():
    plan = get_plan(Q2)
    scans = find_scan_nodes(plan)
    assert len(scans) > 0, "Q2: No scan nodes found in plan"
    found = any("created_at" in s.get("Index Cond", "") for s in scans)
    assert found, "Q2: created_at must appear in Index Cond, not as a Filter"


# =====================================================================
# Q3: Resolution Metrics
# =====================================================================
Q3 = f"""
SELECT source_system,
       COUNT(*) as event_count,
       AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) as avg_resolution_secs
FROM app.events
WHERE tenant_id = '{TENANT_ID}'
  AND status = 'RESOLVED'
  AND resolved_at >= '2024-03-01'::timestamptz
  AND resolved_at < '2024-06-01'::timestamptz
GROUP BY source_system
"""


def test_q3_status_not_in_filter():
    plan = get_plan(Q3)
    scans = find_scan_nodes(plan)
    assert len(scans) > 0, "Q3: No scan nodes found in plan"
    for s in scans:
        filt = s.get("Filter", "")
        assert "status" not in filt, (
            f"Q3: 'status' found in Filter: {filt}"
        )


def test_q3_resolved_at_not_in_filter():
    plan = get_plan(Q3)
    scans = find_scan_nodes(plan)
    assert len(scans) > 0, "Q3: No scan nodes found in plan"
    for s in scans:
        filt = s.get("Filter", "")
        assert "resolved_at" not in filt, (
            f"Q3: 'resolved_at' found in Filter: {filt}"
        )


# =====================================================================
# Q4: Critical Unresolved Events
# =====================================================================
Q4 = f"""
SELECT id, event_type, severity, created_at, assigned_to, description
FROM app.events
WHERE tenant_id = '{TENANT_ID}'
  AND severity >= 4
  AND status NOT IN ('RESOLVED', 'CLOSED')
ORDER BY created_at ASC
LIMIT 20
"""


def test_q4_no_sort():
    plan = get_plan(Q4)
    assert not has_sort_node(plan), "Q4: Plan must not contain a Sort node"


def test_q4_efficient_scan():
    plan = get_plan(Q4, analyze=True)
    touched = total_rows_touched(plan)
    assert touched <= 500, (
        f"Q4: Touched {touched} rows for LIMIT 20, expected <=500"
    )


# =====================================================================
# Retention Delete Function
# =====================================================================
def test_retention_function_exists():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'app' AND p.proname = 'delete_old_events'
    """
    )
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1, "Function app.delete_old_events must exist"


def test_retention_deletes_old_data():
    conn = get_conn()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cutoff = "2024-01-20 00:00:00+00"

        # Count rows before cutoff
        cur.execute(
            f"SELECT COUNT(*) FROM app.events WHERE created_at < '{cutoff}'::timestamptz"
        )
        expected = cur.fetchone()[0]
        assert expected > 0, "No old data found to test retention"

        # Run retention function
        cur.execute(
            f"SELECT app.delete_old_events('{cutoff}'::timestamptz, 2000)"
        )
        deleted = cur.fetchone()[0]

        # Verify all old data was deleted
        cur.execute(
            f"SELECT COUNT(*) FROM app.events WHERE created_at < '{cutoff}'::timestamptz"
        )
        remaining = cur.fetchone()[0]
        assert remaining == 0, f"Expected 0 rows remaining after retention, got {remaining}"

        # Verify returned count matches
        assert deleted == expected, (
            f"Function returned {deleted} deleted, but {expected} rows existed before cutoff"
        )
    finally:
        conn.rollback()
        conn.close()


def test_retention_created_at_index_exists():
    """An index with created_at as leading column must exist for retention."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM pg_index i
        JOIN pg_class c ON i.indexrelid = c.oid
        JOIN pg_class t ON i.indrelid = t.oid
        JOIN pg_namespace n ON t.relnamespace = n.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
        WHERE n.nspname = 'app' AND t.relname = 'events'
        AND a.attname = 'created_at'
    """
    )
    count = cur.fetchone()[0]
    conn.close()
    assert count >= 1, (
        "Need an index with created_at as the leading column for retention deletes"
    )
