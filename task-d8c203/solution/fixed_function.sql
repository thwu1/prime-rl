
-- Fixed version of select_booking_advanced
-- Addresses: injection, AND semantics, case-insensitive email,
-- and conditional join logic

CREATE OR REPLACE FUNCTION postgres_air.select_booking_advanced(
    p_email text DEFAULT NULL,
    p_last_name text DEFAULT NULL,
    p_departure_airport text DEFAULT NULL,
    p_arrival_airport text DEFAULT NULL,
    p_departure_date date DEFAULT NULL,
    p_booking_ref text DEFAULT NULL
)
RETURNS TABLE(
    out_booking_id int,
    out_booking_ref text,
    out_booking_name text,
    out_email text,
    out_departure_airport text,
    out_arrival_airport text,
    out_scheduled_departure timestamptz,
    out_passenger_last_name text
) AS $func$
DECLARE
    v_sql text;
    v_where text;
    v_need_booking_leg boolean := false;
    v_need_flight boolean := false;
    v_need_passenger boolean := false;
BEGIN
    -- Determine which tables are needed based on parameters
    IF p_departure_airport IS NOT NULL
       OR p_arrival_airport IS NOT NULL
       OR p_departure_date IS NOT NULL THEN
        v_need_flight := true;
        v_need_booking_leg := true;
    END IF;

    IF p_last_name IS NOT NULL THEN
        v_need_passenger := true;
    END IF;

    -- Build SELECT clause with NULLs for non-joined tables
    v_sql := 'SELECT DISTINCT b.booking_id, b.booking_ref, '
          || 'b.booking_name, b.email, ';

    IF v_need_flight THEN
        v_sql := v_sql || 'f.departure_airport::text, '
              || 'f.arrival_airport::text, '
              || 'f.scheduled_departure, ';
    ELSE
        v_sql := v_sql || 'NULL::text, NULL::text, NULL::timestamptz, ';
    END IF;

    IF v_need_passenger THEN
        v_sql := v_sql || 'p.last_name ';
    ELSE
        v_sql := v_sql || 'NULL::text ';
    END IF;

    -- FROM clause
    v_sql := v_sql || 'FROM postgres_air.booking b ';

    -- Conditional JOINs
    IF v_need_booking_leg THEN
        v_sql := v_sql
              || 'JOIN postgres_air.booking_leg bl '
              || 'ON bl.booking_id = b.booking_id ';
    END IF;

    IF v_need_flight THEN
        v_sql := v_sql
              || 'JOIN postgres_air.flight f '
              || 'ON f.flight_id = bl.flight_id ';
    END IF;

    IF v_need_passenger THEN
        v_sql := v_sql
              || 'JOIN postgres_air.passenger p '
              || 'ON p.booking_id = b.booking_id ';
    END IF;

    -- Build WHERE clause — ALL conditions use AND via concat_ws
    IF p_last_name IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'p.last_name = ' || quote_literal(p_last_name));
    END IF;

    IF p_email IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'lower(b.email) LIKE '
            || quote_literal(lower(p_email) || '%'));
    END IF;

    IF p_departure_airport IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.departure_airport = '
            || quote_literal(p_departure_airport));
    END IF;

    IF p_arrival_airport IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.arrival_airport = '
            || quote_literal(p_arrival_airport));
    END IF;

    IF p_departure_date IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'f.scheduled_departure BETWEEN '
            || quote_literal(p_departure_date) || '::date AND '
            || quote_literal(p_departure_date) || '::date + 1');
    END IF;

    IF p_booking_ref IS NOT NULL THEN
        v_where := concat_ws(' AND ', v_where,
            'b.booking_ref = ' || quote_literal(p_booking_ref));
    END IF;

    IF v_where IS NOT NULL THEN
        v_sql := v_sql || ' WHERE ' || v_where;
    END IF;

    RETURN QUERY EXECUTE v_sql;
END;
$func$ LANGUAGE plpgsql;
