
import pytest
import psycopg2
import time


@pytest.fixture(scope="module")
def conn():
    """Connect to the postgres_air database with retry."""
    for attempt in range(5):
        try:
            c = psycopg2.connect(dbname="postgres_air", user="postgres")
            c.autocommit = True
            yield c
            c.close()
            return
        except psycopg2.OperationalError:
            time.sleep(2)
    pytest.fail("Could not connect to PostgreSQL after 5 attempts")


@pytest.fixture
def cur(conn):
    c = conn.cursor()
    yield c
    c.close()


def test_injection_resistance(cur):
    """SQL injection via p_last_name must be prevented."""
    try:
        cur.execute(
            "SELECT count(*) FROM postgres_air.select_booking_advanced("
            "p_last_name := %s)",
            ("x' OR 1=1 --",),
        )
        count = cur.fetchone()[0]
    except Exception as exc:
        pytest.fail(f"Function errored on injection payload: {exc}")

    assert count == 0, (
        f"SQL injection returned {count} rows, expected 0. "
        "The p_last_name parameter is not properly escaped."
    )


def test_apostrophe_handling(cur):
    """Names containing apostrophes must not cause SQL errors."""
    try:
        cur.execute(
            "SELECT count(*) FROM postgres_air.select_booking_advanced("
            "p_last_name := %s)",
            ("O'Brien",),
        )
        count = cur.fetchone()[0]
    except Exception as exc:
        pytest.fail(
            f"Function raised an error for name with apostrophe: {exc}"
        )
    assert count >= 0  # just needs to not crash


def test_email_date_and_semantics(cur):
    """Email + departure_date must use AND (intersection), not OR (union)."""
    # Correct count: AND semantics
    cur.execute(
        "SELECT count(DISTINCT b.booking_id) "
        "FROM postgres_air.booking b "
        "JOIN postgres_air.booking_leg bl ON bl.booking_id = b.booking_id "
        "JOIN postgres_air.flight f ON f.flight_id = bl.flight_id "
        "WHERE lower(b.email) LIKE 'john.smith%%' "
        "AND f.scheduled_departure BETWEEN '2024-06-15'::date "
        "    AND '2024-06-15'::date + interval '1 day'"
    )
    correct_and_count = cur.fetchone()[0]

    # Incorrect count: OR semantics
    cur.execute(
        "SELECT count(DISTINCT b.booking_id) "
        "FROM postgres_air.booking b "
        "JOIN postgres_air.booking_leg bl ON bl.booking_id = b.booking_id "
        "JOIN postgres_air.flight f ON f.flight_id = bl.flight_id "
        "WHERE lower(b.email) LIKE 'john.smith%%' "
        "OR f.scheduled_departure BETWEEN '2024-06-15'::date "
        "   AND '2024-06-15'::date + interval '1 day'"
    )
    or_count = cur.fetchone()[0]

    # Sanity: OR must produce strictly more rows than AND
    assert or_count > correct_and_count, (
        f"Sanity check failed: OR count ({or_count}) should exceed "
        f"AND count ({correct_and_count})"
    )

    # Function result
    cur.execute(
        "SELECT count(DISTINCT out_booking_id) "
        "FROM postgres_air.select_booking_advanced("
        "    p_email := 'john.smith', p_departure_date := '2024-06-15')"
    )
    func_count = cur.fetchone()[0]

    assert func_count == correct_and_count, (
        f"Function returned {func_count} rows but correct AND count is "
        f"{correct_and_count} (OR count would be {or_count}). "
        "The departure_date condition is likely OR'd instead of AND'd."
    )


