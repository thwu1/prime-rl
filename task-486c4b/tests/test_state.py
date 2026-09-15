
import pytest
import psycopg2
import psycopg2.errors


@pytest.fixture(scope="module")
def conn():
    """Database connection shared across all tests."""
    c = psycopg2.connect(dbname="postgres_air", user="postgres", host="localhost")
    c.autocommit = True
    yield c
    c.close()


def get_all_plan_nodes(plan):
    """Recursively extract all nodes from a PostgreSQL EXPLAIN JSON plan."""
    nodes = []
    if isinstance(plan, dict):
        if "Node Type" in plan:
            nodes.append(
                {
                    "type": plan["Node Type"],
                    "relation": plan.get("Relation Name", ""),
                    "index": plan.get("Index Name", ""),
                }
            )
        if "Plans" in plan:
            for child in plan["Plans"]:
                nodes.extend(get_all_plan_nodes(child))
        if "Plan" in plan and isinstance(plan["Plan"], dict):
            nodes.extend(get_all_plan_nodes(plan["Plan"]))
    elif isinstance(plan, list):
        for item in plan:
            nodes.extend(get_all_plan_nodes(item))
    return nodes


# ---------------------------------------------------------------------------
# 1. Function existence and signature
# ---------------------------------------------------------------------------
class TestFunctionExists:

    def test_optimized_function_exists(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_proc WHERE proname = 'search_bookings_optimized'"
        )
        assert cur.fetchone()[0] >= 1, "Function search_bookings_optimized does not exist"
        cur.close()

    def test_function_parameter_count(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT pronargs FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized' LIMIT 1"
        )
        row = cur.fetchone()
        assert row is not None, "Function not found"
        assert row[0] == 6, f"Expected 6 parameters, got {row[0]}"
        cur.close()


# ---------------------------------------------------------------------------
# 2. Implementation quality
# ---------------------------------------------------------------------------
class TestFunctionImplementation:

    def test_uses_dynamic_sql(self, conn):
        """Function must use dynamic SQL (EXECUTE keyword)."""
        cur = conn.cursor()
        cur.execute(
            "SELECT prosrc FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized' LIMIT 1"
        )
        body = cur.fetchone()[0].upper()
        cur.close()
        assert "EXECUTE" in body, "Function must use dynamic SQL with EXECUTE"

    def test_sql_injection_prevention(self, conn):
        """Function must use quote_literal / format for safe SQL construction."""
        cur = conn.cursor()
        cur.execute(
            "SELECT prosrc FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized' LIMIT 1"
        )
        body = cur.fetchone()[0].lower()
        cur.close()
        ok = (
            "quote_literal" in body
            or "format(" in body
            or "quote_ident" in body
            or "%l" in body
        )
        assert ok, "Function must use quote_literal(), format(), or similar"

    def test_null_guard(self, conn):
        """All-NULL parameters must raise an exception."""
        cur = conn.cursor()
        raised = False
        try:
            cur.execute("SELECT * FROM search_bookings_optimized()")
        except psycopg2.Error:
            raised = True
        cur.close()
        assert raised, "Function should raise an exception when all params are NULL"


# ---------------------------------------------------------------------------
# 3. Result correctness
# ---------------------------------------------------------------------------
class TestResultCorrectness:

    @staticmethod
    def _compare(conn, params_sql):
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM search_bookings_full({params_sql}) "
            "ORDER BY 1,2,3,4,5,6,7,8,9"
        )
        expected = cur.fetchall()
        cur.execute(
            f"SELECT * FROM search_bookings_optimized({params_sql}) "
            "ORDER BY 1,2,3,4,5,6,7,8,9"
        )
        actual = cur.fetchall()
        cur.close()
        return expected, actual

    def test_email_search(self, conn):
        expected, actual = self._compare(conn, "p_email := 'james.smith20'")
        assert len(actual) > 0, "Should return results for email search"
        assert actual == expected, "Email search results differ"

    def test_departure_airport_search(self, conn):
        expected, actual = self._compare(conn, "p_dep_airport := 'ORD'")
        assert len(actual) > 0, "Should return results for departure airport"
        assert actual == expected, "Departure airport results differ"

    def test_arrival_airport_search(self, conn):
        expected, actual = self._compare(conn, "p_arr_airport := 'JFK'")
        assert len(actual) > 0, "Should return results for arrival airport"
        assert actual == expected, "Arrival airport results differ"

    def test_departure_date_search(self, conn):
        expected, actual = self._compare(conn, "p_dep_date := '2020-07-15'")
        assert len(actual) > 0, "Should return results for departure date"
        assert actual == expected, "Departure date results differ"

    def test_passenger_name_search(self, conn):
        expected, actual = self._compare(conn, "p_passenger_last_name := 'Smith'")
        assert len(actual) > 0, "Should return results for passenger name"
        assert actual == expected, "Passenger name results differ"

    def test_passport_country_search(self, conn):
        expected, actual = self._compare(conn, "p_passport_country := 'US'")
        assert len(actual) > 0, "Should return results for passport country"
        assert actual == expected, "Passport country results differ"

    def test_multi_param_search(self, conn):
        expected, actual = self._compare(
            conn, "p_dep_airport := 'ORD', p_passenger_last_name := 'Smith'"
        )
        assert actual == expected, "Multi-param results differ"

    def test_email_and_airport_search(self, conn):
        expected, actual = self._compare(
            conn, "p_email := 'james.smith', p_dep_airport := 'ORD'"
        )
        assert actual == expected, "Email+airport results differ"


