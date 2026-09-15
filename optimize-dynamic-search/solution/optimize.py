#!/usr/bin/env python3

"""
Analyze the postgres_air database and generate an optimized version of
search_bookings_full using dynamic SQL, proper indexes, and SARGable
date comparisons.
"""

import subprocess
import sys


def run_sql(sql):
    """Execute SQL against postgres_air and return output."""
    result = subprocess.run(
        ['psql', '-U', 'postgres', '-d', 'postgres_air',
         '-t', '-A', '-F', '|', '-c', sql],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def analyze_database():
    """Inspect current database state to inform optimization strategy."""

    print("=== Analyzing postgres_air database ===\n")

    # 1. Get the original function source
    func_src = run_sql(
        "SELECT prosrc FROM pg_proc WHERE proname = 'search_bookings_full';"
    )
    print("Original function source (excerpt):")
    print(func_src[:300], "...\n")

    # 2. Check existing indexes (beyond PKs)
    indexes = run_sql(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' "
        "AND indexname NOT LIKE '%pkey%' "
        "ORDER BY tablename, indexname;"
    )
    print(f"Existing secondary indexes: {indexes if indexes else 'NONE'}\n")

    # 3. Check table sizes for selectivity estimation
    for table in ['booking', 'booking_leg', 'flight', 'passenger']:
        count = run_sql(f"SELECT count(*) FROM {table};")
        print(f"  {table}: {count} rows")

    # 4. Check database collation
    collation = run_sql(
        "SELECT datcollate FROM pg_database WHERE datname = 'postgres_air';"
    )
    print(f"\nDatabase collation: {collation}")
    needs_pattern_ops = 'utf' in collation.lower() or collation not in ('C', 'POSIX')
    print(f"Needs text_pattern_ops for LIKE: {needs_pattern_ops}")

    # 5. Identify anti-patterns in original function
    print("\n=== Identified anti-patterns ===")
    issues = []
    if 'JOIN booking_leg' in func_src and 'JOIN flight' in func_src and 'JOIN passenger' in func_src:
        issues.append("Unconditional JOINs: all 3 tables always joined regardless of parameters")
    if '::date' in func_src:
        issues.append("Date cast anti-pattern: scheduled_departure::date prevents index usage")
    if 'quote_literal' not in func_src.lower() and 'format(' not in func_src.lower():
        issues.append("No dynamic SQL: uses static SQL with OR-based parameter handling")

    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")

    return needs_pattern_ops


def generate_optimization_sql(needs_pattern_ops):
    """Generate the optimization SQL based on analysis."""

    pattern_ops = " text_pattern_ops" if needs_pattern_ops else ""

    sql = f"""-- PostgreSQL Query Optimization for postgres_air
-- Addresses: unconditional JOINs, missing indexes, date cast anti-pattern

-- ============================================================
-- INDEXES
-- ============================================================

-- Expression index for case-insensitive email prefix search
-- Uses text_pattern_ops for LIKE prefix queries under non-C collation
CREATE INDEX IF NOT EXISTS idx_booking_email_lower
    ON booking (lower(email){pattern_ops});

-- Composite index for flight route + date range queries
CREATE INDEX IF NOT EXISTS idx_flight_dep_arr_sched
    ON flight (departure_airport, arrival_airport, scheduled_departure);

-- Single-column index on flight status for status-only filters
CREATE INDEX IF NOT EXISTS idx_flight_status
    ON flight (status);

-- Expression index for case-insensitive passenger last name prefix search
CREATE INDEX IF NOT EXISTS idx_passenger_last_name_lower
    ON passenger (lower(last_name){pattern_ops});

-- Foreign key indexes on booking_leg for efficient hash/merge joins
CREATE INDEX IF NOT EXISTS idx_booking_leg_booking_id
    ON booking_leg (booking_id);

CREATE INDEX IF NOT EXISTS idx_booking_leg_flight_id
    ON booking_leg (flight_id);

-- ============================================================
-- OPTIMIZED FUNCTION: Dynamic SQL with conditional JOINs
-- ============================================================

CREATE OR REPLACE FUNCTION search_bookings_optimized(
    p_email text DEFAULT NULL,
    p_departure_airport text DEFAULT NULL,
    p_arrival_airport text DEFAULT NULL,
    p_departure_date date DEFAULT NULL,
    p_passenger_last_name text DEFAULT NULL,
    p_flight_status text DEFAULT NULL
) RETURNS TABLE(
    booking_id integer,
    booking_ref text,
    booking_name text,
    account_id integer,
    email text
) AS $func$
DECLARE
    v_sql text;
    v_where text;
    v_need_flight boolean := false;
    v_need_passenger boolean := false;
BEGIN
    -- Base query: always start from booking table
    v_sql := 'SELECT DISTINCT b.booking_id, b.booking_ref, '
             'b.booking_name, b.account_id, b.email FROM booking b';

    -- Determine which tables must be joined based on non-NULL parameters
    IF p_departure_airport IS NOT NULL
       OR p_arrival_airport IS NOT NULL
       OR p_departure_date IS NOT NULL
       OR p_flight_status IS NOT NULL THEN
        v_need_flight := true;
    END IF;

    IF p_passenger_last_name IS NOT NULL THEN
        v_need_passenger := true;
    END IF;

    -- Conditionally add JOINs only when the corresponding parameters
    -- actually require data from those tables
    IF v_need_flight THEN
        v_sql := v_sql || ' JOIN booking_leg bl ON bl.booking_id = b.booking_id'
                       || ' JOIN flight f ON f.flight_id = bl.flight_id';
    END IF;

    IF v_need_passenger THEN
        v_sql := v_sql || ' JOIN passenger p ON p.booking_id = b.booking_id';
    END IF;

    -- Build WHERE clause with proper escaping via quote_literal()
    -- NOTE: v_where starts as NULL so concat_ws skips it on first call,
    -- avoiding a leading ' AND ' that would produce invalid SQL.

    IF p_email IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'lower(b.email) LIKE ' || quote_literal(lower(p_email) || '%'));
    END IF;

    IF p_departure_airport IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.departure_airport = ' || quote_literal(p_departure_airport));
    END IF;

    IF p_arrival_airport IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.arrival_airport = ' || quote_literal(p_arrival_airport));
    END IF;

    -- Use range comparison instead of ::date cast for index compatibility
    IF p_departure_date IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.scheduled_departure >= ' || quote_literal(p_departure_date)
            || '::date AND f.scheduled_departure < ('
            || quote_literal(p_departure_date)
            || '::date + interval ''1 day'')');
    END IF;

    IF p_passenger_last_name IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'lower(p.last_name) LIKE '
            || quote_literal(lower(p_passenger_last_name) || '%'));
    END IF;

    IF p_flight_status IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.status = ' || quote_literal(p_flight_status));
    END IF;

    -- Append WHERE clause if any conditions were added
    IF v_where IS NOT NULL THEN
        v_sql := v_sql || ' WHERE ' || v_where;
    END IF;

    -- Execute the dynamically constructed query
    RETURN QUERY EXECUTE v_sql;
END;
$func$ LANGUAGE plpgsql;

-- Update statistics so the planner uses the new indexes effectively
ANALYZE;
"""
    return sql


def main():
    needs_pattern_ops = analyze_database()
    optimization_sql = generate_optimization_sql(needs_pattern_ops)

    output_path = '/app/optimization.sql'
    with open(output_path, 'w') as f:
        f.write(optimization_sql)

    print(f"\nOptimization SQL written to {output_path}")
    print(f"File size: {len(optimization_sql)} bytes")


if __name__ == '__main__':
    main()
