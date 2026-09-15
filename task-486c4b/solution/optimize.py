#!/usr/bin/env python3

"""Analyze postgres_air schema and generate optimized search function + indexes."""

import psycopg2


def main():
    conn = psycopg2.connect(dbname="postgres_air", user="postgres", host="localhost")
    conn.autocommit = True
    cur = conn.cursor()

    # ---- Analyze existing indexes to determine what is missing ----
    cur.execute(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' ORDER BY tablename, indexname"
    )
    existing = cur.fetchall()

    # ---- Read the original function signature for reference ----
    cur.execute(
        "SELECT proargnames, proargtypes "
        "FROM pg_proc WHERE proname = 'search_bookings_full' LIMIT 1"
    )
    func_info = cur.fetchone()
    param_names = func_info[0] if func_info else []

    # ---- Determine which indexes are needed ----
    index_stmts = []

    has_email_idx = any(
        "lower(email)" in r[2] or "lower((email)" in r[2]
        for r in existing if r[0] == "booking"
    )
    if not has_email_idx:
        index_stmts.append(
            "CREATE INDEX idx_booking_email_lower_pattern "
            "ON booking (lower(email) text_pattern_ops);"
        )

    has_dep_idx = any(
        "departure_airport" in r[2] for r in existing if r[0] == "flight"
    )
    if not has_dep_idx:
        index_stmts.append(
            "CREATE INDEX idx_flight_departure_airport "
            "ON flight (departure_airport);"
        )

    has_arr_idx = any(
        "arrival_airport" in r[2] and "departure" not in r[2]
        for r in existing if r[0] == "flight"
    )
    if not has_arr_idx:
        index_stmts.append(
            "CREATE INDEX idx_flight_arrival_airport "
            "ON flight (arrival_airport);"
        )

    has_sched_idx = any(
        "scheduled_departure" in r[2] for r in existing if r[0] == "flight"
    )
    if not has_sched_idx:
        index_stmts.append(
            "CREATE INDEX idx_flight_scheduled_departure "
            "ON flight (scheduled_departure);"
        )

    # Composite index for combined airport + date searches
    index_stmts.append(
        "CREATE INDEX IF NOT EXISTS idx_flight_dep_arr_sched "
        "ON flight (departure_airport, arrival_airport, scheduled_departure);"
    )

    has_pname_idx = any(
        "last_name" in r[2] for r in existing if r[0] == "passenger"
    )
    if not has_pname_idx:
        index_stmts.append(
            "CREATE INDEX idx_passenger_last_name_lower_pattern "
            "ON passenger (lower(last_name) text_pattern_ops);"
        )

    has_cf_composite = any(
        "custom_field_name" in r[2] and "custom_field_value" in r[2]
        for r in existing if r[0] == "custom_field"
    )
    if not has_cf_composite:
        index_stmts.append(
            "CREATE INDEX idx_cf_name_value_passenger "
            "ON custom_field (custom_field_name, custom_field_value, passenger_id);"
        )

    # ---- Write indexes.sql ----
    with open("/app/indexes.sql", "w") as f:
        f.write("-- Auto-generated indexes for optimized booking search\n\n")
        for stmt in index_stmts:
            f.write(stmt + "\n")

    # ---- Generate the optimized function ----
    func_sql = r"""CREATE OR REPLACE FUNCTION search_bookings_optimized(
    p_email text DEFAULT NULL,
    p_dep_airport text DEFAULT NULL,
    p_arr_airport text DEFAULT NULL,
    p_dep_date date DEFAULT NULL,
    p_passenger_last_name text DEFAULT NULL,
    p_passport_country text DEFAULT NULL
) RETURNS TABLE (
    booking_id int,
    booking_ref text,
    booking_name text,
    email text,
    departure_airport char(3),
    arrival_airport char(3),
    scheduled_departure timestamptz,
    passenger_last_name text,
    passenger_first_name text
) AS $func$
DECLARE
    v_sql text;
    v_where text := '';
BEGIN
    -- Guard: at least one search parameter must be provided
    IF p_email IS NULL AND p_dep_airport IS NULL AND p_arr_airport IS NULL
       AND p_dep_date IS NULL AND p_passenger_last_name IS NULL
       AND p_passport_country IS NULL THEN
        RAISE EXCEPTION 'At least one search parameter must be provided';
    END IF;

    -- Base query: always need booking, booking_leg, flight, passenger for output
    v_sql := 'SELECT DISTINCT b.booking_id, b.booking_ref, b.booking_name, '
          || 'b.email, f.departure_airport, f.arrival_airport, '
          || 'f.scheduled_departure, p.last_name, p.first_name '
          || 'FROM booking b '
          || 'JOIN booking_leg bl ON bl.booking_id = b.booking_id '
          || 'JOIN flight f ON f.flight_id = bl.flight_id '
          || 'JOIN passenger p ON p.booking_id = b.booking_id';

    -- Conditionally join custom_field only when passport_country is searched
    IF p_passport_country IS NOT NULL THEN
        v_sql := v_sql
              || ' JOIN custom_field cf ON cf.passenger_id = p.passenger_id'
              || ' AND cf.custom_field_name = ' || quote_literal('passport_country');
    END IF;

    -- Build WHERE clauses dynamically (no IS NULL OR anti-pattern)
    IF p_email IS NOT NULL THEN
        v_where := v_where || ' AND lower(b.email) LIKE '
                || quote_literal(lower(p_email) || '%');
    END IF;

    IF p_dep_airport IS NOT NULL THEN
        v_where := v_where || ' AND f.departure_airport = '
                || quote_literal(p_dep_airport);
    END IF;

    IF p_arr_airport IS NOT NULL THEN
        v_where := v_where || ' AND f.arrival_airport = '
                || quote_literal(p_arr_airport);
    END IF;

    IF p_dep_date IS NOT NULL THEN
        v_where := v_where
                || ' AND f.scheduled_departure >= '
                || quote_literal(p_dep_date) || '::date'
                || ' AND f.scheduled_departure < ('
                || quote_literal(p_dep_date) || '::date + interval ''1 day'')';
    END IF;

    IF p_passenger_last_name IS NOT NULL THEN
        v_where := v_where || ' AND lower(p.last_name) LIKE '
                || quote_literal(lower(p_passenger_last_name) || '%');
    END IF;

    IF p_passport_country IS NOT NULL THEN
        v_where := v_where || ' AND cf.custom_field_value = '
                || quote_literal(p_passport_country);
    END IF;

    -- Strip leading ' AND ' and append WHERE clause
    IF length(v_where) > 0 THEN
        v_sql := v_sql || ' WHERE ' || substring(v_where from 6);
    END IF;

    RETURN QUERY EXECUTE v_sql;
END;
$func$ LANGUAGE plpgsql;
"""

    with open("/app/optimized_search.sql", "w") as f:
        f.write(func_sql)

    cur.close()
    conn.close()
    print("Generated /app/indexes.sql and /app/optimized_search.sql")


if __name__ == "__main__":
    main()