# ---------------------------------------------------------------------------
# 4. Required indexes
# ---------------------------------------------------------------------------
class TestIndexes:

    def test_email_index_exists(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'booking' "
            "AND (indexdef LIKE '%%lower(email)%%' "
            "     OR indexdef LIKE '%%lower((email)%%')"
        )
        assert cur.fetchone()[0] > 0, "Missing index on booking(lower(email))"
        cur.close()

    def test_flight_departure_index_exists(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'flight' "
            "AND indexdef LIKE '%%departure_airport%%'"
        )
        assert cur.fetchone()[0] > 0, "Missing index on flight(departure_airport)"
        cur.close()

    def test_passenger_lastname_index_exists(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'passenger' "
            "AND (indexdef LIKE '%%lower(last_name)%%' "
            "     OR indexdef LIKE '%%lower((last_name)%%' "
            "     OR indexdef LIKE '%%last_name%%')"
        )
        cnt = cur.fetchone()[0]
        cur.close()
        # Must have more than just the PK index
        assert cnt > 0, "Missing index on passenger for last name searches"

    def test_custom_field_composite_index(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'custom_field' "
            "AND indexdef LIKE '%%custom_field_name%%' "
            "AND indexdef LIKE '%%custom_field_value%%'"
        )
        assert cur.fetchone()[0] > 0, (
            "Missing composite index on custom_field(name, value)"
        )
        cur.close()


# ---------------------------------------------------------------------------
# 5. Execution plan quality
# ---------------------------------------------------------------------------
class TestPlanQuality:

    @staticmethod
    def _seq_scan_tables(conn, query):
        cur = conn.cursor()
        cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
        plan_json = cur.fetchone()[0]
        cur.close()
        nodes = get_all_plan_nodes(plan_json[0])
        return {
            n["relation"]
            for n in nodes
            if n["type"] == "Seq Scan" and n["relation"]
        }

    def test_email_query_plan(self, conn):
        """Email prefix query must not Seq Scan booking."""
        q = (
            "SELECT DISTINCT b.booking_id, b.booking_ref, b.booking_name, "
            "b.email, f.departure_airport, f.arrival_airport, "
            "f.scheduled_departure, p.last_name, p.first_name "
            "FROM booking b "
            "JOIN booking_leg bl ON bl.booking_id = b.booking_id "
            "JOIN flight f ON f.flight_id = bl.flight_id "
            "JOIN passenger p ON p.booking_id = b.booking_id "
            "WHERE lower(b.email) LIKE 'james.smith20%%'"
        )
        ss = self._seq_scan_tables(conn, q)
        assert "booking" not in ss, f"Booking Seq Scan detected: {ss}"

    def test_departure_airport_plan(self, conn):
        """Departure airport query must not Seq Scan flight."""
        q = (
            "SELECT DISTINCT b.booking_id, b.booking_ref, b.booking_name, "
            "b.email, f.departure_airport, f.arrival_airport, "
            "f.scheduled_departure, p.last_name, p.first_name "
            "FROM booking b "
            "JOIN booking_leg bl ON bl.booking_id = b.booking_id "
            "JOIN flight f ON f.flight_id = bl.flight_id "
            "JOIN passenger p ON p.booking_id = b.booking_id "
            "WHERE f.departure_airport = 'ORD'"
        )
        ss = self._seq_scan_tables(conn, q)
        assert "flight" not in ss, f"Flight Seq Scan detected: {ss}"

    def test_passport_country_plan(self, conn):
        """Passport country query must not Seq Scan custom_field."""
        q = (
            "SELECT DISTINCT b.booking_id, b.booking_ref, b.booking_name, "
            "b.email, f.departure_airport, f.arrival_airport, "
            "f.scheduled_departure, p.last_name, p.first_name "
            "FROM booking b "
            "JOIN booking_leg bl ON bl.booking_id = b.booking_id "
            "JOIN flight f ON f.flight_id = bl.flight_id "
            "JOIN passenger p ON p.booking_id = b.booking_id "
            "JOIN custom_field cf ON cf.passenger_id = p.passenger_id "
            "AND cf.custom_field_name = 'passport_country' "
            "WHERE cf.custom_field_value = 'US'"
        )
        ss = self._seq_scan_tables(conn, q)
        assert "custom_field" not in ss, f"custom_field Seq Scan detected: {ss}"
