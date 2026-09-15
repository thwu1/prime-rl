-- Booking search function for postgres_air database
-- Searches across booking, flight, passenger, and custom_field tables

CREATE OR REPLACE FUNCTION search_bookings_full(
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
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        b.booking_id,
        b.booking_ref,
        b.booking_name,
        b.email,
        f.departure_airport,
        f.arrival_airport,
        f.scheduled_departure,
        p.last_name,
        p.first_name
    FROM booking b
    JOIN booking_leg bl ON bl.booking_id = b.booking_id
    JOIN flight f ON f.flight_id = bl.flight_id
    JOIN passenger p ON p.booking_id = b.booking_id
    LEFT JOIN custom_field cf ON cf.passenger_id = p.passenger_id
        AND cf.custom_field_name = 'passport_country'
    WHERE (p_email IS NULL OR lower(b.email) LIKE lower(p_email) || '%')
    AND (p_dep_airport IS NULL OR f.departure_airport = p_dep_airport)
    AND (p_arr_airport IS NULL OR f.arrival_airport = p_arr_airport)
    AND (p_dep_date IS NULL OR f.scheduled_departure >= p_dep_date
         AND f.scheduled_departure < p_dep_date + interval '1 day')
    AND (p_passenger_last_name IS NULL OR lower(p.last_name) LIKE lower(p_passenger_last_name) || '%')
    AND (p_passport_country IS NULL OR cf.custom_field_value = p_passport_country);
END;
$$ LANGUAGE plpgsql;