def test_case_insensitive_email(cur):
    """Email search must use lower() for case-insensitive matching."""
    cur.execute(
        "INSERT INTO postgres_air.booking "
        "(booking_ref, booking_name, email, update_ts) "
        "VALUES ('ZZTEST', 'TestUser', 'JOHN.SMITH.UPPER@gmail.com', now()) "
        "RETURNING booking_id"
    )
    test_id = cur.fetchone()[0]

    try:
        cur.execute(
            "SELECT count(*) FROM postgres_air.select_booking_advanced("
            "p_email := 'john.smith.upper')"
        )
        count = cur.fetchone()[0]
        assert count >= 1, (
            f"Case-insensitive email search returned {count} rows, "
            "expected >= 1. The function likely uses email instead of "
            "lower(email)."
        )
    finally:
        cur.execute(
            "DELETE FROM postgres_air.booking WHERE booking_id = %s",
            (test_id,),
        )


def test_email_index_btree_pattern_ops(cur):
    """Email index must be btree with text_pattern_ops for prefix LIKE queries."""
    cur.execute("""
        SELECT am.amname, pg_get_indexdef(c.oid)
        FROM pg_class c
        JOIN pg_am am ON am.oid = c.relam
        JOIN pg_index i ON i.indexrelid = c.oid
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'postgres_air'
          AND t.relname = 'booking'
          AND pg_get_indexdef(c.oid) LIKE '%%lower(email)%%'
    """)
    rows = cur.fetchall()
    assert len(rows) > 0, (
        "No index on lower(email) found on postgres_air.booking"
    )
    btree_rows = [r for r in rows if r[0] == 'btree']
    assert len(btree_rows) > 0, (
        f"Index on lower(email) uses access method "
        f"'{rows[0][0]}', but must be btree for LIKE prefix matching"
    )
    pattern_ops = [r for r in btree_rows if 'text_pattern_ops' in r[1]]
    assert len(pattern_ops) > 0, (
        "btree index on lower(email) must use text_pattern_ops "
        "operator class for prefix matching"
    )


def test_email_plan_uses_index(cur):
    """lower(email) prefix search must be able to use the expression index."""
    cur.execute("SET enable_seqscan = off")
    try:
        cur.execute(
            "EXPLAIN (FORMAT TEXT) "
            "SELECT * FROM postgres_air.booking "
            "WHERE lower(email) LIKE 'john.smith%%'"
        )
        plan = "\n".join(row[0] for row in cur.fetchall())
    finally:
        cur.execute("RESET enable_seqscan")

    assert "Seq Scan" not in plan, (
        f"Expected index scan, but got:\n{plan}"
    )


def test_conditional_join_null_columns(cur):
    """Email-only search must return NULL for flight/passenger columns."""
    cur.execute(
        "SELECT out_booking_id, out_email, "
        "       out_departure_airport, out_passenger_last_name "
        "FROM postgres_air.select_booking_advanced("
        "    p_email := 'john.smith0@g') "
        "LIMIT 5"
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "Email-only search returned no rows"

    for row in rows:
        assert row[0] is not None, "booking_id must not be NULL"
        assert row[1] is not None, "email must not be NULL"
        assert row[2] is None, (
            f"departure_airport should be NULL for email-only search, "
            f"got '{row[2]}'"
        )
        assert row[3] is None, (
            f"passenger_last_name should be NULL for email-only search, "
            f"got '{row[3]}'"
        )


def test_departure_airport_correctness(cur):
    """Departure airport filter must return the correct booking count."""
    cur.execute(
        "SELECT count(DISTINCT b.booking_id) "
        "FROM postgres_air.booking b "
        "JOIN postgres_air.booking_leg bl ON bl.booking_id = b.booking_id "
        "JOIN postgres_air.flight f ON f.flight_id = bl.flight_id "
        "WHERE f.departure_airport = 'JFK'"
    )
    expected = cur.fetchone()[0]

    cur.execute(
        "SELECT count(DISTINCT out_booking_id) "
        "FROM postgres_air.select_booking_advanced("
        "    p_departure_airport := 'JFK')"
    )
    actual = cur.fetchone()[0]

    assert expected > 0, "Sanity: should have bookings departing JFK"
    assert actual == expected, (
        f"Departure airport filter: function returned {actual}, "
        f"expected {expected}"
    )
