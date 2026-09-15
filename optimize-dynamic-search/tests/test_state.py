
"""
Tests for PostgreSQL booking search optimization task.

Verifies:
  - Optimized function exists and uses dynamic SQL
  - Proper SQL injection prevention
  - Required indexes exist
  - Result correctness across multiple parameter combinations
  - Index scans are used for selective queries
"""

import subprocess
import os
import re
import pytest


def run_sql(sql, timeout=120):
    """Execute SQL against the postgres_air database and return output."""
    result = subprocess.run(
        ['psql', '-U', 'postgres', '-d', 'postgres_air',
         '-t', '-A', '-F', '|', '-c', sql],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0 and result.stderr:
        # Allow warnings but fail on errors
        if 'ERROR' in result.stderr:
            raise RuntimeError(f"SQL error: {result.stderr}")
    return result.stdout.strip()


def run_sql_rows(sql, timeout=120):
    """Execute SQL and return list of non-empty rows."""
    output = run_sql(sql, timeout)
    if not output:
        return []
    return [row for row in output.split('\n') if row.strip()]


# ============================================================
# 1. FUNCTION EXISTENCE AND STRUCTURE
# ============================================================

class TestFunctionStructure:

    def test_optimization_file_exists(self):
        """optimization.sql was created."""
        assert os.path.exists('/app/optimization.sql'), \
            "/app/optimization.sql not found"

    def test_optimized_function_exists(self):
        """search_bookings_optimized function exists in the database."""
        result = run_sql(
            "SELECT proname FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized';"
        )
        assert 'search_bookings_optimized' in result, \
            "Function search_bookings_optimized not found in pg_proc"

    def test_function_uses_dynamic_sql(self):
        """Function body contains EXECUTE (dynamic SQL)."""
        result = run_sql(
            "SELECT prosrc FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized';"
        )
        assert result, "Could not retrieve function source"
        assert 'execute' in result.lower(), \
            "Function does not use dynamic SQL (no EXECUTE keyword found)"

    def test_function_uses_safe_escaping(self):
        """Function uses quote_literal() or format() for injection prevention."""
        result = run_sql(
            "SELECT prosrc FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized';"
        )
        assert result, "Could not retrieve function source"
        uses_quote_literal = 'quote_literal' in result.lower()
        uses_format = 'format(' in result.lower() or '%L' in result
        assert uses_quote_literal or uses_format, \
            "Function does not use quote_literal() or format() for safe SQL escaping"

    def test_function_has_conditional_joins(self):
        """Function conditionally includes JOINs based on parameter nullity."""
        result = run_sql(
            "SELECT prosrc FROM pg_proc "
            "WHERE proname = 'search_bookings_optimized';"
        )
        assert result, "Could not retrieve function source"
        src_lower = result.lower()
        # Must have conditional logic checking parameters before adding joins
        has_null_check = 'is not null' in src_lower
        has_join_ref = 'join' in src_lower
        assert has_null_check and has_join_ref, \
            "Function does not appear to conditionally include JOINs " \
            "(expected IS NOT NULL checks and JOIN references)"

    def test_function_return_type(self):
        """Function returns the correct column types matching original."""
        result = run_sql(
            "SELECT pg_get_function_result(p.oid) "
            "FROM pg_proc p WHERE proname = 'search_bookings_optimized';"
        )
        assert result, "Could not retrieve function return type"
        result_lower = result.lower()
        assert 'booking_id' in result_lower, "Return type missing booking_id"
        assert 'booking_ref' in result_lower, "Return type missing booking_ref"
        assert 'email' in result_lower, "Return type missing email"


# ============================================================
# 2. INDEX EXISTENCE
# ============================================================

class TestIndexes:

    def test_email_expression_index(self):
        """Expression index on lower(email) exists for booking table."""
        result = run_sql(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'booking' "
            "AND indexdef ILIKE '%lower%' AND indexdef ILIKE '%email%';"
        )
        assert result, "No expression index on lower(email) found on booking table"
        assert 'lower' in result.lower() and 'email' in result.lower(), \
            f"Index definition doesn't match expected pattern: {result}"

    def test_flight_composite_index(self):
        """Composite index on flight(departure_airport, ..., scheduled_departure)."""
        result = run_sql(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'flight' "
            "AND indexdef ILIKE '%departure_airport%' "
            "AND indexdef ILIKE '%scheduled_departure%';"
        )
        assert result, \
            "No composite index with departure_airport and scheduled_departure on flight"

    def test_passenger_name_index(self):
        """Index on passenger last_name (preferably expression index)."""
        result = run_sql(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'passenger' "
            "AND indexdef ILIKE '%last_name%';"
        )
        assert result, "No index on passenger(last_name) found"

    def test_booking_leg_booking_id_index(self):
        """Index on booking_leg(booking_id) for efficient joins."""
        result = run_sql(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'booking_leg' "
            "AND indexdef ILIKE '%booking_id%' "
            "AND indexname NOT LIKE '%pkey%';"
        )
        assert result, "No index on booking_leg(booking_id) found"

    def test_booking_leg_flight_id_index(self):
        """Index on booking_leg(flight_id) for efficient joins."""
        result = run_sql(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'booking_leg' "
            "AND indexdef ILIKE '%flight_id%';"
        )
        assert result, "No index on booking_leg(flight_id) found"


# ============================================================
# 3. RESULT CORRECTNESS
# ============================================================

class TestResultCorrectness:
    """Compare results between original and optimized functions."""

    def _compare_results(self, params_str, limit=100):
        """Run both functions with same params and compare booking_ids."""
        original = run_sql(
            f"SELECT booking_id FROM search_bookings_full({params_str}) "
            f"ORDER BY booking_id LIMIT {limit};"
        )
        optimized = run_sql(
            f"SELECT booking_id FROM search_bookings_optimized({params_str}) "
            f"ORDER BY booking_id LIMIT {limit};"
        )
        orig_ids = set(original.split('\n')) if original else set()
        opt_ids = set(optimized.split('\n')) if optimized else set()
        assert orig_ids == opt_ids, (
            f"Results differ for params: {params_str}\n"
            f"Original count: {len(orig_ids)}, Optimized count: {len(opt_ids)}\n"
            f"In original but not optimized: {orig_ids - opt_ids}\n"
            f"In optimized but not original: {opt_ids - orig_ids}"
        )
        return orig_ids

    def test_results_email_only(self):
        """Results match when searching by email prefix only."""
        ids = self._compare_results("p_email := 'john.smith0'")
        assert len(ids) > 0, "Email search returned no results"

    def test_results_departure_airport_only(self):
        """Results match when searching by departure airport only."""
        ids = self._compare_results("p_departure_airport := 'JFK'")
        assert len(ids) > 0, "Departure airport search returned no results"

    def test_results_flight_status_only(self):
        """Results match when searching by flight status only."""
        ids = self._compare_results("p_flight_status := 'Canceled'")
        assert len(ids) > 0, "Flight status search returned no results"

    def test_results_departure_date_only(self):
        """Results match when searching by departure date only."""
        ids = self._compare_results("p_departure_date := '2023-03-15'")
        assert len(ids) > 0, "Date search returned no results"

    def test_results_passenger_name_only(self):
        """Results match when searching by passenger last name only."""
        ids = self._compare_results("p_passenger_last_name := 'Smith'")
        assert len(ids) > 0, "Passenger name search returned no results"

    def test_results_combined_email_and_passenger(self):
        """Results match with email + passenger name (tests conditional JOINs)."""
        ids = self._compare_results(
            "p_email := 'john', p_passenger_last_name := 'Smith'"
        )
        assert len(ids) > 0, "Combined email+passenger search returned no results"

    def test_results_combined_airport_and_status(self):
        """Results match with departure airport + flight status."""
        ids = self._compare_results(
            "p_departure_airport := 'MEX', p_flight_status := 'Canceled'"
        )
        assert len(ids) > 0, "Combined airport+status search returned no results"


# ============================================================
# 4. QUERY PLAN VERIFICATION
# ============================================================

class TestQueryPlans:
    """Verify that indexes are used for selective queries."""

    def test_index_scan_for_email_query(self):
        """EXPLAIN shows index scan for email prefix search."""
        result = run_sql(
            "EXPLAIN (FORMAT TEXT) "
            "SELECT DISTINCT b.booking_id FROM booking b "
            "WHERE lower(b.email) LIKE 'john.smith0%';"
        )
        assert result, "EXPLAIN returned no output"
        result_lower = result.lower()
        has_index = ('index' in result_lower and 'scan' in result_lower)
        assert has_index, (
            f"Expected Index Scan for email prefix query, got:\n{result}"
        )

    def test_index_scan_for_flight_query(self):
        """EXPLAIN shows index scan for flight search by route and date."""
        result = run_sql(
            "EXPLAIN (FORMAT TEXT) "
            "SELECT f.flight_id FROM flight f "
            "WHERE departure_airport = 'JFK' "
            "AND scheduled_departure >= '2023-03-15' "
            "AND scheduled_departure < '2023-03-16';"
        )
        assert result, "EXPLAIN returned no output"
        result_lower = result.lower()
        has_index = ('index' in result_lower and 'scan' in result_lower)
        assert has_index, (
            f"Expected Index Scan for flight route+date query, got:\n{result}"
        )

    def test_index_scan_for_passenger_name(self):
        """EXPLAIN shows index scan for passenger name prefix search."""
        result = run_sql(
            "EXPLAIN (FORMAT TEXT) "
            "SELECT p.passenger_id FROM passenger p "
            "WHERE lower(p.last_name) LIKE 'smith%';"
        )
        assert result, "EXPLAIN returned no output"
        result_lower = result.lower()
        has_index = ('index' in result_lower)
        assert has_index, (
            f"Expected some form of index usage for passenger name query, got:\n{result}"
        )
